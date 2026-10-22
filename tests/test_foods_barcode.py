import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeDB:
    def __init__(self, rows=None, fail_insert=False):
        self.rows = iter(rows or [])
        self.queries = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_insert = fail_insert

    def execute(self, query, params=None):
        sql = str(query)
        self.queries.append((sql, params))

        if "SELECT" in sql.upper() and "FOOD_BARCODES" in sql.upper():
            return next(self.rows, FakeResult(None))

        if "INSERT INTO unrecognized_barcodes" in sql:
            if self.fail_insert:
                raise RuntimeError("Simulated database error")

        return FakeResult(None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def client():
    fake_db = FakeDB()
    app.dependency_overrides[get_db] = lambda: fake_db

    with TestClient(app) as test_client:
        yield test_client, fake_db

    app.dependency_overrides.clear()


def test_invalid_barcode_returns_422(client):
    test_client, fake_db = client

    response = test_client.get("/foods/barcode/ABC123")

    assert response.status_code == 422
    assert fake_db.queries == []


def test_barcode_not_found_is_recorded(client):
    test_client, fake_db = client

    response = test_client.get("/foods/barcode/8850051006863")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "ยังไม่มีข้อมูลสินค้านี้ในคลังอาหาร "
        "ลองค้นหาชื่ออาหารหรือกรอกรหัสอื่น"
    )
    assert any(
        "INSERT INTO unrecognized_barcodes" in sql
        for sql, _ in fake_db.queries
    )
    assert fake_db.commits == 1


def test_found_barcode_returns_food(client):
    test_client, fake_db = client
    fake_db.rows = iter([
        FakeResult({
            "barcode": "8850051006863",
            "barcode_type": "EAN13",
            "food_id": "food-123",
            "item_type": "packaged_food",
            "name_th": "น้ำดื่ม",
            "name_en": "Drinking Water",
            "brand_name": "Example",
            "preparation_state": "ready_to_eat",
            "verification_status": "verified",
        })
    ])

    response = test_client.get("/foods/barcode/8850051006863")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["item"]["name_th"] == "น้ำดื่ม"
    assert not any(
        "INSERT INTO unrecognized_barcodes" in sql
        for sql, _ in fake_db.queries
    )


def test_database_insert_error_keeps_not_found_response(client):
    test_client, fake_db = client
    fake_db.fail_insert = True

    response = test_client.get("/foods/barcode/8850051006863")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "ยังไม่มีข้อมูลสินค้านี้ในคลังอาหาร "
        "ลองค้นหาชื่ออาหารหรือกรอกรหัสอื่น"
    )
    assert fake_db.rollbacks == 1
