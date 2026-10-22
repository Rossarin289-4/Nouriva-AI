from typing import Any, Dict, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(prefix="/consents", tags=["Consents"])

ConsentType = Literal[
    "privacy_policy",
    "external_ai_processing",
    "research_participation",
    "terms_of_service",
    "health_data_storage",
]


class ConsentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    consent_type: ConsentType
    policy_version: str = Field(min_length=1, max_length=50)
    consent_metadata: Dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_consents(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    rows = db.execute(
        text("""
            SELECT
                consent_id,
                consent_type,
                policy_version,
                consented_at,
                withdrawn_at,
                consent_metadata
            FROM user_consents
            WHERE user_id = :user_id
            ORDER BY consented_at DESC, consent_id DESC
        """),
        {"user_id": user_id},
    ).mappings().all()

    return {"consents": [dict(row) for row in rows]}


@router.post("", status_code=201)
def create_consent(
    data: ConsentCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    policy_version = data.policy_version.strip()

    if not policy_version:
        raise HTTPException(
            status_code=422,
            detail="กรุณาระบุเวอร์ชันนโยบาย",
        )

    # A consent record represents an explicit action by the signed-in user.
    # Do not create consent automatically during registration.
    record = db.execute(
        text("""
            INSERT INTO user_consents (
                user_id,
                consent_type,
                policy_version,
                consented_at,
                consent_metadata
            )
            VALUES (
                :user_id,
                :consent_type,
                :policy_version,
                NOW(),
                CAST(:consent_metadata AS jsonb)
            )
            RETURNING
                consent_id,
                consent_type,
                policy_version,
                consented_at,
                withdrawn_at,
                consent_metadata
        """),
        {
            "user_id": user_id,
            "consent_type": data.consent_type,
            "policy_version": policy_version,
            "consent_metadata": __import__("json").dumps(
                data.consent_metadata
            ),
        },
    ).mappings().one()

    db.commit()
    return {"consent": dict(record)}


@router.post("/{consent_id}/withdraw")
def withdraw_consent(
    consent_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    try:
        consent_id = str(UUID(consent_id))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="รูปแบบ consent_id ไม่ถูกต้อง",
        )

    # Scope the update to the authenticated user and only an active record.
    record = db.execute(
        text("""
            UPDATE user_consents
            SET withdrawn_at = NOW()
            WHERE consent_id = CAST(:consent_id AS uuid)
              AND user_id = :user_id
              AND withdrawn_at IS NULL
            RETURNING
                consent_id,
                consent_type,
                policy_version,
                consented_at,
                withdrawn_at,
                consent_metadata
        """),
        {
            "consent_id": consent_id,
            "user_id": user_id,
        },
    ).mappings().first()

    if record is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="ไม่พบรายการความยินยอมที่ยังใช้งานได้ในบัญชีนี้",
        )

    db.commit()
    return {"consent": dict(record)}
