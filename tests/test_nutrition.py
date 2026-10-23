
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


class FakeResult:
    """จำลองผลลัพธ์จากการ query ฐานข้อมูล"""

    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        if isinstance(self.row, list):
            return self.row[0] if self.row else None
        return self.row

    def all(self):
        if self.row is None:
            return []
        if isinstance(self.row, list):
            return self.row
        return [self.row]


class FakeDB:
    """จำลองฐานข้อมูลโดยไม่เชื่อมต่อ PostgreSQL จริง"""

    def __init__(self, results):
        self.results = iter(results)
        self.execute_count = 0

    def execute(self, query, params=None):
        self.execute_count += 1
        return next(self.results)

    def close(self):
        pass


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: FakeDB(
        [FakeResult(None)]
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_invalid_food_id_returns_422(client):
    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": "not-a-uuid",
            "eaten_weight_g": 15,
        },
    )

    assert response.status_code == 422


def test_food_not_found(client):
    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": "00000000-0000-0000-0000-000000000000",
            "eaten_weight_g": 15,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "food_not_found"


def test_rule_not_active_does_not_calculate(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": None,
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "needs_review",
        }),
        FakeResult({
            "nutrition_basis_id": (
                "ac9f5b2c-7256-43fa-88df-87f72f342976"
            ),
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "source_kind": "database",
            "verification_status": "needs_review",
        }),
        
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "draft",
            "decision_logic": (
            "consumed = nutrient_per_100g "
            "* eaten_weight_g / 100"
            ),
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "rule_not_active"
    assert data["lifecycle_status"] == "draft"
    assert fake_db.execute_count == 3


def test_nutrition_basis_not_found(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": None,
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "needs_review",
        }),
        FakeResult(None),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "nutrition_basis_not_found"


def test_nutrition_basis_ambiguous(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": None,
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "needs_review",
        }),
        FakeResult([
            {
                "nutrition_basis_id": "basis-test-1",
                "basis_type": "per_100g",
                "basis_quantity": 100,
                "basis_unit": "g",
                "verification_status": "needs_review",
            },
            {
                "nutrition_basis_id": "basis-test-2",
                "basis_type": "per_100g",
                "basis_quantity": 100,
                "basis_unit": "g",
                "verification_status": "needs_review",
            },
        ]),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "nutrition_basis_ambiguous"
    assert data["basis_count"] == 2


def test_data_needs_review_does_not_calculate(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": None,
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "needs_review",
        }),
        FakeResult({
            "nutrition_basis_id": (
                "ac9f5b2c-7256-43fa-88df-87f72f342976"
            ),
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "source_kind": "database",
            "verification_status": "needs_review",
        }),
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "data_needs_review"
    assert fake_db.execute_count == 3


@pytest.mark.parametrize("weight", [0, -1, -15])
def test_invalid_eaten_weight_returns_422(client, weight):
    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": "8d78d477-67c6-4272-92a6-5495e114402e",
            "eaten_weight_g": weight,
        },
    )

    assert response.status_code == 422


def test_calculate_nutrition_formula(client):
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult({
            "nutrient_code": "protein_g",
            "canonical_unit": "g",
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 57.5,
            "eaten_weight_g": 15,
            "nutrient_code": "protein_g",
            "unit": "g",
            "source": "test",
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "calculated"
    assert data["consumed"] == 8.625
    assert data["unit"] == "g"
    assert data["rule_code"] == "NUT-001"
    assert data["lifecycle_status"] == "active"
    assert fake_db.execute_count == 2


def test_calculate_nutrition_rejects_draft_rule(client):
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "draft",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        })
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 57.5,
            "eaten_weight_g": 15,
            "nutrient_code": "protein_g",
            "unit": "g",
            "source": "test",
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "rule_not_active"
    assert data["lifecycle_status"] == "draft"
    assert "consumed" not in data
    assert fake_db.execute_count == 1


