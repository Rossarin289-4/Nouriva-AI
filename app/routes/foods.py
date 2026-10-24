import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.food_photo_analysis import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    FoodImageAnalysisUnavailable,
    analyze_food_image,
)
from app.services.openfoodfacts import (
    OpenFoodFactsUnavailable,
    lookup_barcode as lookup_openfoodfacts_barcode,
)


router = APIRouter(
    prefix="/foods",
    tags=["Foods"]
)

@router.get("")
def search_foods(
    search: Optional[str] = Query(default=None, min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    sql = """
        SELECT
            food_id,
            item_type,
            name_th,
            name_en,
            brand_name,
            preparation_state,
            verification_status
        FROM food_items
        WHERE is_active = TRUE
            AND (
                CAST(:search AS TEXT) IS NULL
                OR name_th ILIKE '%' || :search || '%'
                OR name_en ILIKE '%' || :search || '%'
                OR brand_name ILIKE '%' || :search || '%'
            )
        ORDER BY name_th NULLS LAST, name_en NULLS LAST
        LIMIT :limit
    """

    rows = db.execute(
        text(sql),
        {
            "search": search,
            "limit": limit
        }
    ).mappings().all()

    return {
        "count": len(rows),
        "items": [dict(row) for row in rows]
    }


@router.get("/barcode/{barcode}")
def get_food_by_barcode(
    barcode: str,
    db: Session = Depends(get_db)
):
    code = barcode.strip()
    if not re.fullmatch(r"[0-9]{8,14}", code):
        raise HTTPException(
            status_code=422,
            detail="รหัส Barcode ต้องเป็นตัวเลข 8-14 หลัก"
        )

    row = db.execute(
        text("""
            SELECT
                fb.barcode,
                fb.barcode_type,
                fi.food_id,
                fi.item_type,
                fi.name_th,
                fi.name_en,
                fi.brand_name,
                fi.preparation_state,
                fi.verification_status
            FROM food_barcodes fb
            JOIN food_items fi
                ON fi.food_id = fb.food_id
            WHERE fb.barcode = :barcode
              AND fi.is_active = TRUE
            LIMIT 1
        """),
        {"barcode": code}
    ).mappings().first()

    if row is None:
        try:
            db.execute(
                text("""
                    INSERT INTO unrecognized_barcodes (
                        barcode,
                        first_seen_at,
                        last_seen_at,
                        scan_count,
                        status
                    )
                    VALUES (
                        :barcode,
                        NOW(),
                        NOW(),
                        1,
                        'pending'
                    )
                    ON CONFLICT (barcode)
                    DO UPDATE SET
                        last_seen_at = NOW(),
                        scan_count =
                            unrecognized_barcodes.scan_count + 1
                    WHERE unrecognized_barcodes.status = 'pending'
                """),
                {"barcode": code}
            )
            db.commit()
        except Exception:
            db.rollback()
            # การบันทึกไม่สำเร็จต้องไม่ทำให้ข้อความค้นหา
            # Barcode ที่ไม่พบเปลี่ยนเป็นข้อผิดพลาดภายใน
            pass

        raise HTTPException(
            status_code=404,
            detail="ยังไม่มีข้อมูลสินค้านี้ในคลังอาหาร ลองค้นหาชื่ออาหารหรือกรอกรหัสอื่น"
        )

    return {
        "status": "success",
        "item": dict(row)
    }


@router.get("/external/openfoodfacts/barcode/{barcode}")
def get_external_food_by_barcode(barcode: str):
    """Look up a product externally without importing it into the local DB."""
    code = barcode.strip()
    if not re.fullmatch(r"[0-9]{8,14}", code):
        raise HTTPException(
            status_code=422,
            detail="รหัส Barcode ต้องเป็นตัวเลข 8-14 หลัก",
        )

    try:
        result = lookup_openfoodfacts_barcode(code)
    except OpenFoodFactsUnavailable as error:
        raise HTTPException(
            status_code=error.status_code, detail=str(error)
        ) from error

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบรหัสนี้ใน Open Food Facts",
        )
    return result


@router.post("/image-analysis")
async def analyze_food_photo(
    request: Request,
    user=Depends(get_current_user),
):
    """Analyze an explicitly consented image in memory; do not persist the photo."""
    if request.headers.get("x-food-image-consent", "").lower() != "true":
        raise HTTPException(
            status_code=400,
            detail="กรุณายืนยันการส่งภาพไปยังผู้ให้บริการวิเคราะห์ก่อน",
        )

    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="รองรับไฟล์ภาพ JPEG, PNG และ WebP เท่านั้น",
        )
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="ภาพใหญ่เกินไป (สูงสุด 10 MB)")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="ขนาดคำขอไม่ถูกต้อง") from error

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="ภาพใหญ่เกินไป (สูงสุด 10 MB)")
        chunks.append(chunk)

    try:
        return analyze_food_image(b"".join(chunks), content_type)
    except FoodImageAnalysisUnavailable as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

