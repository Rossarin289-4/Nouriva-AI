from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key
from app.routes.allergies import router as allergies_router


USER_ID = "00000000-0000-0000-0000-000000000021"


if not any(route.path == "/allergies" for route in app.routes):
    app.include_router(allergies_router)


class Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class WithdrawnConsentDB:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        sql = str(query)
        self.calls.append(sql)

        if "FROM app_users" in sql:
            return Result([{
                "user_id": USER_ID,
                "email": "allergy-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            }])

        if "FROM user_consents" in sql:
            # The user has withdrawn all health-data consent.
            return Result([])

        raise AssertionError(
            "Unexpected query; allergy data must not be read: " + sql
        )

    def close(self):
        pass


def test_withdrawn_health_data_consent_blocks_allergy_read():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": USER_ID,
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        get_secret_key(),
        algorithm="HS256",
    )
    db = WithdrawnConsentDB()
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            response = client.get(
                "/allergies",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 403
    assert not any(
        "FROM user_allergy_profiles" in sql
        or "FROM user_allergies" in sql
        for sql in db.calls
    )