def test_calculate_from_food_success():
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"
    basis_id = "ac9f5b2c-7256-43fa-88df-87f72f342976"

    fake_db = FakeDB([
        # 1. ค้นหาอาหาร
        FakeResult({
            "food_id": food_id,
            "name_th": "นูเทลล่า",
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "reviewed",
        }),

        # 2. ค้นหาฐานโภชนาการ
        FakeResult([{
            "nutrition_basis_id": basis_id,
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "verification_status": "reviewed",
            "source_id": "source-test-id",
        }]),

        # 3. ตรวจสอบกฎ NUT-001
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),

        # 4. แหล่งข้อมูลเปิดใช้งาน
        FakeResult({"food_source_id": "source-test-id"}),

        # 5. ข้อมูลสารอาหาร
        FakeResult([
            {
                "nutrient_code": "carbohydrate_g",
                "name_th": "คาร์โบไฮเดรต",
                "name_en": "Carbohydrate",
                "canonical_unit": "g",
                "display_decimals": 1,
                "amount": 57.6,
                "source_note": "carbohydrates_100g",
            },
            {
                "nutrient_code": "energy_kcal",
                "name_th": "พลังงาน",
                "name_en": "Energy",
                "canonical_unit": "kcal",
                "display_decimals": 0,
                "amount": 539,
                "source_note": "energy-kcal_100g",
            },
        ]),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/nutrition/calculate-from-food",
                json={
                    "food_id": food_id,
                    "eaten_weight_g": 15,
                },
            )

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "calculated"
        assert data["message"] == "คำนวณสำเร็จ"
        assert data["eaten_weight_g"] == 15

        assert data["food"]["food_id"] == food_id
        assert data["food"]["verification_status"] == "reviewed"

        assert data["nutrition_basis"]["basis_type"] == "per_100g"
        assert data["rule"]["rule_code"] == "NUT-001"
        assert data["rule"]["lifecycle_status"] == "active"

        nutrients = {
            item["nutrient_code"]: item
            for item in data["nutrients"]
        }

        # คาร์โบไฮเดรต: 57.6 × 15 ÷ 100 = 8.64 → 8.6 g
        assert nutrients["carbohydrate_g"]["consumed"] == 8.6
        assert nutrients["carbohydrate_g"]["unit"] == "g"
        assert nutrients["carbohydrate_g"]["amount_per_100g"] == 57.6

        # พลังงาน: 539 × 15 ÷ 100 = 80.85 → 81 kcal
        assert nutrients["energy_kcal"]["consumed"] == 81
        assert nutrients["energy_kcal"]["unit"] == "kcal"

        assert fake_db.execute_count == 5

    finally:
        app.dependency_overrides.clear()



@pytest.mark.parametrize(
    "source_id,source_result,expected_count",
    [
        (None, None, 3),
        ("source-test-id", None, 4),
    ],
)
def test_calculate_from_food_requires_active_source(
    source_id, source_result, expected_count
):
    """ห้ามคำนวณเมื่อไม่มี source_id หรือไม่มีแหล่งข้อมูลที่ active."""
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_results = [
        FakeResult({
            "food_id": food_id,
            "name_th": "นูเทลล่า",
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "reviewed",
        }),
        FakeResult([{
            "nutrition_basis_id": "basis-source-test",
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "verification_status": "reviewed",
            "source_id": source_id,
        }]),
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
    ]

    if source_id is not None:
        fake_results.append(FakeResult(source_result))

    fake_db = FakeDB(fake_results)
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/nutrition/calculate-from-food",
                json={
                    "food_id": food_id,
                    "eaten_weight_g": 15,
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "source_not_verified"
        assert "nutrients" not in response.json()
        assert fake_db.execute_count == expected_count
    finally:
        app.dependency_overrides.clear()

def test_calculate_from_food_without_nutrients():
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"
    basis_id = "ac9f5b2c-7256-43fa-88df-87f72f342976"

    fake_db = FakeDB([
        # 1. พบอาหารและข้อมูลผ่านการตรวจสอบ
        FakeResult({
            "food_id": food_id,
            "name_th": "นูเทลล่า",
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "reviewed",
        }),

        # 2. พบฐานโภชนาการต่อ 100 กรัม
        FakeResult([{
            "nutrition_basis_id": basis_id,
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "verification_status": "reviewed",
            "source_id": "source-test-id",
        }]),

        # 3. กฎได้รับอนุมัติ
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),

        # 4. แหล่งข้อมูลเปิดใช้งาน
        FakeResult({"food_source_id": "source-test-id"}),

        # 5. ไม่มีรายการสารอาหาร
        FakeResult([]),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/nutrition/calculate-from-food",
                json={
                    "food_id": food_id,
                    "eaten_weight_g": 15,
                },
            )

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "nutrients_not_found"
        assert "nutrients" not in data
        assert fake_db.execute_count == 5

    finally:
        app.dependency_overrides.clear()

@pytest.mark.parametrize(
    ("nutrient_per_100g", "eaten_weight_g", "expected", "unit"),
    [
        (57.5, 15, 8.625, "g"),
        (539, 15, 80.85, "kcal"),
    ],
)
def test_nutrition_formula_with_different_values(
    client,
    nutrient_per_100g,
    eaten_weight_g,
    expected,
    unit,
):
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult({
            "nutrient_code": (
                "protein_g" if unit == "g" else "energy_kcal"
            ),
            "canonical_unit": unit,
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": nutrient_per_100g,
            "eaten_weight_g": eaten_weight_g,
            "nutrient_code": "energy_kcal" if unit == "kcal" else "protein_g",
            "unit": unit,
            "source": "test",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "calculated"
    assert response.json()["consumed"] == expected



def test_TC_027_nutrition_formula_kcal(client):
    """250 kcal/100g × 60g ต้องได้ 150 kcal."""
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult({
            "nutrient_code": "energy_kcal",
            "canonical_unit": "kcal",
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 250,
            "eaten_weight_g": 60,
            "nutrient_code": "energy_kcal",
            "unit": "kcal",
            "source": "TC-027 test data",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "calculated"
    assert data["consumed"] == 150
    assert data["unit"] == "kcal"


def test_TC_028_missing_confirmed_weight(client):
    """น้ำหนัก null ต้องขอข้อมูลเพิ่ม และห้ามคืนผลคำนวณ."""
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        })
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 250,
            "eaten_weight_g": None,
            "nutrient_code": "energy_kcal",
            "unit": "kcal",
            "source": "TC-028 test data",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "needs_input"
    assert "consumed" not in data


@pytest.mark.parametrize("unit", ["lb", "ml", "joule", " "])
def test_calculate_nutrition_rejects_unsupported_unit(client, unit):
    app.dependency_overrides[get_db] = lambda: FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        })
    ])

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 25,
            "eaten_weight_g": 20,
            "nutrient_code": "energy_kcal" if unit == "kcal" else "protein_g",
            "unit": unit,
            "source": "unit validation test",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "invalid_input"
    assert "consumed" not in response.json()


