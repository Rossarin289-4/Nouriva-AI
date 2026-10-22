import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
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
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=JWT_ALGORITHM)


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

    # รองรับ Bearer token สำหรับ API และ HttpOnly cookie สำหรับหน้าเว็บ
    token = (
        credentials.credentials
        if credentials is not None
        else request.cookies.get("nouriva_access_token")
    )
    if not token:
        raise unauthorized

    try:
        payload = jwt.decode(
            token,
            get_secret_key(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        user_id = str(UUID(payload["sub"]))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized

    user = db.execute(
        text("""
            SELECT user_id, email, role, is_active, email_verified_at
            FROM app_users
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().first()

    if user is None or not user["is_active"]:
        raise unauthorized

    return user


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
            FROM app_users
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
                INSERT INTO app_users (
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
                INSERT INTO user_profiles (
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


def cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"


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
            FROM app_users
            WHERE lower(email) = :email
        """),
        {"email": email},
    ).mappings().first()

    # ใช้ข้อความเดียวกันเมื่ออีเมลไม่มีหรือรหัสผ่านผิด
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

    response.set_cookie(
        key="nouriva_access_token",
        value=token,
        max_age=TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )

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
            FROM user_profiles
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
def logout(response: Response):
    response.delete_cookie(
        key="nouriva_access_token",
        path="/",
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )
    return {"message": "ออกจากระบบแล้ว"}


@router.post("/guest", status_code=201)
def create_guest(response: Response, db: Session = Depends(get_db)):
    """Create a database-backed guest account with no real email address."""
    guest_email = f"guest-{uuid4().hex}@guest.nouriva.invalid"
    random_password = secrets.token_urlsafe(32)
    password_hash = password_hasher.hash(random_password)

    try:
        user = db.execute(
            text("""
                INSERT INTO app_users (
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
                INSERT INTO user_profiles (
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
    response.set_cookie(
        key="nouriva_access_token",
        value=token,
        max_age=TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )

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
