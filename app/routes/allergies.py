from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(prefix="/allergies", tags=["Allergies"])

AllergyStatus = Literal[
    "not_asked",
    "unknown",
    "none_reported",
    "has_reported_allergies",
]


class AllergyProfileUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    allergy_status: AllergyStatus


class AllergyCreate(BaseModel):
    model_config = {"extra": "forbid"}

    allergen_code: str = Field(min_length=1, max_length=100)
    display_label: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def trim_values(self):
        self.allergen_code = self.allergen_code.strip()
        self.display_label = self.display_label.strip()

        if not self.allergen_code or not self.display_label:
            raise ValueError("กรุณาระบุรหัสและชื่อสารก่อภูมิแพ้")

        if self.notes is not None:
            self.notes = self.notes.strip() or None

        return self


class AllergyUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    allergen_code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    display_label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)
    confirmation_status: Optional[
        Literal["reported_unconfirmed", "user_confirmed"]
    ] = None

    @model_validator(mode="after")
    def trim_values(self):
        for field in ("allergen_code", "display_label"):
            value = getattr(self, field)
            if value is not None:
                value = value.strip()
                if not value:
                    raise ValueError(f"{field} must not be blank")
                setattr(self, field, value)

        if self.notes is not None:
            self.notes = self.notes.strip() or None

        return self


def require_health_data_consent(db: Session, user_id: str):
    consent = db.execute(
        text("""
            SELECT consent_id
            FROM user_consents
            WHERE user_id = :user_id
              AND consent_type = 'health_data_storage'
              AND withdrawn_at IS NULL
            ORDER BY consented_at DESC, consent_id DESC
            LIMIT 1
        """),
        {"user_id": user_id},
    ).mappings().first()

    if consent is None:
        raise HTTPException(
            status_code=403,
            detail="กรุณาให้ความยินยอมในการจัดเก็บข้อมูลสุขภาพก่อน",
        )


@router.get("")
def read_allergies(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    require_health_data_consent(db, user_id)

    profile = db.execute(
        text("""
            SELECT allergy_status, source_type, updated_at
            FROM user_allergy_profiles
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().first()

    rows = db.execute(
        text("""
            SELECT
                allergy_id,
                allergen_code,
                display_label,
                confirmation_status,
                source_type,
                notes,
                created_at,
                updated_at
            FROM user_allergies
            WHERE user_id = :user_id
              AND confirmation_status <> 'inactive'
            ORDER BY created_at DESC, allergy_id DESC
        """),
        {"user_id": user_id},
    ).mappings().all()

    return {
        "profile": dict(profile) if profile else {
            "allergy_status": "not_asked",
            "source_type": "user_reported",
            "updated_at": None,
        },
        "allergies": [dict(row) for row in rows],
    }


@router.put("/profile")
def update_allergy_profile(
    data: AllergyProfileUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    require_health_data_consent(db, user_id)

    if data.allergy_status == "has_reported_allergies":
        count = db.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM user_allergies
                WHERE user_id = :user_id
                  AND confirmation_status <> 'inactive'
            """),
            {"user_id": user_id},
        ).mappings().first()

        if count and count["total"] == 0:
            raise HTTPException(
                status_code=422,
                detail="เพิ่มรายการแพ้อาหารก่อนเลือกสถานะนี้",
            )

    profile = db.execute(
        text("""
            INSERT INTO user_allergy_profiles (
                user_id, allergy_status, source_type, updated_at
            )
            VALUES (:user_id, :allergy_status, 'user_reported', NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET allergy_status = EXCLUDED.allergy_status,
                source_type = 'user_reported',
                updated_at = NOW()
            RETURNING allergy_status, source_type, updated_at
        """),
        {
            "user_id": user_id,
            "allergy_status": data.allergy_status,
        },
    ).mappings().one()

    db.commit()
    return {"profile": dict(profile)}


@router.post("", status_code=201)
def create_allergy(
    data: AllergyCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    require_health_data_consent(db, user_id)

    try:
        record = db.execute(
            text("""
                INSERT INTO user_allergies (
                    user_id, allergen_code, display_label,
                    confirmation_status, source_type, notes
                )
                VALUES (
                    :user_id, :allergen_code, :display_label,
                    'reported_unconfirmed', 'user_reported', :notes
                )
                RETURNING
                    allergy_id, allergen_code, display_label,
                    confirmation_status, source_type, notes,
                    created_at, updated_at
            """),
            {
                "user_id": user_id,
                "allergen_code": data.allergen_code,
                "display_label": data.display_label,
                "notes": data.notes,
            },
        ).mappings().one()

        db.execute(
            text("""
                INSERT INTO user_allergy_profiles (
                    user_id, allergy_status, source_type, updated_at
                )
                VALUES (
                    :user_id, 'has_reported_allergies',
                    'user_reported', NOW()
                )
                ON CONFLICT (user_id) DO UPDATE
                SET allergy_status = 'has_reported_allergies',
                    source_type = 'user_reported',
                    updated_at = NOW()
            """),
            {"user_id": user_id},
        )
        db.commit()
        return {"allergy": dict(record)}
    except Exception:
        db.rollback()
        raise


@router.patch("/{allergy_id}")
def update_allergy(
    allergy_id: str,
    data: AllergyUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    try:
        allergy_id = str(UUID(allergy_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="รูปแบบ allergy_id ไม่ถูกต้อง")

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="ไม่มีข้อมูลสำหรับแก้ไข")

    # Deactivation is permitted even after consent withdrawal so users
    # can stop using an entry. Other changes require active consent.
    deactivating_only = (
        set(changes) == {"confirmation_status"}
        and changes["confirmation_status"] == "inactive"
    )
    if not deactivating_only:
        require_health_data_consent(db, user_id)

    assignments = []
    params = {"user_id": user_id, "allergy_id": allergy_id}

    for field, value in changes.items():
        assignments.append(f"{field} = :{field}")
        params[field] = value

    assignments.append("updated_at = NOW()")

    try:
        record = db.execute(
            text("""
                UPDATE user_allergies
                SET {}
                WHERE allergy_id = CAST(:allergy_id AS uuid)
                  AND user_id = :user_id
                  AND confirmation_status <> 'inactive'
                RETURNING
                    allergy_id, allergen_code, display_label,
                    confirmation_status, source_type, notes,
                    created_at, updated_at
            """.format(", ".join(assignments))),
            params,
        ).mappings().first()

        if record is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="ไม่พบรายการแพ้ในบัญชีนี้")

        db.commit()
        return {"allergy": dict(record)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


@router.delete("/{allergy_id}", status_code=204)
def deactivate_allergy(
    allergy_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    try:
        allergy_id = str(UUID(allergy_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="รูปแบบ allergy_id ไม่ถูกต้อง")

    try:
        result = db.execute(
            text("""
                UPDATE user_allergies
                SET confirmation_status = 'inactive',
                    updated_at = NOW()
                WHERE allergy_id = CAST(:allergy_id AS uuid)
                  AND user_id = :user_id
                  AND confirmation_status <> 'inactive'
                RETURNING allergy_id
            """),
            {"allergy_id": allergy_id, "user_id": user_id},
        ).mappings().first()

        if result is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="ไม่พบรายการแพ้ในบัญชีนี้")

        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
