from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(prefix="/profile", tags=["Profile"])

ActivityLevel = Literal[
    "sedentary", "light", "moderate", "high", "very_high", "unknown"
]
SexForFormula = Literal["female", "male", "other", "not_specified"]


class ProfileUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    date_of_birth: Optional[date] = None
    sex_for_formula: Optional[SexForFormula] = None
    activity_level: Optional[ActivityLevel] = None

    @model_validator(mode="after")
    def validate_display_name(self):
        if self.display_name is not None:
            self.display_name = self.display_name.strip()
            if not self.display_name:
                raise ValueError("display_name must not be blank")
        return self


class BodyMeasurementCreate(BaseModel):
    weight_kg: Optional[float] = Field(default=None, ge=0.5, le=500)
    height_cm: Optional[float] = Field(default=None, ge=30, le=250)

    @model_validator(mode="after")
    def require_measurement(self):
        if self.weight_kg is None and self.height_cm is None:
            raise ValueError("กรุณาระบุน้ำหนักหรือส่วนสูงอย่างน้อยหนึ่งรายการ")
        return self


@router.get("")
def read_profile(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    profile = db.execute(
        text("""
            SELECT
                display_name,
                date_of_birth,
                sex_for_formula,
                activity_level,
                preferred_language,
                time_zone
            FROM user_profiles
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().first()

    if profile is None:
        raise HTTPException(status_code=404, detail="ไม่พบโปรไฟล์ผู้ใช้")

    latest_measurement = db.execute(
        text("""
            SELECT
                body_measurement_id,
                measured_at,
                weight_kg,
                height_cm,
                source_type,
                verification_status
            FROM body_measurements
            WHERE user_id = :user_id
            ORDER BY measured_at DESC, body_measurement_id DESC
            LIMIT 1
        """),
        {"user_id": user_id},
    ).mappings().first()

    return {
        "profile": dict(profile),
        "latest_body_measurement": (
            dict(latest_measurement) if latest_measurement else None
        ),
    }


@router.patch("")
def update_profile(
    data: ProfileUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = data.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(status_code=422, detail="ไม่มีข้อมูลสำหรับแก้ไข")

    user_id = str(user["user_id"])

    # Only update explicitly supplied fields.
    assignments = []
    params = {"user_id": user_id}

    for field, value in changes.items():
        assignments.append("{} = :{}".format(field, field))
        params[field] = value

    assignments.append("updated_at = NOW()")

    result = db.execute(
        text("""
            UPDATE user_profiles
            SET {}
            WHERE user_id = :user_id
            RETURNING
                display_name,
                date_of_birth,
                sex_for_formula,
                activity_level,
                preferred_language,
                time_zone
        """.format(", ".join(assignments))),
        params,
    ).mappings().first()

    if result is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="ไม่พบโปรไฟล์ผู้ใช้")

    db.commit()
    return {"profile": dict(result)}


@router.post("/body-measurements", status_code=201)
def create_body_measurement(
    data: BodyMeasurementCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    measurement = db.execute(
        text("""
            INSERT INTO body_measurements (
                user_id,
                weight_kg,
                height_cm,
                source_type,
                verification_status,
                measured_at
            )
            VALUES (
                :user_id,
                :weight_kg,
                :height_cm,
                'user_entered',
                'user_confirmed',
                NOW()
            )
            RETURNING
                body_measurement_id,
                measured_at,
                weight_kg,
                height_cm,
                source_type,
                verification_status
        """),
        {
            "user_id": user_id,
            "weight_kg": data.weight_kg,
            "height_cm": data.height_cm,
        },
    ).mappings().first()

    db.commit()
    return {"measurement": dict(measurement)}
