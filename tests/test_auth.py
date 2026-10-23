from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


class FakeDB:
    def close(self):
        pass


def test_auth_me_without_token_returns_401():
    app.dependency_overrides[get_db] = lambda: FakeDB()

    try:
        with TestClient(app) as client:
            response = client.get("/auth/me")

        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "Bearer"
    finally:
        app.dependency_overrides.pop(get_db, None)


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class LoginFakeDB:
    def __init__(self, row):
        self.row = row

    def execute(self, query, params=None):
        return FakeResult(self.row)

    def close(self):
        pass


def test_login_unknown_email_returns_401():
    app.dependency_overrides[get_db] = lambda: LoginFakeDB(None)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/login",
                json={
                    "email": "nobody@example.com",
                    "password": "WrongPassword123",
                },
            )

        assert response.status_code == 401
        assert response.json()["detail"] == "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_login_wrong_password_returns_401():
    from app.routes.auth import password_hasher

    user = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "password_hash": password_hasher.hash("CorrectPassword123"),
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }

    app.dependency_overrides[get_db] = lambda: LoginFakeDB(user)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/login",
                json={
                    "email": "tester@example.com",
                    "password": "WrongPassword123",
                },
            )

        assert response.status_code == 401
        assert response.json()["detail"] == "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_login_success_returns_access_token():
    from app.routes.auth import password_hasher

    user = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "password_hash": password_hasher.hash("CorrectPassword123"),
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }

    app.dependency_overrides[get_db] = lambda: LoginFakeDB(user)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/login",
                json={
                    "email": "tester@example.com",
                    "password": "CorrectPassword123",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 3600
        assert data["user"]["email"] == "tester@example.com"
        assert data["access_token"]
        assert "password_hash" not in data["user"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_auth_me_with_valid_token_returns_user_and_profile():
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.routes.auth import get_secret_key

    user_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": user_id,
            "jti": str(__import__("uuid").uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        get_secret_key(),
        algorithm="HS256",
    )

    class MeFakeDB:
        def __init__(self):
            self.calls = 0

        def execute(self, query, params=None):
            query_text = str(query)

            if "revoked_auth_tokens" in query_text:
                return FakeResult(None)

            if "FROM public.app_users" in query_text:
                return FakeResult({
                    "user_id": user_id,
                    "email": "tester@example.com",
                    "role": "user",
                    "is_active": True,
                    "email_verified_at": None,
                })

            return FakeResult({
                "display_name": "Test User",
                "preferred_language": "th",
                "time_zone": "Asia/Bangkok",
            })

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: MeFakeDB()

    try:
        with TestClient(app) as client:
            response = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["user"]
        assert data["email"] == "tester@example.com"
        assert data["email_verified"] is False
        assert data["profile"]["display_name"] == "Test User"
        assert data["profile"]["preferred_language"] == "th"
    finally:
        app.dependency_overrides.pop(get_db, None)


class RegisterResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row

    def mappings(self):
        return self

    def one(self):
        return self.row


class RegisterFakeDB:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.calls = 0
        self.statements = []
        self.params = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        self.calls += 1
        self.statements.append(str(query))
        self.params.append(params or {})

        if self.calls == 1:
            return RegisterResult(self.existing_user)

        if self.calls == 2:
            return RegisterResult({
                "user_id": "00000000-0000-0000-0000-000000000002",
                "email": "newuser@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
                "created_at": None,
            })

        return RegisterResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_register_success_creates_user_and_profile():
    fake_db = RegisterFakeDB()
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/register",
                json={
                    "email": "NewUser@Example.com",
                    "password": "StrongPassword123",
                    "display_name": " New User ",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["role"] == "user"
        assert data["user"]["email_verified"] is False
        assert "password_hash" not in data["user"]
        assert fake_db.committed is True
        assert fake_db.rolled_back is False
        assert fake_db.calls == 3

        stored_hash = fake_db.params[1]["password_hash"]
        from app.routes.auth import password_hasher
        assert stored_hash != "StrongPassword123"
        assert password_hasher.verify(stored_hash, "StrongPassword123")

        profile_params = fake_db.params[2]
        assert profile_params["display_name"] == "New User"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_register_duplicate_email_returns_409():
    fake_db = RegisterFakeDB(
        existing_user={"user_id": "existing-user"}
    )
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/register",
                json={
                    "email": "existing@example.com",
                    "password": "StrongPassword123",
                    "display_name": "Existing User",
                },
            )

        assert response.status_code == 409
        assert fake_db.calls == 1
        assert fake_db.committed is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_login_sets_httponly_cookie():
    from app.routes.auth import password_hasher

    user = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "password_hash": password_hasher.hash("CorrectPassword123"),
        "role": "user",
        "is_active": True,
        "email_verified_at": None,
    }
    app.dependency_overrides[get_db] = lambda: LoginFakeDB(user)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/login",
                json={
                    "email": "tester@example.com",
                    "password": "CorrectPassword123",
                },
            )

        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "nouriva_access_token=" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "max-age=3600" in cookie
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_logout_clears_auth_cookie():
    with TestClient(app) as client:
        response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json()["message"] == "ออกจากระบบแล้ว"
    cookie = response.headers["set-cookie"].lower()
    assert "nouriva_access_token=" in cookie
    assert "max-age=0" in cookie


