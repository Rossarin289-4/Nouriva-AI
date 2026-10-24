import pytest
from fastapi import HTTPException

from app.routes import ai_chat


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class ConsentFakeDB:
    def __init__(self, row):
        self.row = row
        self.sql = ""
        self.params = {}

    def execute(self, query, params=None):
        self.sql = str(query)
        self.params = params or {}
        return FakeResult(self.row)


def test_openai_free_limit_is_ten():
    assert ai_chat._limit_for("openai", "free") == 10


def test_gemini_has_no_app_daily_limit():
    assert ai_chat._limit_for("gemini", "free") is None
    assert ai_chat._limit_for("gemini", "premium") is None


def test_premium_openai_is_disabled_without_config(monkeypatch):
    monkeypatch.delenv("NOURIVAAI_OPENAI_PREMIUM_DAILY_LIMIT", raising=False)
    assert ai_chat._limit_for("openai", "premium") is None


def test_premium_openai_rejects_invalid_or_non_higher_limit(monkeypatch):
    for value in ("", "abc", "10", "0", "-1"):
        monkeypatch.setenv("NOURIVAAI_OPENAI_PREMIUM_DAILY_LIMIT", value)
        assert ai_chat._limit_for("openai", "premium") is None


def test_premium_openai_accepts_configured_higher_limit(monkeypatch):
    monkeypatch.setenv("NOURIVAAI_OPENAI_PREMIUM_DAILY_LIMIT", "20")
    assert ai_chat._limit_for("openai", "premium") == 20


def test_ai_chat_consent_requires_matching_purpose_and_version():
    db = ConsentFakeDB(None)

    with pytest.raises(HTTPException) as error:
        ai_chat._require_ai_chat_consent(db, "user-1")

    assert error.value.status_code == 403
    assert db.params["policy_version"] == ai_chat.AI_CHAT_CONSENT_VERSION
    assert "consent_metadata->>'purpose' = 'ai_chat'" in db.sql
    assert "withdrawn_at IS NULL" in db.sql


def test_ai_chat_consent_passes_when_matching_active_consent_exists():
    db = ConsentFakeDB({"consent_id": "consent-1"})

    assert ai_chat._require_ai_chat_consent(db, "user-1") is None
    assert db.params["user_id"] == "user-1"


def test_chat_request_rejects_unknown_fields():
    with pytest.raises(Exception):
        ai_chat.ChatRequest(
            provider="gemini",
            message="hello",
            user_id="someone-else",
        )


def test_chat_request_rejects_message_over_limit():
    with pytest.raises(Exception):
        ai_chat.ChatRequest(
            provider="gemini",
            message="x" * 4001,
        )