def test_calculate_nutrition_normalizes_unit(client):
    app.dependency_overrides[get_db] = lambda: FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult({
            "nutrient_code": "protein_g",
            "canonical_unit": "g",
        }),
    ])

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 25,
            "eaten_weight_g": 20,
            "nutrient_code": "protein_g",
            "unit": " G ",
            "source": "unit normalization test",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "calculated"
    assert response.json()["consumed"] == 5
    assert response.json()["unit"] == "g"


def test_food_nutrition_returns_source_and_nutrients(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    food = {
        "food_id": food_id,
        "name_th": None,
        "name_en": "Nutella",
        "verification_status": "needs_review",
    }

    common = {
        "nutrition_basis_id": "ac9f5b2c-7256-43fa-88df-87f72f342976",
        "basis_type": "per_100g",
        "basis_quantity": 100.0,
        "basis_unit": "g",
        "serving_label": None,
        "serving_size_g": None,
        "source_kind": "database",
        "source_record_id": "3017624010701",
        "basis_notes": "ต้องตรวจสอบกับฉลากก่อนอนุมัติ",
        "verification_status": "needs_review",
        "source_code": "OPEN_FOOD_FACTS",
        "source_name": "Open Food Facts",
        "source_url": (
            "https://openfoodfacts.github.io/documentation/"
            "docs/Product-Opener/v3/products/get-api-v3-product-code/"
        ),
        "license_or_attribution": "ตรวจสอบข้อกำหนดการใช้งานข้อมูล",
        "source_is_active": True,
    }

    rows = [
        {
            **common,
            "nutrient_code": "sugar_g",
            "nutrient_name_th": "น้ำตาล",
            "nutrient_name_en": "Sugars",
            "amount": 56.3,
            "nutrient_unit": "g",
            "source_note": "Open Food Facts: sugars_100g; g",
        },
        {
            **common,
            "nutrient_code": "energy_kcal",
            "nutrient_name_th": "พลังงาน",
            "nutrient_name_en": "Energy",
            "amount": 539.0,
            "nutrient_unit": "kcal",
            "source_note": "Open Food Facts: energy-kcal_100g; kcal",
        },
    ]

    app.dependency_overrides[get_db] = lambda: FakeDB([
        FakeResult(food),
        FakeResult(rows),
    ])

    response = client.get(f"/foods/{food_id}/nutrition")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["food"]["name_en"] == "Nutella"
    assert data["count"] == 2

    assert data["source"]["source_code"] == "OPEN_FOOD_FACTS"
    assert data["source"]["source_name"] == "Open Food Facts"
    assert data["source"]["source_url"].startswith("https://")
    assert data["source"]["source_record_id"] == "3017624010701"
    assert data["source"]["verification_status"] == "needs_review"
    assert data["food"]["verification_status"] == "needs_review"

    assert data["nutrition"][0]["nutrient_code"] == "sugar_g"
    assert data["nutrition"][0]["amount"] == 56.3
    assert data["nutrition"][1]["nutrient_unit"] == "kcal"

    for item in data["nutrition"]:
        assert "source_url" not in item
        assert "source_name" not in item
        assert "source_record_id" not in item


def test_food_nutrition_returns_404_when_food_not_found(client):
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    app.dependency_overrides[get_db] = lambda: FakeDB([
        FakeResult(None),
    ])

    response = client.get(f"/foods/{food_id}/nutrition")

    assert response.status_code == 404
    assert response.json()["detail"] == "ไม่พบอาหารที่ระบุ"


def test_reviewed_food_with_unreviewed_basis_does_not_calculate(client):
    """อาหารผ่านการตรวจ แต่ฐานโภชนาการยังไม่ผ่าน ต้องไม่คำนวณ."""
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": "นูเทลล่า",
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "reviewed",
        }),
        FakeResult([{
            "nutrition_basis_id": "basis-unreviewed",
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "verification_status": "needs_review",
        }]),
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "data_needs_review"
    assert data["nutrition_basis"]["verification_status"] == "needs_review"
    assert "nutrients" not in data
    assert fake_db.execute_count == 3


