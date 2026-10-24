import json
from decimal import Decimal
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.openfoodfacts import (
    OpenFoodFactsUnavailable,
    lookup_barcode as lookup_openfoodfacts_barcode,
)

router = APIRouter(prefix="/meals", tags=["Meals"])

MealType = Literal["breakfast", "lunch", "dinner", "snack", "other"]


class MealCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_date: date
    meal_type: MealType
    eaten_at: Optional[datetime] = None
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("title", "notes")
    @classmethod
    def strip_optional_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


class MealUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_date: Optional[date] = None
    meal_type: Optional[MealType] = None
    eaten_at: Optional[datetime] = None
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("title", "notes")
    @classmethod
    def strip_optional_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("กรุณาระบุข้อมูลที่ต้องการแก้ไข")
        if "meal_date" in self.model_fields_set and self.meal_date is None:
            raise ValueError("meal_date ต้องไม่เป็นค่าว่าง")
        if "meal_type" in self.model_fields_set and self.meal_type is None:
            raise ValueError("meal_type ต้องไม่เป็นค่าว่าง")
        return self


@router.post("", status_code=201)
def create_meal(
    data: MealCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    meal = db.execute(
        text("""
            INSERT INTO meal_logs (
                user_id,
                meal_date,
                meal_type,
                eaten_at,
                title,
                notes,
                created_at,
                updated_at
            )
            VALUES (
                :user_id,
                :meal_date,
                :meal_type,
                :eaten_at,
                :title,
                :notes,
                NOW(),
                NOW()
            )
            RETURNING
                meal_log_id,
                meal_date,
                meal_type,
                eaten_at,
                title,
                notes,
                created_at,
                updated_at
        """),
        {
            "user_id": user_id,
            "meal_date": data.meal_date,
            "meal_type": data.meal_type,
            "eaten_at": data.eaten_at,
            "title": data.title,
            "notes": data.notes,
        },
    ).mappings().first()

    if meal is None:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="ไม่สามารถบันทึกมื้ออาหารได้",
        )

    db.commit()
    return {"status": "success", "meal": dict(meal)}