class MappingResult:
    def __init__(self, row, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one(self):
        return self.row


class ReservationFakeDB:
    def __init__(self, used=0, reserved=0, reservation_id="reservation-123"):
        self.used = used
        self.reserved = reserved
        self.reservation_id = reservation_id
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_update = False
        self.zero_update_rows = False

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.statements.append((sql, params))

        if "COUNT(*) FILTER" in sql:
            return MappingResult({"used": self.used, "reserved": self.reserved})

        if "INSERT INTO public.ai_chat_usage_events" in sql:
            return MappingResult({"usage_event_id": self.reservation_id})

        if "SET status = :status" in sql and self.fail_update:
            from sqlalchemy.exc import SQLAlchemyError
            raise SQLAlchemyError("simulated database error")

        if "SET status = :status" in sql:
            return MappingResult(
                {},
                rowcount=0 if self.zero_update_rows else 1,
            )

        return MappingResult({})

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_reserve_usage_creates_reservation_and_commits():
    from datetime import date

    db = ReservationFakeDB()
    reservation_id = ai_chat._reserve_usage(
        db, "user-1", "openai", date(2026, 10, 24), 10
    )

    assert reservation_id == "reservation-123"
    assert db.commits == 1
    assert any(
        "pg_advisory_xact_lock" in sql
        for sql, _ in db.statements
    )
    assert any(
        "INSERT INTO public.ai_chat_usage_events" in sql
        for sql, _ in db.statements
    )


def test_reserve_usage_rejects_full_quota():
    from datetime import date

    db = ReservationFakeDB(used=10, reserved=0)

    with pytest.raises(HTTPException) as error:
        ai_chat._reserve_usage(
            db, "user-1", "openai", date(2026, 10, 24), 10
        )

    assert error.value.status_code == 429
    assert db.rollbacks == 1
    assert not any(
        "INSERT INTO public.ai_chat_usage_events" in sql
        for sql, _ in db.statements
    )


@pytest.mark.parametrize(
    ("succeeded", "expected_status"),
    [(True, "succeeded"), (False, "failed")],
)
def test_finish_usage_sets_final_status(succeeded, expected_status):
    db = ReservationFakeDB()

    ai_chat._finish_usage(db, "reservation-123", succeeded)

    update = [
        (sql, params)
        for sql, params in db.statements
        if "SET status = :status" in sql
    ]
    assert len(update) == 1
    assert update[0][1]["status"] == expected_status
    assert update[0][1]["usage_event_id"] == "reservation-123"
    assert db.commits == 1


def test_finish_usage_database_error_returns_false_and_rolls_back():
    db = ReservationFakeDB()
    db.fail_update = True

    result = ai_chat._finish_usage(db, "reservation-123", True)

    assert result is False
    assert db.rollbacks == 1
    assert db.commits == 0



def test_finish_usage_returns_false_when_no_reserved_row_is_updated():
    db = ReservationFakeDB()
    db.zero_update_rows = True

    result = ai_chat._finish_usage(db, "reservation-123", True)

    assert result is False
    assert db.rollbacks == 1
    assert db.commits == 0


def test_reservation_lifetime_exceeds_provider_timeout():
    from app.services.ai_chat import PROVIDER_TIMEOUT_SECONDS

    reservation_lifetime_seconds = ai_chat.RESERVATION_MINUTES * 60

    # Keep a safety margin for processing and persisting the final usage status.
    assert reservation_lifetime_seconds >= PROVIDER_TIMEOUT_SECONDS + 60


def test_reserve_usage_cleans_expired_reservations_before_counting():
    from datetime import date

    db = ReservationFakeDB()

    ai_chat._reserve_usage(
        db, "user-1", "openai", date(2026, 10, 24), 10
    )

    cleanup_indexes = [
        index
        for index, (sql, _) in enumerate(db.statements)
        if (
            "UPDATE public.ai_chat_usage_events" in sql
            and "reservation_expires_at <= NOW()" in sql
        )
    ]
    count_indexes = [
        index
        for index, (sql, _) in enumerate(db.statements)
        if "COUNT(*) FILTER" in sql
    ]

    assert len(cleanup_indexes) == 1
    assert len(count_indexes) == 1
    assert cleanup_indexes[0] < count_indexes[0]

    cleanup_sql, cleanup_params = db.statements[cleanup_indexes[0]]
    assert "SET status = 'failed'" in cleanup_sql
    assert cleanup_params["user_id"] == "user-1"
    assert cleanup_params["provider"] == "openai"
    assert cleanup_params["usage_date"] == date(2026, 10, 24)


@pytest.mark.parametrize(
    ("provider", "key_name", "model_name", "default_model"),
    [
        ("gemini", "NOURIVAAI_GEMINI_API_KEY", "NOURIVAAI_GEMINI_MODEL", "gemini-2.5-flash"),
        ("openai", "NOURIVAAI_OPENAI_API_KEY", "NOURIVAAI_OPENAI_MODEL", "gpt-4.1-mini"),
    ],
)
def test_provider_configured_requires_api_key(
    monkeypatch, provider, key_name, model_name, default_model
):
    monkeypatch.delenv(key_name, raising=False)
    monkeypatch.delenv(model_name, raising=False)

    assert ai_chat._provider_configured(provider) is False

    monkeypatch.setenv(key_name, "test-key")
    assert ai_chat._provider_configured(provider) is True

    monkeypatch.setenv(model_name, " ")
    assert ai_chat._provider_configured(provider) is False

    monkeypatch.setenv(model_name, default_model)
    assert ai_chat._provider_configured(provider) is True


def test_provider_configured_rejects_unknown_provider():
    assert ai_chat._provider_configured("unknown") is False


# Endpoint-level tests: mock authentication, database, and external AI provider.
def test_post_ai_chat_requires_authentication():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/ai-chat",
            json={"provider": "gemini", "message": "ทดสอบ"},
        )

    assert response.status_code == 401


def test_post_ai_chat_rejects_unknown_provider_before_database_access():
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routes.auth import get_current_user
    from app.main import app

    class UnusedDB:
        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: UnusedDB()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ai-chat",
                json={"provider": "unknown", "message": "ทดสอบ"},
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)

def test_post_ai_chat_rejects_missing_consent():
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routes.auth import get_current_user
    from app.main import app

    class ConsentDB:
        def execute(self, query, params=None):
            return FakeResult(None)

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: ConsentDB()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ai-chat",
                json={"provider": "gemini", "message": "ทดสอบ"},
            )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ai_chat_consent_required"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_post_ai_chat_rejects_unknown_request_fields():
    from fastapi.testclient import TestClient
    from app.routes.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ai-chat",
                json={
                    "provider": "gemini",
                    "message": "ทดสอบ",
                    "user_id": "another-user",
                },
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