def test_calculate_returns_404_when_rule_missing(client):
    """ไม่พบ NUT-001 ต้องไม่คำนวณ."""
    app.dependency_overrides[get_db] = lambda: FakeDB([
        FakeResult(None),
    ])

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_per_100g": 57.5,
            "eaten_weight_g": 15,
            "nutrient_code": "protein_g",
            "unit": "g",
            "source": "test",
        },
    )

    assert response.status_code == 404
    assert "ไม่พบกฎ NUT-001" in response.json()["detail"]


def test_calculate_from_food_returns_404_when_rule_missing(client):
    """พบอาหารและฐานแล้ว แต่ไม่พบกฎ ต้องไม่คำนวณ."""
    food_id = "8d78d477-67c6-4272-92a6-5495e114402e"

    fake_db = FakeDB([
        FakeResult({
            "food_id": food_id,
            "name_th": "นูเทลล่า",
            "name_en": "Nutella",
            "brand_name": "Ferrero",
            "verification_status": "reviewed",
        }),
        FakeResult([{
            "nutrition_basis_id": "basis-reviewed",
            "basis_type": "per_100g",
            "basis_quantity": 100,
            "basis_unit": "g",
            "verification_status": "reviewed",
        }]),
        FakeResult(None),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate-from-food",
        json={
            "food_id": food_id,
            "eaten_weight_g": 15,
        },
    )

    assert response.status_code == 404
    assert "ไม่พบกฎ NUT-001" in response.json()["detail"]
    assert fake_db.execute_count == 3








def test_calculate_rejects_mismatched_nutrient_unit(client):
    """protein_g ต้องไม่คำนวณเมื่อส่งหน่วย kcal."""
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult({
            "nutrient_code": "protein_g",
            "canonical_unit": "g",
        }),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_code": "protein_g",
            "nutrient_per_100g": 25,
            "eaten_weight_g": 20,
            "unit": "kcal",
            "source": "unit mismatch test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "invalid_input"
    assert data["expected_unit"] == "g"
    assert data["received_unit"] == "kcal"
    assert "consumed" not in data


def test_calculate_rejects_unknown_nutrient_code(client):
    """รหัสสารอาหารที่ไม่พบต้องไม่คำนวณ."""
    fake_db = FakeDB([
        FakeResult({
            "rule_code": "NUT-001",
            "rule_name": "คำนวณจากค่าต่อ 100 กรัม",
            "lifecycle_status": "active",
            "decision_logic": (
                "consumed = nutrient_per_100g "
                "* eaten_weight_g / 100"
            ),
        }),
        FakeResult(None),
    ])

    app.dependency_overrides[get_db] = lambda: fake_db

    response = client.post(
        "/nutrition/calculate",
        json={
            "nutrient_code": "unknown_nutrient",
            "nutrient_per_100g": 25,
            "eaten_weight_g": 20,
            "unit": "g",
            "source": "unknown nutrient test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "invalid_input"
    assert "consumed" not in data
