from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


class FakeResult:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.row


class FakeDB:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.last_query = ""
        self.last_params = {}

    def execute(self, query, params=None):
        self.last_query = str(query)
        self.last_params = params or {}
        return FakeResult(rows=self.rows, row=self.row)

    def close(self):
        pass


def test_get_rules_returns_count_and_items():
    db = FakeDB(rows=[
        {"rule_code": "CORE-001", "lifecycle_status": "draft"},
        {"rule_code": "NUT-001", "lifecycle_status": "draft"},
    ])
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get("/rules")

        assert response.status_code == 200
        assert response.json()["count"] == 2
        assert len(response.json()["items"]) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_rules_filters_by_category_and_status():
    db = FakeDB(rows=[
        {"rule_code": "NUT-001", "category": "nutrition",
         "lifecycle_status": "draft"},
    ])
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get(
                "/rules",
                params={
                    "category": "nutrition",
                    "lifecycle_status": "draft",
                },
            )

        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert db.last_params["category"] == "nutrition"
        assert db.last_params["lifecycle_status"] == "draft"
        assert "category = :category" in db.last_query
        assert "lifecycle_status = :lifecycle_status" in db.last_query
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_rules_rejects_limit_over_100():
    app.dependency_overrides[get_db] = lambda: FakeDB()

    try:
        with TestClient(app) as client:
            response = client.get("/rules", params={"limit": 101})

        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_rule_by_code_returns_404_when_missing():
    app.dependency_overrides[get_db] = lambda: FakeDB(row=None)

    try:
        with TestClient(app) as client:
            response = client.get("/rules/NO-SUCH-RULE")

        assert response.status_code == 404
        assert response.json()["detail"] == "Rule not found"
    finally:
        app.dependency_overrides.pop(get_db, None)
