"""Authenticated AI chat routes with explicit consent and usage controls."""

import json
import os
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.ai_chat import AIChatError, chat as run_ai_chat


router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])

AI_CHAT_CONSENT_VERSION = "1.0"
BANGKOK = ZoneInfo("Asia/Bangkok")
RESERVATION_MINUTES = 2
OPENAI_FREE_DAILY_LIMIT = 10

# Premium remains disabled until a budget-backed limit is deliberately set.
def _premium_openai_daily_limit():
    raw = os.getenv("NOURIVAAI_OPENAI_PREMIUM_DAILY_LIMIT", "").strip()
    if not raw:
        return None
    try:
        limit = int(raw)
    except ValueError:
        return None
    return limit if limit > OPENAI_FREE_DAILY_LIMIT else None


class ChatRequest(BaseModel):
    model_config = {"extra": "forbid"}

    provider: str
    message: str = Field(min_length=1, max_length=4000)


def _require_ai_chat_consent(db, user_id):
    row = db.execute(
        text("""
            SELECT consent_id
            FROM public.user_consents
            WHERE user_id = :user_id
              AND consent_type = 'external_ai_processing'
              AND policy_version = :policy_version
              AND withdrawn_at IS NULL
              AND consent_metadata->>'purpose' = 'ai_chat'
            ORDER BY consented_at DESC, consent_id DESC
            LIMIT 1
        """),
        {
            "user_id": user_id,
            "policy_version": AI_CHAT_CONSENT_VERSION,
        },
    ).first()

    if row is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ai_chat_consent_required",
                "message": (
                    "กรุณาอ่านและยอมรับความยินยอมสำหรับ AI Chat "
                    "ก่อนส่งข้อความ"
                ),
                "consent_type": "external_ai_processing",
                "purpose": "ai_chat",
                "policy_version": AI_CHAT_CONSENT_VERSION,
            },
        )


def _get_plan(db, user_id):
    try:
        row = db.execute(
            text("""
                SELECT ai_plan
                FROM public.app_users
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        ).mappings().first()
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="ระบบสิทธิ์ AI Chat ยังไม่พร้อม กรุณาลองใหม่ภายหลัง",
        ) from error

    if row is None:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบใหม่")

    plan = row.get("ai_plan")
    if plan not in ("free", "premium"):
        raise HTTPException(status_code=503, detail="ไม่สามารถตรวจสอบสิทธิ์ AI Chat ได้")

    return plan


def _limit_for(provider, plan):
    if provider == "gemini":
        return None

    if provider == "openai" and plan == "free":
        return OPENAI_FREE_DAILY_LIMIT

    if provider == "openai" and plan == "premium":
        return _premium_openai_daily_limit()

    return None


def _provider_configured(provider):
    if provider == "gemini":
        key = os.getenv("NOURIVAAI_GEMINI_API_KEY", "").strip()
        model = os.getenv("NOURIVAAI_GEMINI_MODEL", "gemini-2.5-flash").strip()
    elif provider == "openai":
        key = os.getenv("NOURIVAAI_OPENAI_API_KEY", "").strip()
        model = os.getenv("NOURIVAAI_OPENAI_MODEL", "gpt-4.1-mini").strip()
    else:
        return False

    return bool(key and model)


def _usage_counts(db, user_id, provider, usage_date):
    row = db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE status = 'succeeded'
                ) AS used,
                COUNT(*) FILTER (
                    WHERE status = 'reserved'
                      AND reservation_expires_at > NOW()
                ) AS reserved
            FROM public.ai_chat_usage_events
            WHERE user_id = :user_id
              AND provider = :provider
              AND usage_date = :usage_date
        """),
        {
            "user_id": user_id,
            "provider": provider,
            "usage_date": usage_date,
        },
    ).mappings().one()

    return int(row["used"]), int(row["reserved"])