def test_auth_me_accepts_cookie_without_bearer_token():
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.routes.auth import get_secret_key

    user_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user_id,
            "jti": str(__import__("uuid").uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        get_secret_key(),
        algorithm="HS256",
    )

    class CookieMeFakeDB:
        def __init__(self):
            self.calls = 0

        def execute(self, query, params=None):
            query_text = str(query)

            if "revoked_auth_tokens" in query_text:
                return FakeResult(None)

            if "FROM public.app_users" in query_text:
                return FakeResult({
                    "user_id": user_id,
                    "email": "tester@example.com",
                    "role": "user",
                    "is_active": True,
                    "email_verified_at": None,
                })

            return FakeResult({
                "display_name": "Cookie User",
                "preferred_language": "th",
                "time_zone": "Asia/Bangkok",
            })

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: CookieMeFakeDB()

    try:
        with TestClient(app) as client:
            client.cookies.set("nouriva_access_token", token)
            response = client.get("/auth/me")

        assert response.status_code == 200
        assert response.json()["user"]["profile"]["display_name"] == "Cookie User"
    finally:
        app.dependency_overrides.pop(get_db, None)



def test_logout_revokes_token_and_auth_me_returns_401():
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import jwt
    from app.routes.auth import get_secret_key

    user_id = "00000000-0000-0000-0000-000000000001"
    token_jti = str(uuid4())
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": user_id,
            "jti": token_jti,
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        get_secret_key(),
        algorithm="HS256",
    )

    class RevocationFakeDB:
        def __init__(self):
            self.revoked_tokens = set()
            self.committed = False

        def execute(self, query, params=None):
            query_text = str(query)
            params = params or {}

            if "INSERT INTO public.revoked_auth_tokens" in query_text:
                self.revoked_tokens.add(params["token_jti"])
                return FakeResult(None)

            if "FROM public.revoked_auth_tokens" in query_text:
                return FakeResult(
                    {"?column?": 1}
                    if params["token_jti"] in self.revoked_tokens
                    else None
                )

            if "FROM public.app_users" in query_text:
                return FakeResult({
                    "user_id": user_id,
                    "email": "tester@example.com",
                    "role": "user",
                    "is_active": True,
                    "email_verified_at": None,
                })

            if "FROM public.user_profiles" in query_text:
                return FakeResult({
                    "display_name": "Test User",
                    "preferred_language": "th",
                    "time_zone": "Asia/Bangkok",
                })

            raise AssertionError("Unexpected SQL: " + query_text)

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            pass

    fake_db = RevocationFakeDB()
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as client:
            logout_response = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

            me_response = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert logout_response.status_code == 200
        assert fake_db.committed is True
        assert token_jti in fake_db.revoked_tokens
        assert me_response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_logout_returns_503_when_token_revocation_fails():
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import jwt
    from app.routes.auth import get_secret_key

    user_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": user_id,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        get_secret_key(),
        algorithm="HS256",
    )

    class FailingRevocationDB:
        def execute(self, query, params=None):
            if "INSERT INTO public.revoked_auth_tokens" in str(query):
                raise RuntimeError("Database unavailable")
            raise AssertionError("Unexpected SQL: " + str(query))

        def rollback(self):
            pass

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: FailingRevocationDB()

    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "ไม่สามารถออกจากระบบได้ในขณะนี้ กรุณาลองอีกครั้ง"
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