@router.get("")
def list_meals(
    meal_date: Optional[date] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])

    rows = db.execute(
        text("""
            SELECT
                meal_log_id,
                meal_date,
                meal_type,
                eaten_at,
                title,
                notes,
                created_at,
                updated_at
            FROM meal_logs
            WHERE user_id = :user_id
              AND (
                  CAST(:meal_date AS date) IS NULL
                  OR meal_date = :meal_date
              )
            ORDER BY meal_date DESC, eaten_at DESC NULLS LAST,
                     created_at DESC
            LIMIT :limit
            OFFSET :offset
        """),
        {
            "user_id": user_id,
            "meal_date": meal_date,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()

    return {
        "status": "success",
        "count": len(rows),
        "items": [dict(row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.patch("/{meal_log_id}")
def update_meal(
    meal_log_id: UUID,
    data: MealUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="ไม่มีข้อมูลให้แก้ไข")

    allowed_columns = {
        "meal_date": "meal_date",
        "meal_type": "meal_type",
        "eaten_at": "eaten_at",
        "title": "title",
        "notes": "notes",
    }
    assignments = []
    params = {
        "meal_log_id": str(meal_log_id),
        "user_id": str(user["user_id"]),
    }
    for field, value in changes.items():
        assignments.append(f"{allowed_columns[field]} = :{field}")
        params[field] = value
    assignments.append("updated_at = NOW()")

    row = db.execute(
        text(f"""
            UPDATE meal_logs
            SET {", ".join(assignments)}
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
            RETURNING
                meal_log_id,
                meal_date,
                meal_type,
                eaten_at,
                title,
                notes,
                created_at,
                updated_at
        """),
        params,
    ).mappings().first()

    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    db.commit()
    return {"status": "success", "meal": dict(row)}


@router.delete("/{meal_log_id}", status_code=204)
def delete_meal(
    meal_log_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meal_id = str(meal_log_id)
    user_id = str(user["user_id"])
    owned = db.execute(
        text("""
            SELECT meal_log_id
            FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
            FOR UPDATE
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if owned is None:
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    db.execute(
        text("DELETE FROM meal_items WHERE meal_log_id = :meal_log_id"),
        {"meal_log_id": meal_id},
    )
    deleted = db.execute(
        text("""
            DELETE FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
            RETURNING meal_log_id
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if deleted is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    db.commit()
    return None


QuantityUnit = Literal["g", "ml", "piece", "serving", "package", "portion"]
EntrySource = Literal["manual", "search", "food_image", "barcode", "ocr", "import"]


class MealItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    food_id: Optional[UUID] = None
    food_name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    preparation_state: Optional[str] = Field(default=None, max_length=200)
    quantity_value: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    quantity_unit: QuantityUnit
    weight_g: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    volume_ml: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    portion_id: Optional[UUID] = None
    entry_source: EntrySource = "manual"
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("food_name", "preparation_state", "notes")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_food_fields(self):
        if self.food_id is None and not self.food_name:
            raise ValueError("กรุณาระบุ food_id หรือ food_name")
        if self.quantity_unit == "portion" and self.portion_id is None:
            raise ValueError("หน่วย portion ต้องระบุ portion_id")
        if self.portion_id is not None and self.food_id is None:
            raise ValueError("การเลือก portion ต้องระบุ food_id")
        return self


class ExternalMealItemCreate(BaseModel):
    """Explicitly confirmed save of an unverified Open Food Facts product."""

    model_config = ConfigDict(extra="forbid")

    barcode: str = Field(pattern=r"^[0-9]{8,14}$")
    quantity_value: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    quantity_unit: Literal["g", "ml", "piece", "serving", "package"]
    confirm_add: Literal[True]
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def strip_external_notes(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


@router.post("/{meal_log_id}/external-items", status_code=201)
def add_external_food_to_meal(
    meal_log_id: UUID,
    data: ExternalMealItemCreate,
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a confirmed external product as unverified, then attach it to an owned meal."""
    meal_id = str(meal_log_id)
    user_id = str(user["user_id"])
    try:
        owned = db.execute(
            text("""
                SELECT meal_log_id
                FROM meal_logs
                WHERE meal_log_id = :meal_log_id
                  AND user_id = :user_id
            """),
            {"meal_log_id": meal_id, "user_id": user_id},
        ).mappings().first()
        if owned is None:
            raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")
        # Do not keep a database transaction open during the upstream request.
        db.rollback()
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="ตรวจสอบมื้ออาหารไม่สำเร็จ กรุณาลองอีกครั้ง"
        ) from error

    try:
        external = lookup_openfoodfacts_barcode(data.barcode)
    except OpenFoodFactsUnavailable as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    if external is None:
        raise HTTPException(status_code=404, detail="ไม่พบสินค้านี้ใน Open Food Facts")

    if not isinstance(external, dict):
        raise HTTPException(
            status_code=502, detail="ข้อมูลสินค้าจาก Open Food Facts ไม่ถูกต้อง"
        )
    item = external.get("item")
    source = external.get("source")
    name = item.get("name") if isinstance(item, dict) else None
    source_url = source.get("source_url") if isinstance(source, dict) else None
    parsed_source_url = urlparse(source_url if isinstance(source_url, str) else "")
    if (
        external.get("status") != "external_unverified"
        or not isinstance(item, dict)
        or item.get("verification_status") != "external_unverified"
        or item.get("barcode") != data.barcode
        or not isinstance(name, str)
        or not name.strip()
        or not isinstance(source, dict)
        or not isinstance(source_url, str)
        or source.get("source_code") != "OPEN_FOOD_FACTS"
        or parsed_source_url.scheme != "https"
        or parsed_source_url.hostname != "world.openfoodfacts.org"
    ):
        raise HTTPException(
            status_code=502,
            detail="ข้อมูลสินค้าจาก Open Food Facts ไม่ครบถ้วนหรือไม่ถูกต้อง",
        )

    external_metadata = {
        "external_status": "external_unverified",
        "external_product_id": data.barcode,
        "source_code": "OPEN_FOOD_FACTS",
        "source_url": source_url,
        "fetched_at": source.get("fetched_at"),
        "license_or_attribution": source.get("license_or_attribution"),
        "package_quantity": item.get("package_quantity"),
    }

    try:
        # Lock the meal to serialize repeated submissions for this same meal.
        owned = db.execute(
            text("""
                SELECT meal_log_id
                FROM meal_logs
                WHERE meal_log_id = :meal_log_id
                  AND user_id = :user_id
                FOR UPDATE
            """),
            {"meal_log_id": meal_id, "user_id": user_id},
        ).mappings().first()
        if owned is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

        source_row = db.execute(
            text("""
                SELECT food_source_id
                FROM food_sources
                WHERE source_code = 'OPEN_FOOD_FACTS'
                  AND is_active = TRUE
                LIMIT 1
            """),
        ).mappings().first()
        if source_row is None:
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="แหล่งข้อมูล Open Food Facts ยังไม่พร้อมใช้งาน",
            )

        food = db.execute(
            text("""
                INSERT INTO food_items (
                    item_type,
                    name_th,
                    name_en,
                    brand_name,
                    source_id,
                    external_record_id,
                    external_metadata,
                    verification_status,
                    is_active,
                    source_last_checked_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    'packaged_product',
                    NULL,
                    :name_en,
                    :brand_name,
                    :source_id,
                    :external_record_id,
                    CAST(:external_metadata AS JSONB),
                    'unverified',
                    TRUE,
                    NOW(),
                    NOW(),
                    NOW()
                )
                ON CONFLICT (source_id, external_record_id)
                    WHERE source_id IS NOT NULL
                      AND external_record_id IS NOT NULL
                DO NOTHING
                RETURNING food_id, verification_status, external_metadata
            """),
            {
                "name_en": name.strip(),
                "brand_name": item.get("brand_name"),
                "source_id": str(source_row["food_source_id"]),
                "external_record_id": data.barcode,
                "external_metadata": json.dumps(external_metadata),
            },
        ).mappings().first()

        if food is None:
            food = db.execute(
                text("""
                    SELECT food_id, verification_status, external_metadata
                    FROM food_items
                    WHERE source_id = :source_id
                      AND external_record_id = :external_record_id
                    FOR UPDATE
                """),
                {
                    "source_id": str(source_row["food_source_id"]),
                    "external_record_id": data.barcode,
                },
            ).mappings().first()
        if food is None:
            db.rollback()
            raise HTTPException(
                status_code=503, detail="บันทึกข้อมูลสินค้าอ้างอิงไม่สำเร็จ"
            )

        stored_metadata = food["external_metadata"] or {}
        if (
            food["verification_status"] not in ("unverified", "needs_review")
            or stored_metadata.get("external_status") != "external_unverified"
            or stored_metadata.get("source_code") != "OPEN_FOOD_FACTS"
        ):
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="สินค้านี้มีข้อมูลในคลังที่ผ่านขั้นตอนตรวจสอบแล้ว กรุณาเลือกจากคลังภายใน",
            )

        existing = db.execute(
            text("""
                SELECT
                    meal_item_id, meal_log_id, food_id, food_name_snapshot,
                    quantity_value, quantity_unit, weight_g, volume_ml,
                    portion_id, entry_source, confirmation_status,
                    source_confidence, notes, created_at, updated_at
                FROM meal_items
                WHERE meal_log_id = :meal_log_id
                  AND food_id = :food_id
                  AND entry_source = 'barcode'
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"meal_log_id": meal_id, "food_id": str(food["food_id"])},
        ).mappings().first()
        if existing is not None:
            db.commit()
            response.status_code = 200
            return {
                "status": "success",
                "duplicate": True,
                "external_status": "external_unverified",
                "source": external_metadata,
                "item": dict(existing),
            }

        weight_g = data.quantity_value if data.quantity_unit == "g" else None
        volume_ml = data.quantity_value if data.quantity_unit == "ml" else None
        row = db.execute(
            text("""
                INSERT INTO meal_items (
                    meal_log_id,
                    food_id,
                    food_name_snapshot,
                    quantity_value,
                    quantity_unit,
                    weight_g,
                    volume_ml,
                    entry_source,
                    confirmation_status,
                    notes,
                    created_at,
                    updated_at
                )
                VALUES (
                    :meal_log_id,
                    :food_id,
                    :food_name_snapshot,
                    :quantity_value,
                    :quantity_unit,
                    :weight_g,
                    :volume_ml,
                    'barcode',
                    'needs_review',
                    :notes,
                    NOW(),
                    NOW()
                )
                RETURNING
                    meal_item_id, meal_log_id, food_id, food_name_snapshot,
                    preparation_state_snapshot, quantity_value, quantity_unit,
                    weight_g, volume_ml, portion_id, entry_source,
                    confirmation_status, source_confidence, notes,
                    created_at, updated_at
            """),
            {
                "meal_log_id": meal_id,
                "food_id": str(food["food_id"]),
                "food_name_snapshot": name.strip(),
                "quantity_value": data.quantity_value,
                "quantity_unit": data.quantity_unit,
                "weight_g": weight_g,
                "volume_ml": volume_ml,
                "notes": data.notes,
            },
        ).mappings().first()
        if row is None:
            db.rollback()
            raise HTTPException(status_code=500, detail="บันทึกรายการอาหารไม่สำเร็จ")
        db.commit()
        return {
            "status": "success",
            "duplicate": False,
            "external_status": "external_unverified",
            "source": external_metadata,
            "item": dict(row),
        }
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="บันทึกรายการอาหารไม่สำเร็จ กรุณาลองอีกครั้ง",
        ) from error


@router.post("/{meal_log_id}/items", status_code=201)
def create_meal_item(
    meal_log_id: UUID,
    data: MealItemCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    meal_id = str(meal_log_id)

    # Check ownership before accessing or modifying the meal.
    meal = db.execute(
        text("""
            SELECT meal_log_id
            FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if meal is None:
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    food_name = data.food_name
    food_id = str(data.food_id) if data.food_id else None
    preparation_state = data.preparation_state
    weight_g = data.weight_g
    volume_ml = data.volume_ml
    portion_id = str(data.portion_id) if data.portion_id else None

    if food_id:
        food = db.execute(
            text("""
                SELECT food_id, name_th, name_en, preparation_state
                FROM food_items
                WHERE food_id = :food_id
                  AND is_active = TRUE
            """),
            {"food_id": food_id},
        ).mappings().first()

        if food is None:
            raise HTTPException(status_code=404, detail="ไม่พบอาหารที่เปิดใช้งาน")

        food_name = food["name_th"] or food["name_en"]
        if not preparation_state:
            preparation_state = food["preparation_state"]

    if portion_id:
        portion = db.execute(
            text("""
                SELECT food_id, weight_g
                FROM food_portions
                WHERE portion_id = :portion_id
                  AND food_id = :food_id
                  AND weight_g > 0
                  AND verification_status IN ('reviewed', 'source_verified')
            """),
            {"portion_id": portion_id, "food_id": food_id},
        ).mappings().first()

        if portion is None:
            raise HTTPException(
                status_code=422,
                detail="portion ไม่ตรงกับอาหาร หรือยังไม่ได้รับการตรวจสอบ",
            )

        if weight_g is None:
            weight_g = Decimal(str(portion["weight_g"])) * data.quantity_value

    row = db.execute(
        text("""
            INSERT INTO meal_items (
                meal_log_id,
                food_id,
                food_name_snapshot,
                preparation_state_snapshot,
                quantity_value,
                quantity_unit,
                weight_g,
                volume_ml,
                portion_id,
                entry_source,
                confirmation_status,
                notes,
                created_at,
                updated_at
            )
            VALUES (
                :meal_log_id,
                :food_id,
                :food_name_snapshot,
                :preparation_state_snapshot,
                :quantity_value,
                :quantity_unit,
                :weight_g,
                :volume_ml,
                :portion_id,
                :entry_source,
                'needs_review',
                :notes,
                NOW(),
                NOW()
            )
            RETURNING
                meal_item_id,
                meal_log_id,
                food_id,
                food_name_snapshot,
                preparation_state_snapshot,
                quantity_value,
                quantity_unit,
                weight_g,
                volume_ml,
                portion_id,
                entry_source,
                confirmation_status,
                notes,
                created_at,
                updated_at
        """),
        {
            "meal_log_id": meal_id,
            "food_id": food_id,
            "food_name_snapshot": food_name,
            "preparation_state_snapshot": preparation_state,
            "quantity_value": data.quantity_value,
            "quantity_unit": data.quantity_unit,
            "weight_g": weight_g,
            "volume_ml": volume_ml,
            "portion_id": portion_id,
            "entry_source": data.entry_source,
            "notes": data.notes,
        },
    ).mappings().first()

    if row is None:
        db.rollback()
        raise HTTPException(status_code=500, detail="ไม่สามารถบันทึกรายการอาหารได้")

    db.commit()
    return {"status": "success", "item": dict(row)}


@router.get("/{meal_log_id}/items")
def list_meal_items(
    meal_log_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    meal_id = str(meal_log_id)

    # Verify ownership before reading any items.
    meal = db.execute(
        text("""
            SELECT meal_log_id
            FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if meal is None:
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    rows = db.execute(
        text("""
            SELECT
                mi.meal_item_id,
                mi.meal_log_id,
                mi.food_id,
                mi.food_name_snapshot,
                mi.preparation_state_snapshot,
                mi.quantity_value,
                mi.quantity_unit,
                mi.weight_g,
                mi.volume_ml,
                mi.portion_id,
                mi.entry_source,
                mi.confirmation_status,
                mi.source_confidence,
                mi.notes,
                mi.created_at,
                mi.updated_at,
                CASE
                    WHEN fi.external_metadata ->> 'external_status' = 'external_unverified'
                     AND fs.source_code = 'OPEN_FOOD_FACTS'
                    THEN 'external_unverified'
                    ELSE NULL
                END AS external_status,
                CASE
                    WHEN fs.source_code = 'OPEN_FOOD_FACTS'
                     AND fi.external_metadata ->> 'external_status' = 'external_unverified'
                    THEN fs.source_code
                    ELSE NULL
                END AS external_source_code,
                CASE
                    WHEN fs.source_code = 'OPEN_FOOD_FACTS'
                     AND fi.external_metadata ->> 'external_status' = 'external_unverified'
                    THEN fs.source_name
                    ELSE NULL
                END AS external_source_name,
                CASE
                    WHEN fs.source_code = 'OPEN_FOOD_FACTS'
                     AND fi.external_metadata ->> 'external_status' = 'external_unverified'
                    THEN fi.external_metadata ->> 'source_url'
                    ELSE NULL
                END AS external_source_url
            FROM meal_items mi
            LEFT JOIN food_items fi ON fi.food_id = mi.food_id
            LEFT JOIN food_sources fs ON fs.food_source_id = fi.source_id
            WHERE mi.meal_log_id = :meal_log_id
            ORDER BY mi.created_at ASC, mi.meal_item_id ASC
        """),
        {"meal_log_id": meal_id},
    ).mappings().all()

    return {
        "status": "success",
        "meal_log_id": meal_id,
        "count": len(rows),
        "items": [dict(row) for row in rows],
    }


class MealItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    food_name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    preparation_state: Optional[str] = Field(default=None, max_length=200)
    quantity_value: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=12, decimal_places=3
    )
    quantity_unit: Optional[QuantityUnit] = None
    weight_g: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=12, decimal_places=3
    )
    volume_ml: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=12, decimal_places=3
    )
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("food_name", "preparation_state", "notes")
    @classmethod
    def strip_update_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("กรุณาระบุข้อมูลที่ต้องการแก้ไข")
        if "food_name" in self.model_fields_set and not self.food_name:
            raise ValueError("food_name ต้องไม่เป็นค่าว่าง")
        return self


@router.patch("/{meal_log_id}/items/{meal_item_id}")
def update_meal_item(
    meal_log_id: UUID,
    meal_item_id: UUID,
    data: MealItemUpdate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    meal_id = str(meal_log_id)
    item_id = str(meal_item_id)

    meal = db.execute(
        text("""
            SELECT meal_log_id
            FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if meal is None:
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    item = db.execute(
        text("""
            SELECT meal_item_id, quantity_unit, portion_id
            FROM meal_items
            WHERE meal_item_id = :meal_item_id
              AND meal_log_id = :meal_log_id
        """),
        {"meal_item_id": item_id, "meal_log_id": meal_id},
    ).mappings().first()

    if item is None:
        raise HTTPException(status_code=404, detail="ไม่พบรายการอาหารในมื้อนี้")

    changes = data.model_dump(exclude_unset=True)
    if "quantity_unit" in changes and changes["quantity_unit"] == "portion":
        if item["portion_id"] is None:
            raise HTTPException(
                status_code=422,
                detail="หน่วย portion ต้องมี portion_id ที่ตรวจสอบแล้ว",
            )

    # Only update explicitly supplied, allowlisted fields.
    column_map = {
        "food_name": "food_name_snapshot",
        "preparation_state": "preparation_state_snapshot",
        "quantity_value": "quantity_value",
        "quantity_unit": "quantity_unit",
        "weight_g": "weight_g",
        "volume_ml": "volume_ml",
        "notes": "notes",
    }
    assignments = []
    params = {"meal_item_id": item_id, "meal_log_id": meal_id}

    for field, value in changes.items():
        column = column_map[field]
        assignments.append(f"{column} = :{field}")
        params[field] = value

    if not assignments:
        raise HTTPException(status_code=422, detail="ไม่มีข้อมูลให้แก้ไข")

    assignments.append("updated_at = NOW()")

    sql = f"""
        UPDATE meal_items
        SET {", ".join(assignments)}
        WHERE meal_item_id = :meal_item_id
          AND meal_log_id = :meal_log_id
        RETURNING
            meal_item_id,
            meal_log_id,
            food_id,
            food_name_snapshot,
            preparation_state_snapshot,
            quantity_value,
            quantity_unit,
            weight_g,
            volume_ml,
            portion_id,
            entry_source,
            confirmation_status,
            source_confidence,
            notes,
            created_at,
            updated_at
    """

    row = db.execute(text(sql), params).mappings().first()
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="ไม่พบรายการอาหารในมื้อนี้")

    db.commit()
    return {"status": "success", "item": dict(row)}


@router.delete("/{meal_log_id}/items/{meal_item_id}", status_code=204)
def delete_meal_item(
    meal_log_id: UUID,
    meal_item_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = str(user["user_id"])
    meal_id = str(meal_log_id)
    item_id = str(meal_item_id)

    meal = db.execute(
        text("""
            SELECT meal_log_id
            FROM meal_logs
            WHERE meal_log_id = :meal_log_id
              AND user_id = :user_id
        """),
        {"meal_log_id": meal_id, "user_id": user_id},
    ).mappings().first()

    if meal is None:
        raise HTTPException(status_code=404, detail="ไม่พบมื้ออาหาร")

    result = db.execute(
        text("""
            DELETE FROM meal_items
            WHERE meal_item_id = :meal_item_id
              AND meal_log_id = :meal_log_id
            RETURNING meal_item_id
        """),
        {"meal_item_id": item_id, "meal_log_id": meal_id},
    ).mappings().first()

    if result is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="ไม่พบรายการอาหารในมื้อนี้")

    db.commit()
    return None