def _reserve_usage(db, user_id, provider, usage_date, limit):
    """Reserve one OpenAI message atomically; Gemini is logged without a cap."""
    reservation_id = None
    try:
        # Serializes reservations for this user/provider/day across concurrent requests.
        lock_key = f"ai-chat:{user_id}:{provider}:{usage_date.isoformat()}"
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

        # Recover reservations left behind by crashed requests.
        db.execute(
            text("""
                UPDATE public.ai_chat_usage_events
                SET status = 'failed',
                    completed_at = NOW()
                WHERE user_id = :user_id
                  AND provider = :provider
                  AND usage_date = :usage_date
                  AND status = 'reserved'
                  AND reservation_expires_at <= NOW()
            """),
            {
                "user_id": user_id,
                "provider": provider,
                "usage_date": usage_date,
            },
        )

        used, reserved = _usage_counts(db, user_id, provider, usage_date)
        if limit is not None and used + reserved >= limit:
            db.rollback()
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "ai_chat_quota_exceeded",
                    "message": "คุณใช้โควตา OpenAI ของวันนี้ครบแล้ว",
                    "provider": provider,
                    "daily_limit": limit,
                    "used": used,
                    "remaining": 0,
                    "reset_timezone": "Asia/Bangkok",
                },
            )

        row = db.execute(
            text("""
                INSERT INTO public.ai_chat_usage_events (
                    user_id,
                    provider,
                    usage_date,
                    status,
                    created_at,
                    reservation_expires_at
                )
                VALUES (
                    :user_id,
                    :provider,
                    :usage_date,
                    'reserved',
                    NOW(),
                    NOW() + (:reservation_minutes * INTERVAL '1 minute')
                )
                RETURNING usage_event_id
            """),
            {
                "user_id": user_id,
                "provider": provider,
                "usage_date": usage_date,
                "reservation_minutes": RESERVATION_MINUTES,
            },
        ).mappings().one()

        reservation_id = str(row["usage_event_id"])
        db.commit()
        return reservation_id

    except HTTPException:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="ไม่สามารถจองโควตา AI Chat ได้ กรุณาลองใหม่ภายหลัง",
        ) from error


def _finish_usage(db, reservation_id, succeeded):
    """Return whether the reservation status was persisted successfully."""
    try:
        result = db.execute(
            text("""
                UPDATE public.ai_chat_usage_events
                SET status = :status,
                    completed_at = NOW()
                WHERE usage_event_id = CAST(:usage_event_id AS uuid)
                  AND status = 'reserved'
            """),
            {
                "usage_event_id": reservation_id,
                "status": "succeeded" if succeeded else "failed",
            },
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True
    except SQLAlchemyError:
        db.rollback()
        return False


@router.get("/status")
def ai_chat_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(UUID(str(user["user_id"])))
    _require_ai_chat_consent(db, user_id)
    plan = _get_plan(db, user_id)

    today = datetime.now(BANGKOK).date()
    result = {}

    for provider in ("gemini", "openai"):
        limit = _limit_for(provider, plan)
        try:
            used, reserved = _usage_counts(db, user_id, provider, today)
        except SQLAlchemyError as error:
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="ระบบโควตา AI Chat ยังไม่พร้อม",
            ) from error

        result[provider] = {
            "configured": _provider_configured(provider),
            "daily_limit": limit,
            "used": used,
            "reserved": reserved,
            "remaining": None if limit is None else max(0, limit - used - reserved),
            "quota_enforced": limit is not None,
        }

    return {
        "plan": plan,
        "consent": {
            "purpose": "ai_chat",
            "policy_version": AI_CHAT_CONSENT_VERSION,
        },
        "reset_timezone": "Asia/Bangkok",
        "usage_date": today.isoformat(),
        "providers": result,
    }


@router.post("")
def send_ai_chat(
    data: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = data.provider.strip().lower()
    if provider not in ("gemini", "openai"):
        raise HTTPException(
            status_code=422,
            detail="เลือก provider เป็น gemini หรือ openai เท่านั้น",
        )

    message = data.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="กรุณาพิมพ์ข้อความก่อนส่ง")

    user_id = str(UUID(str(user["user_id"])))
    _require_ai_chat_consent(db, user_id)
    plan = _get_plan(db, user_id)

    limit = _limit_for(provider, plan)
    if provider == "openai" and limit is None:
        raise HTTPException(
            status_code=403,
            detail="สิทธิ์ OpenAI สำหรับแผนนี้ยังไม่เปิดใช้งาน",
        )

    today = datetime.now(BANGKOK).date()
    reservation_id = _reserve_usage(
        db, user_id, provider, today, limit
    )

    try:
        response = run_ai_chat(provider, message)
    except AIChatError as error:
        _finish_usage(db, reservation_id, succeeded=False)
        raise HTTPException(
            status_code=error.status_code,
            detail=str(error),
        ) from error
    except Exception as error:
        _finish_usage(db, reservation_id, succeeded=False)
        raise HTTPException(
            status_code=503,
            detail="AI Chat ไม่สามารถตอบกลับได้ในขณะนี้",
        ) from error

    usage_recorded = _finish_usage(db, reservation_id, succeeded=True)

    return {
        "provider": response["provider"],
        "model": response["model"],
        "message": response["message"],
        "usage": {
            "plan": plan,
            "daily_limit": limit,
            "quota_enforced": limit is not None,
            "usage_date": today.isoformat(),
            "reset_timezone": "Asia/Bangkok",
            "status_recorded": usage_recorded,
        },
        "warning": (
            None if usage_recorded else
            "AI ตอบกลับแล้ว แต่ระบบบันทึกสถานะโควตาไม่สำเร็จ "
            "กรุณาตรวจสอบสถานะการใช้งานก่อนส่งข้อความซ้ำ"
        ),
    }