@router.get("/{food_id}")
def get_food(
    food_id: UUID,
    db: Session = Depends(get_db)
):
    row = db.execute(
        text("""
            SELECT
                food_id,
                item_type,
                name_th,
                name_en,
                brand_name,
                preparation_state,
                verification_status,
                is_active,
                source_id,
                created_at,
                updated_at
            FROM food_items
            WHERE food_id = :food_id
        """),
        {"food_id": food_id}
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบอาหารที่ระบุ"
        )

    return {
        "status": "success",
        "item": dict(row)
    }


@router.get("/{food_id}/portions")
def get_food_portions(
    food_id: UUID,
    db: Session = Depends(get_db)
):
    food = db.execute(
        text("""
            SELECT food_id
            FROM food_items
            WHERE food_id = :food_id
              AND is_active = TRUE
        """),
        {"food_id": str(food_id)}
    ).mappings().first()

    if food is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบอาหารนี้ หรืออาหารไม่ได้เปิดใช้งาน"
        )

    rows = db.execute(
        text("""
            SELECT
                portion_id,
                portion_name_th,
                portion_name_en,
                unit_name,
                weight_g,
                source_note,
                verification_status
            FROM food_portions
            WHERE food_id = :food_id
              AND weight_g > 0
              AND verification_status IN (
                  'reviewed',
                  'source_verified'
              )
            ORDER BY portion_name_th
        """),
        {"food_id": str(food_id)}
    ).mappings().all()

    return {
        "status": "success",
        "food_id": str(food_id),
        "count": len(rows),
        "items": [dict(row) for row in rows]
    }

@router.get("/{food_id}/nutrition")
def get_food_nutrition(
    food_id: UUID,
    db: Session = Depends(get_db)
):
    food = db.execute(
        text("""
            SELECT
                food_id,
                name_th,
                name_en,
                verification_status
            FROM food_items
            WHERE food_id = :food_id
        """),
        {"food_id": food_id}
    ).mappings().first()

    if food is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบอาหารที่ระบุ"
        )

    rows = db.execute(
        text("""
            SELECT
                b.nutrition_basis_id,
                b.basis_type,
                b.basis_quantity,
                b.basis_unit,
                b.serving_label,
                b.serving_size_g,
                b.source_kind,
                b.source_record_id,
                b.notes AS basis_notes,
                b.verification_status,
                fs.source_code,
                fs.source_name,
                fs.source_url,
                fs.license_or_attribution,
                fs.is_active AS source_is_active,
                n.nutrient_code,
                d.name_th AS nutrient_name_th,
                d.name_en AS nutrient_name_en,
                n.amount,
                d.canonical_unit AS nutrient_unit,
                n.source_note
            FROM food_nutrition_bases b
            JOIN food_nutrients n
                ON n.nutrition_basis_id = b.nutrition_basis_id
            JOIN nutrient_definitions d
                ON d.nutrient_code = n.nutrient_code
            LEFT JOIN food_sources fs
                ON fs.food_source_id = b.source_id
            WHERE b.food_id = :food_id
            ORDER BY b.basis_type, d.name_th
        """),
        {"food_id": food_id}
    ).mappings().all()

    source = None
    if rows:
        first = rows[0]
        source = {
            "source_code": first["source_code"],
            "source_name": first["source_name"],
            "source_url": first["source_url"],
            "license_or_attribution": first["license_or_attribution"],
            "source_is_active": first["source_is_active"],
            "source_kind": first["source_kind"],
            "source_record_id": first["source_record_id"],
            "verification_status": first["verification_status"],
            "notes": first["basis_notes"],
        }

    nutrition = []
    for row in rows:
        item = dict(row)
        for key in (
            "source_code",
            "source_name",
            "source_url",
            "license_or_attribution",
            "source_is_active",
            "source_record_id",
            "basis_notes",
        ):
            item.pop(key, None)
        nutrition.append(item)

    return {
        "status": "success",
        "food": dict(food),
        "count": len(nutrition),
        "source": source,
        "nutrition": nutrition,
    }
