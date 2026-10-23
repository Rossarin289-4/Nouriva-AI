import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)

TOKEN_TTL_MINUTES = 60
JWT_ALGORITHM = "HS256"
AUTH_COOKIE_NAME = "nouriva_access_token"


def get_secret_key():
    key = os.getenv("AUTH_SECRET_KEY")
    if not key or len(key) < 32:
        raise RuntimeError(
            "AUTH_SECRET_KEY must be configured with a strong secret"
        )
    return key


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


def normalize_email(raw_email: str) -> str:
    try:
        result = validate_email(
            raw_email.strip(),
            check_deliverability=False,
        )
        return result.normalized.lower()
    except EmailNotValidError:
        raise HTTPException(
            status_code=422,
            detail="รูปแบบอีเมลไม่ถูกต้อง",
        )


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(
        payload,
        get_secret_key(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        get_secret_key(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat", "jti"]},
    )


def get_token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials = None,
):
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(AUTH_COOKIE_NAME)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    unauthorized = HTTPException(
        status_code=401,
        detail="กรุณาเข้าสู่ระบบใหม่",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = get_token_from_request(request, credentials)
    if not token:
        raise unauthorized

    try:
        payload = decode_access_token(token)
        user_id = str(UUID(payload["sub"]))
        token_jti = str(UUID(payload["jti"]))
        expires_at = datetime.fromtimestamp(
            payload["exp"],
            tz=timezone.utc,
        )
    except (
        jwt.InvalidTokenError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        OSError,
    ):
        raise unauthorized

    if expires_at <= datetime.now(timezone.utc):
        raise unauthorized

    revoked = db.execute(
        text("""
            SELECT 1
            FROM public.revoked_auth_tokens
            WHERE token_jti = :token_jti
        """),
        {"token_jti": token_jti},
    ).first()

    if revoked:
        raise unauthorized

    user = db.execute(
        text("""
            SELECT user_id, email, role, is_active, email_verified_at
            FROM public.app_users
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().first()

    if user is None or not user["is_active"]:
        raise unauthorized

    return user


def cookie_secure() -> bool:
    return (
        os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower()
        == "true"
    )


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )


@router.post("/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    display_name = data.display_name.strip()

    if not display_name:
        raise HTTPException(
            status_code=422,
            detail="กรุณาระบุชื่อที่แสดง",
        )

    existing = db.execute(
        text("""
            SELECT user_id
            FROM public.app_users
            WHERE lower(email) = :email
        """),
        {"email": email},
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="อีเมลนี้มีบัญชีแล้ว กรุณาเข้าสู่ระบบ",
        )

    password_hash = password_hasher.hash(data.password)

    try:
        user = db.execute(
            text("""
                INSERT INTO public.app_users (
                    email, password_hash, role, is_active,
                    created_at, updated_at
                )
                VALUES (
                    :email, :password_hash, 'user', TRUE,
                    NOW(), NOW()
                )
                RETURNING user_id, email, role, is_active,
                          email_verified_at, created_at
            """),
            {
                "email": email,
                "password_hash": password_hash,
            },
        ).mappings().one()

        db.execute(
            text("""
                INSERT INTO public.user_profiles (
                    user_id, display_name,
                    preferred_language, time_zone,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, :display_name,
                    'th', 'Asia/Bangkok', NOW(), NOW()
                )
            """),
            {
                "user_id": str(user["user_id"]),
                "display_name": display_name,
            },
        )

        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="ไม่สามารถสมัครได้ อีเมลนี้อาจมีบัญชีแล้ว",
        )
    except Exception:
        db.rollback()
        raise

    return {
        "message": "สมัครสมาชิกสำเร็จ กรุณาเข้าสู่ระบบ",
        "user": {
            "user_id": str(user["user_id"]),
            "email": user["email"],
            "role": user["role"],
            "is_active": user["is_active"],
            "email_verified": user["email_verified_at"] is not None,
            "created_at": user["created_at"],
        },
    }


@router.post("/login")
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    email = normalize_email(data.email)

    user = db.execute(
        text("""
            SELECT user_id, email, password_hash, role,
                   is_active, email_verified_at
            FROM public.app_users
            WHERE lower(email) = :email
        """),
        {"email": email},
    ).mappings().first()

    invalid_login = HTTPException(
        status_code=401,
        detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง",
    )

    if user is None:
        raise invalid_login

    try:
        password_hasher.verify(user["password_hash"], data.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise invalid_login

    if not user["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="บัญชีนี้ถูกระงับการใช้งาน",
        )

    token = create_access_token(str(user["user_id"]))
    set_auth_cookie(response, token)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_TTL_MINUTES * 60,
        "user": {
            "user_id": str(user["user_id"]),
            "email": user["email"],
            "role": user["role"],
            "email_verified": user["email_verified_at"] is not None,
        },
    }


@router.get("/me")
def read_current_user(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.execute(
        text("""
            SELECT display_name, preferred_language, time_zone
            FROM public.user_profiles
            WHERE user_id = :user_id
        """),
        {"user_id": str(user["user_id"])},
    ).mappings().first()

    return {
        "user": {
            "user_id": str(user["user_id"]),
            "email": user["email"],
            "role": user["role"],
            "is_active": user["is_active"],
            "email_verified": user["email_verified_at"] is not None,
            "profile": dict(profile) if profile else None,
        }
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    token = get_token_from_request(request, credentials)

    if token:
        try:
            payload = decode_access_token(token)
            token_jti = str(UUID(payload["jti"]))
            user_id = str(UUID(payload["sub"]))
            expires_at = datetime.fromtimestamp(
                payload["exp"],
                tz=timezone.utc,
            )

            if expires_at > datetime.now(timezone.utc):
                db.execute(
                    text("""
                        INSERT INTO public.revoked_auth_tokens (
                            token_jti, user_id, expires_at
                        )
                        VALUES (
                            :token_jti, :user_id, :expires_at
                        )
                        ON CONFLICT (token_jti) DO NOTHING
                    """),
                    {
                        "token_jti": token_jti,
                        "user_id": user_id,
                        "expires_at": expires_at,
                    },
                )
                db.commit()

        except (
            jwt.InvalidTokenError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            OSError,
        ):
            # Token ไม่ถูกต้องก็ยังลบ cookie ให้ผู้ใช้ได้
            db.rollback()
        except Exception:
            # หากบันทึกการเพิกถอนล้มเหลว ห้ามตอบว่าสำเร็จ
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="ไม่สามารถออกจากระบบได้ในขณะนี้ กรุณาลองอีกครั้ง",
            )

    clear_auth_cookie(response)
    return {"message": "ออกจากระบบแล้ว"}


@router.post("/guest", status_code=201)
def create_guest(response: Response, db: Session = Depends(get_db)):
    guest_email = f"guest-{uuid4().hex}@guest.nouriva.invalid"
    random_password = secrets.token_urlsafe(32)
    password_hash = password_hasher.hash(random_password)

    try:
        user = db.execute(
            text("""
                INSERT INTO public.app_users (
                    email, password_hash, role, account_type,
                    is_active, created_at, updated_at
                )
                VALUES (
                    :email, :password_hash, 'user', 'guest',
                    TRUE, NOW(), NOW()
                )
                RETURNING user_id, role, account_type, is_active
            """),
            {
                "email": guest_email,
                "password_hash": password_hash,
            },
        ).mappings().one()

        db.execute(
            text("""
                INSERT INTO public.user_profiles (
                    user_id, display_name,
                    preferred_language, time_zone,
                    created_at, updated_at
                )
                VALUES (
                    :user_id, 'Guest',
                    'th', 'Asia/Bangkok', NOW(), NOW()
                )
            """),
            {"user_id": str(user["user_id"])},
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    token = create_access_token(str(user["user_id"]))
    set_auth_cookie(response, token)

    return {
        "message": "เข้าใช้งานแบบ Guest สำเร็จ",
        "user": {
            "user_id": str(user["user_id"]),
            "account_type": "guest",
            "role": "user",
            "is_active": True,
            "email_notifications_available": False,
        },
    }
