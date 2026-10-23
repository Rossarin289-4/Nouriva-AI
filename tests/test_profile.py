from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key
import uuid

USER_ID = "00000000-0000-0000-0000-000000000021"


def make_token():
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": USER_ID,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        get_secret_key(),
        algorithm="HS256",
    )


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class ProfileFakeDB:
    def __init__(self):
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        sql = str(query)
        if "revoked_auth_tokens" in sql:
            return FakeResult([])
        self.calls.append((sql, params or {}))

        if "app_users" in sql and "revoked_auth_tokens" not in sql:
            return FakeResult({
                "user_id": USER_ID,
                "email": "profile-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            })

        if "FROM user_profiles" in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult({
                "display_name": "Test User",
                "date_of_birth": None,
                "sex_for_formula": None,
                "activity_level": "unknown",
                "preferred_language": "th",
                "time_zone": "Asia/Bangkok",
            })

        if "FROM body_measurements" in sql and sql.lstrip().startswith("SELECT"):
            return FakeResult({
                "body_measurement_id": "measurement-test-id",
                "measured_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
                "weight_kg": 55.0,
                "height_cm": 160.0,
                "source_type": "user_entered",
                "verification_status": "user_confirmed",
            })

        if sql.lstrip().startswith("UPDATE user_profiles"):
            return FakeResult({
                "display_name": params.get("display_name", "Test User"),
                "date_of_birth": params.get("date_of_birth"),
                "sex_for_formula": params.get("sex_for_formula"),
                "activity_level": params.get("activity_level", "unknown"),
                "preferred_language": "th",
                "time_zone": "Asia/Bangkok",
            })

        if sql.lstrip().startswith("INSERT INTO body_measurements"):
            return FakeResult({
                "body_measurement_id": "new-measurement-id",
                "measured_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
                "weight_kg": params.get("weight_kg"),
                "height_cm": params.get("height_cm"),
                "source_type": "user_entered",
                "verification_status": "user_confirmed",
            })

        raise AssertionError("Unexpected SQL: " + sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def setup_db(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db


def teardown_db():
    app.dependency_overrides.pop(get_db, None)


def auth_headers():
    return {"Authorization": f"Bearer {make_token()}"}


def test_profile_without_token_returns_401():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.get("/profile")

        assert response.status_code == 401
    finally:
        teardown_db()


def test_read_profile_returns_profile_and_latest_measurement():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.get("/profile", headers=auth_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["profile"]["display_name"] == "Test User"
        assert data["profile"]["preferred_language"] == "th"
        assert data["latest_body_measurement"]["weight_kg"] == 55.0
    finally:
        teardown_db()


def test_patch_profile_updates_only_allowed_field():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.patch(
                "/profile",
                headers=auth_headers(),
                json={"display_name": "New Name"},
            )

        assert response.status_code == 200
        assert response.json()["profile"]["display_name"] == "New Name"

        update_sql, params = next(
            (sql, params)
            for sql, params in fake_db.calls
            if sql.lstrip().startswith("UPDATE user_profiles")
        )
        assert "display_name = :display_name" in update_sql
        assert "user_id" in params
        assert params["user_id"] == USER_ID
        assert fake_db.committed
    finally:
        teardown_db()


def test_patch_profile_rejects_unknown_field():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.patch(
                "/profile",
                headers=auth_headers(),
                json={"role": "admin"},
            )

        assert response.status_code == 422
    finally:
        teardown_db()


def test_body_measurement_requires_weight_or_height():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/profile/body-measurements",
                headers=auth_headers(),
                json={},
            )

        assert response.status_code == 422
    finally:
        teardown_db()


def test_body_measurement_rejects_out_of_range_weight():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/profile/body-measurements",
                headers=auth_headers(),
                json={"weight_kg": 1000},
            )

        assert response.status_code == 422
    finally:
        teardown_db()


def test_body_measurement_creates_new_record():
    fake_db = ProfileFakeDB()
    setup_db(fake_db)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/profile/body-measurements",
                headers=auth_headers(),
                json={"weight_kg": 55.5, "height_cm": 160},
            )

        assert response.status_code == 201
        assert response.json()["measurement"]["weight_kg"] == 55.5

        insert_sql, params = next(
            (sql, params)
            for sql, params in fake_db.calls
            if sql.lstrip().startswith("INSERT INTO body_measurements")
        )
        assert "user_id" in params
        assert params["user_id"] == USER_ID
        assert fake_db.committed
    finally:
        teardown_db()
