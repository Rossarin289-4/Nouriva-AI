from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key
from app.routes.allergies import router as allergies_router

USER_ID = "00000000-0000-0000-0000-000000000021"
ALLERGY_ID = "00000000-0000-0000-0000-000000000041"

# Register the router only in this test module.
# app/main.py remains unchanged until the route tests are ready.
if not any(route.path == "/allergies" for route in app.routes):
    app.include_router(allergies_router)


def auth_headers():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": USER_ID,
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        get_secret_key(),
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def one(self):
        if len(self.rows) != 1:
            raise AssertionError("Expected exactly one row")
        return self.rows[0]


class AllergyFakeDB:
    def __init__(self, consent=True, allergy=None, profile=None):
        self.consent = consent
        self.allergy = allergy
        self.profile = profile
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.calls.append((sql, params))

        if "FROM app_users" in sql:
            return FakeResult([{
                "user_id": USER_ID,
                "email": "allergy-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            }])

        if "FROM user_consents" in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult(
                [{"consent_id": "consent-test"}] if self.consent else []
            )

        if "FROM user_allergy_profiles" in sql:
            return FakeResult([self.profile] if self.profile else [])

        if "SELECT COUNT(*) AS total" in sql:
            return FakeResult([{"total": 0}])

        if sql.lstrip().startswith("INSERT INTO user_allergies"):
            return FakeResult([{
                "allergy_id": ALLERGY_ID,
                "allergen_code": params["allergen_code"],
                "display_label": params["display_label"],
                "confirmation_status": "reported_unconfirmed",
                "source_type": "user_reported",
                "notes": params.get("notes"),
                "created_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            }])

        if sql.lstrip().startswith("INSERT INTO user_allergy_profiles"):
            return FakeResult([{
                "allergy_status": params.get("allergy_status", "has_reported_allergies"),
                "source_type": "user_reported",
                "updated_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            }])

        if (
            "FROM user_allergies" in sql
            and sql.lstrip().startswith("SELECT")
            and "SELECT COUNT(*) AS total" not in sql
        ):
            return FakeResult([])

        if sql.lstrip().startswith("UPDATE user_allergies"):
            if self.allergy is None:
                return FakeResult([])
            return FakeResult([self.allergy])

        raise AssertionError("Unexpected SQL: " + sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def run_with_db(db, callback):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            return callback(client)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_allergy_routes_require_authentication():
    db = AllergyFakeDB()

    response = run_with_db(db, lambda client: client.get("/allergies"))

    assert response.status_code == 401


def test_read_allergies_defaults_to_not_asked():
    db = AllergyFakeDB()

    response = run_with_db(
        db,
        lambda client: client.get("/allergies", headers=auth_headers()),
    )

    assert response.status_code == 200
    assert response.json()["profile"]["allergy_status"] == "not_asked"
    assert response.json()["allergies"] == []



def test_read_allergies_requires_health_data_consent():
    db = AllergyFakeDB(consent=False)

    response = run_with_db(
        db,
        lambda client: client.get(
            "/allergies",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 403
    assert not any(
        "FROM user_allergy_profiles" in sql
        or "FROM user_allergies" in sql
        for sql, _ in db.calls
    )

def test_create_allergy_requires_health_data_consent():
    db = AllergyFakeDB(consent=False)

    response = run_with_db(
        db,
        lambda client: client.post(
            "/allergies",
            headers=auth_headers(),
            json={
                "allergen_code": "peanut",
                "display_label": "ถั่วลิสง",
            },
        ),
    )

    assert response.status_code == 403
    assert not any(
        sql.lstrip().startswith("INSERT INTO user_allergies")
        for sql, _ in db.calls
    )
    assert not db.committed


def test_create_allergy_saves_user_reported_record_with_consent():
    db = AllergyFakeDB(consent=True)

    response = run_with_db(
        db,
        lambda client: client.post(
            "/allergies",
            headers=auth_headers(),
            json={
                "allergen_code": " peanut ",
                "display_label": " ถั่วลิสง ",
            },
        ),
    )

    assert response.status_code == 201
    assert response.json()["allergy"]["allergen_code"] == "peanut"
    assert response.json()["allergy"]["confirmation_status"] == "reported_unconfirmed"
    assert db.committed

    insert_call = next(
        (sql, params)
        for sql, params in db.calls
        if sql.lstrip().startswith("INSERT INTO user_allergies")
    )
    assert insert_call[1]["user_id"] == USER_ID


def test_create_allergy_rejects_unknown_fields():
    db = AllergyFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            "/allergies",
            headers=auth_headers(),
            json={
                "allergen_code": "peanut",
                "display_label": "ถั่วลิสง",
                "user_id": "00000000-0000-0000-0000-000000000099",
            },
        ),
    )

    assert response.status_code == 422


def test_update_allergy_requires_consent():
    db = AllergyFakeDB(consent=False)

    response = run_with_db(
        db,
        lambda client: client.patch(
            f"/allergies/{ALLERGY_ID}",
            headers=auth_headers(),
            json={"display_label": "ถั่วลิสง"},
        ),
    )

    assert response.status_code == 403
    assert not any(
        sql.lstrip().startswith("UPDATE user_allergies")
        for sql, _ in db.calls
    )


def test_update_other_users_allergy_returns_404():
    db = AllergyFakeDB(consent=True, allergy=None)

    response = run_with_db(
        db,
        lambda client: client.patch(
            f"/allergies/{ALLERGY_ID}",
            headers=auth_headers(),
            json={"display_label": "รายการที่แก้ไข"},
        ),
    )

    assert response.status_code == 404

    update_call = next(
        (sql, params)
        for sql, params in db.calls
        if sql.lstrip().startswith("UPDATE user_allergies")
    )
    assert "AND user_id = :user_id" in update_call[0]
    assert update_call[1]["user_id"] == USER_ID


def test_delete_allergy_can_deactivate_after_consent_withdrawal():
    db = AllergyFakeDB(
        consent=False,
        allergy={"allergy_id": ALLERGY_ID},
    )

    response = run_with_db(
        db,
        lambda client: client.delete(
            f"/allergies/{ALLERGY_ID}",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 204
    assert db.committed
