
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


router = APIRouter(
    prefix="/nutrition",
    tags=["Nutrition"]
)


class NutritionRequest(BaseModel):
    nutrient_per_100g: Optional[float] = Field(
        default=None,
        ge=0
    )
    eaten_weight_g: Optional[float] = Field(
        default=None,
        gt=0
    )
    nutrient_code: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)


class FoodNutritionRequest(BaseModel):
    food_id: UUID
    eaten_weight_g: float = Field(gt=0)


@router.post("/calculate")
def calculate_nutrition(
    data: NutritionRequest,
    db: Session = Depends(get_db)
):
    # อ่านกฎ NUT-001 จาก PostgreSQL
    result = db.execute(
        text("""
            SELECT
                rule_code,
                rule_name,
                lifecycle_status,
                decision_logic
            FROM rule_definitions
            WHERE rule_code = :rule_code
            ORDER BY version DESC
            LIMIT 1
        """),
        {"rule_code": "NUT-001"}
    ).mappings().first()

    # ไม่พบกฎในฐานข้อมูล
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบกฎ NUT-001 ในฐานข้อมูล"
        )

    # อนุญาตให้ใช้เฉพาะกฎที่เปิดใช้งานแล้ว
    if result["lifecycle_status"] != "active":
        return {
            "status": "rule_not_active",
            "rule_code": result["rule_code"],
            "rule_name": result["rule_name"],
            "lifecycle_status": result["lifecycle_status"],
            "decision_logic": result["decision_logic"],
            "message": "กฎนี้ยังไม่ได้เปิดใช้งาน จึงยังไม่คำนวณ"
        }

    # ตรวจสอบข้อมูลที่จำเป็น
    if data.nutrient_per_100g is None:
        return {
            "status": "needs_input",
            "message": "กรุณาระบุปริมาณสารอาหารต่อ 100 กรัม"
        }

    if data.eaten_weight_g is None:
        return {
            "status": "needs_input",
            "message": "กรุณาระบุน้ำหนักอาหารที่รับประทาน"
        }

    # ปรับหน่วยให้อยู่ในรูปแบบมาตรฐานก่อนตรวจสอบและส่งกลับ
    normalized_unit = data.unit.strip().lower()

    if normalized_unit not in {"g", "mg", "kcal"}:
        return {
            "status": "invalid_input",
            "message": "หน่วยสารอาหารต้องเป็น g, mg หรือ kcal"
        }

    # ตรวจรหัสสารอาหารและหน่วยมาตรฐานจากฐานข้อมูล
    nutrient = db.execute(
        text("""
            SELECT nutrient_code, canonical_unit
            FROM nutrient_definitions
            WHERE nutrient_code = :nutrient_code
              AND is_active = TRUE
            LIMIT 1
        """),
        {"nutrient_code": data.nutrient_code.strip()}
    ).mappings().first()

    if nutrient is None:
        return {
            "status": "invalid_input",
            "message": "ไม่พบรหัสสารอาหารหรือสารอาหารไม่ได้เปิดใช้งาน"
        }

    canonical_unit = nutrient["canonical_unit"].strip().lower()

    if normalized_unit != canonical_unit:
        return {
            "status": "invalid_input",
            "message": "หน่วยไม่ตรงกับหน่วยมาตรฐานของสารอาหาร",
            "expected_unit": canonical_unit,
            "received_unit": normalized_unit
        }

    # คำนวณตามสูตรของ NUT-001
    consumed = (
        data.nutrient_per_100g
        * data.eaten_weight_g
        / 100
    )

    return {
        "status": "calculated",
        "nutrient_per_100g": data.nutrient_per_100g,
        "eaten_weight_g": data.eaten_weight_g,
        "consumed": round(consumed, 6),
        "unit": normalized_unit,
        "source": data.source,
        "rule_code": result["rule_code"],
        "rule_name": result["rule_name"],
        "lifecycle_status": result["lifecycle_status"]
    }



