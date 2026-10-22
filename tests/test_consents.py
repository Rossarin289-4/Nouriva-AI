from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key

USER_ID = "00000000-0000-0000-0000-000000000021"
CONSENT_ID = "00000000-0000-0000-0000-000000000031"


def make_token():
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": USER_ID,
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        get_secret_key(),
        algorithm="HS256",
    )


def auth_headers():
    return {"Authorization": f"Bearer {make_token()}"}


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        if len(self.rows) != 1:
            raise AssertionError("Expected exactly one row")
        return self.rows[0]


class ConsentFakeDB:
    def __init__(self, withdraw_record=True):
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.withdraw_record = withdraw_record

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.calls.append((sql, params))

        if "FROM app_users" in sql:
            return FakeResult([{
                "user_id": USER_ID,
                "email": "consent-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            }])

        if "FROM user_consents" in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult([])

        if sql.lstrip().startswith("INSERT INTO user_consents"):
            return FakeResult([{
                "consent_id": CONSENT_ID,
                "consent_type": params["consent_type"],
                "policy_version": params["policy_version"],
                "consented_at": datetime(
                    2026, 10, 22, tzinfo=timezone.utc
                ),
                "withdrawn_at": None,
                "consent_metadata": {},
            }])

        if sql.lstrip().startswith("UPDATE user_consents"):
            if not self.withdraw_record:
                return FakeResult([])

            return FakeResult([{
                "consent_id": params["consent_id"],
                "consent_type": "external_ai_processing",
                "policy_version": "1.0",
                "consented_at": datetime(
                    2026, 10, 22, tzinfo=timezone.utc
                ),
                "withdrawn_at": datetime(
                    2026, 10, 22, 1, tzinfo=timezone.utc
                ),
                "consent_metadata": {},
            }])

        raise AssertionError("Unexpected SQL: " + sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def run_with_db(fake_db, callback):
    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        with TestClient(app) as client:
            return callback(client)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_consents_without_token_returns_401():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.get("/consents"),
    )

    assert response.status_code == 401


def test_list_consents_returns_empty_list():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.get(
            "/consents",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"consents": []}

    select_call = next(
        (sql, params)
        for sql, params in db.calls
        if "FROM user_consents" in sql
    )
    sql, params = select_call
    assert "WHERE user_id = :user_id" in sql
    assert params["user_id"] == USER_ID


def test_create_consent_saves_explicit_consent():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            "/consents",
            headers=auth_headers(),
            json={
                "consent_type": "external_ai_processing",
                "policy_version": "1.0",
                "consent_metadata": {"source": "settings"},
            },
        ),
    )

    assert response.status_code == 201
    consent = response.json()["consent"]
    assert consent["consent_type"] == "external_ai_processing"
    assert consent["policy_version"] == "1.0"
    assert db.committed

    sql, params = next(
        (sql, params)
        for sql, params in db.calls
        if sql.lstrip().startswith("INSERT INTO user_consents")
    )
    assert params["user_id"] == USER_ID
    assert params["consent_type"] == "external_ai_processing"


def test_create_consent_rejects_unknown_type():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            "/consents",
            headers=auth_headers(),
            json={
                "consent_type": "health_data",
                "policy_version": "1.0",
            },
        ),
    )

    assert response.status_code == 422
    assert not any(
        sql.lstrip().startswith("INSERT INTO user_consents")
        for sql, _ in db.calls
    )


def test_create_consent_rejects_unknown_fields():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            "/consents",
            headers=auth_headers(),
            json={
                "consent_type": "external_ai_processing",
                "policy_version": "1.0",
                "user_id": "00000000-0000-0000-0000-000000000099",
            },
        ),
    )

    assert response.status_code == 422


def test_withdraw_consent_commits_for_own_active_record():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            f"/consents/{CONSENT_ID}/withdraw",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 200
    consent = response.json()["consent"]
    assert consent["consent_id"] == CONSENT_ID
    assert consent["withdrawn_at"] is not None
    assert db.committed

    sql, params = next(
        (sql, params)
        for sql, params in db.calls
        if sql.lstrip().startswith("UPDATE user_consents")
    )
    assert "user_id = :user_id" in sql
    assert "withdrawn_at IS NULL" in sql
    assert params["user_id"] == USER_ID
    assert str(UUID(params["consent_id"])) == CONSENT_ID


def test_withdraw_missing_or_other_users_record_returns_404():
    db = ConsentFakeDB(withdraw_record=False)

    response = run_with_db(
        db,
        lambda client: client.post(
            f"/consents/{CONSENT_ID}/withdraw",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 404
    assert db.rolled_back
    assert not db.committed


def test_withdraw_invalid_uuid_returns_422():
    db = ConsentFakeDB()

    response = run_with_db(
        db,
        lambda client: client.post(
            "/consents/not-a-uuid/withdraw",
            headers=auth_headers(),
        ),
    )

    assert response.status_code == 422
    assert not any(
        sql.lstrip().startswith("UPDATE user_consents")
        for sql, _ in db.calls
    )