@router.post("/calculate-from-food")
def calculate_from_food(
    data: FoodNutritionRequest,
    db: Session = Depends(get_db)
):
    # 1. ตรวจสอบว่าอาหารมีอยู่และเปิดใช้งาน
    food = db.execute(
        text("""
            SELECT
                food_id,
                name_th,
                name_en,
                brand_name,
                verification_status
            FROM food_items
            WHERE food_id = :food_id
                AND is_active = TRUE
        """),
        {"food_id": str(data.food_id)}
    ).mappings().first()

    if food is None:
        return {
            "status": "food_not_found",
            "message": "ไม่พบอาหารนี้ หรืออาหารไม่ได้เปิดใช้งาน"
        }

    # 2. ค้นหาฐานโภชนาการต่อ 100 กรัม
    # ไม่เลือกฐานใดฐานหนึ่งโดยอัตโนมัติ หากพบหลายฐาน
    bases = db.execute(
        text("""
            SELECT
                nutrition_basis_id,
                basis_type,
                basis_quantity,
                basis_unit,
                verification_status
            FROM food_nutrition_bases
            WHERE food_id = :food_id
                AND basis_type = 'per_100g'
                AND basis_quantity = 100
                AND LOWER(basis_unit) = 'g'
            ORDER BY created_at DESC
        """),
        {"food_id": str(data.food_id)}
    ).mappings().all()

    if not bases:
        return {
            "status": "nutrition_basis_not_found",
            "message": "ไม่พบฐานโภชนาการต่อ 100 กรัม"
        }

    if len(bases) > 1:
        return {
            "status": "nutrition_basis_ambiguous",
            "message": (
                "พบฐานโภชนาการต่อ 100 กรัมหลายรายการ "
                "ต้องตรวจสอบและเลือกฐานที่ถูกต้องก่อน"
            ),
            "basis_count": len(bases)
        }

    basis = bases[0]

    # 3. ตรวจสอบกฎ NUT-001
    rule = db.execute(
        text("""
            SELECT
                rule_code,
                rule_name,
                lifecycle_status,
                decision_logic
            FROM rule_definitions
            WHERE rule_code = 'NUT-001'
            ORDER BY version DESC
            LIMIT 1
        """)
    ).mappings().first()

    if rule is None:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบกฎ NUT-001 ในฐานข้อมูล"
        )

    # ไม่คำนวณจริงหากกฎยังไม่ได้เปิดใช้งาน
    if rule["lifecycle_status"] != "active":
        return {
            "status": "rule_not_active",
            "rule_code": rule["rule_code"],
            "rule_name": rule["rule_name"],
            "lifecycle_status": rule["lifecycle_status"],
            "decision_logic": rule["decision_logic"],
            "food": {
                "food_id": str(food["food_id"]),
                "name_th": food["name_th"],
                "name_en": food["name_en"],
                "brand_name": food["brand_name"],
                "verification_status": food["verification_status"]
            },
            "nutrition_basis": {
                "basis_type": basis["basis_type"],
                "basis_quantity": float(basis["basis_quantity"]),
                "basis_unit": basis["basis_unit"],
                "verification_status": basis["verification_status"]
            },
            "message": "กฎยังไม่ได้เปิดใช้งาน จึงยังไม่คำนวณ"
        }

    # 4. ตรวจสอบสถานะข้อมูลก่อนคำนวณ
    trusted_statuses = ("reviewed", "source_verified")

    if (
        food["verification_status"] not in trusted_statuses
        or basis["verification_status"] not in trusted_statuses
    ):
        return {
            "status": "data_needs_review",
            "food": {
                "food_id": str(food["food_id"]),
                "name_th": food["name_th"],
                "name_en": food["name_en"],
                "brand_name": food["brand_name"],
                "verification_status": food["verification_status"]
            },
            "nutrition_basis": {
                "basis_type": basis["basis_type"],
                "basis_quantity": float(basis["basis_quantity"]),
                "basis_unit": basis["basis_unit"],
                "verification_status": basis["verification_status"]
            },
            "message": "ข้อมูลอาหารหรือฐานโภชนาการยังต้องตรวจสอบ"
        }

    # 5. อ่านเฉพาะสารอาหารที่มีอยู่จริง
    nutrients = db.execute(
        text("""
            SELECT
                d.nutrient_code,
                d.name_th,
                d.name_en,
                d.canonical_unit,
                d.display_decimals,
                n.amount,
                n.source_note
            FROM food_nutrients n
            JOIN nutrient_definitions d
                ON d.nutrient_code = n.nutrient_code
            WHERE n.nutrition_basis_id = :basis_id
              AND d.is_active = TRUE
            ORDER BY d.nutrient_code
        """),
        {"basis_id": basis["nutrition_basis_id"]}
    ).mappings().all()

    if not nutrients:
        return {
            "status": "nutrients_not_found",
            "message": "ไม่พบข้อมูลสารอาหารสำหรับฐานโภชนาการนี้"
        }

    # 6. คำนวณตาม NUT-001
    results = []

    for nutrient in nutrients:
        consumed = (
            float(nutrient["amount"])
            * data.eaten_weight_g
            / 100
        )

        decimals = nutrient["display_decimals"]

        results.append({
            "nutrient_code": nutrient["nutrient_code"],
            "name_th": nutrient["name_th"],
            "name_en": nutrient["name_en"],
            "amount_per_100g": float(nutrient["amount"]),
            "consumed": round(consumed, decimals),
            "unit": nutrient["canonical_unit"],
            "source_note": nutrient["source_note"]
        })

    return {
        "status": "calculated",
        "food": {
            "food_id": str(food["food_id"]),
            "name_th": food["name_th"],
            "name_en": food["name_en"],
            "brand_name": food["brand_name"],
            "verification_status": food["verification_status"]
        },
        "eaten_weight_g": data.eaten_weight_g,
        "nutrition_basis": {
            "basis_type": basis["basis_type"],
            "basis_quantity": float(basis["basis_quantity"]),
            "basis_unit": basis["basis_unit"],
            "verification_status": basis["verification_status"]
        },
        "rule": {
            "rule_code": rule["rule_code"],
            "rule_name": rule["rule_name"],
            "lifecycle_status": rule["lifecycle_status"]
        },
        "nutrients": results,
        "message": "คำนวณสำเร็จ"
    }

