from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key

USER_ID = "00000000-0000-0000-0000-000000000021"


def auth_headers():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": USER_ID,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        get_secret_key(),
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class MealsFakeDB:
    def __init__(self, returned_row=None, returned_rows=None):
        self.returned_row = returned_row
        self.returned_rows = returned_rows or []
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}

        if "revoked_auth_tokens" in sql:
            return Result(row=None)

        if "FROM public.app_users" in sql:
            return Result(row={
                "user_id": USER_ID,
                "email": "meal-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            })

        self.calls.append((sql, params))
        if sql.lstrip().startswith("INSERT INTO meal_logs"):
            return Result(row=self.returned_row)
        if "FROM meal_logs" in sql:
            return Result(rows=self.returned_rows)

        raise AssertionError("Unexpected SQL: " + sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def setup_db(db):
    app.dependency_overrides[get_db] = lambda: db


def teardown_db():
    app.dependency_overrides.pop(get_db, None)


def test_create_meal_requires_authentication():
    setup_db(MealsFakeDB())
    try:
        with TestClient(app) as client:
            response = client.post("/meals", json={
                "meal_date": "2026-10-23",
                "meal_type": "lunch",
            })
        assert response.status_code == 401
    finally:
        teardown_db()


def test_create_meal_saves_for_authenticated_user():
    meal_id = "00000000-0000-0000-0000-000000000099"
    db = MealsFakeDB(returned_row={
        "meal_log_id": meal_id,
        "meal_date": date(2026, 10, 23),
        "meal_type": "lunch",
        "eaten_at": None,
        "title": "มื้อกลางวัน",
        "notes": None,
        "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
    })
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals",
                headers=auth_headers(),
                json={
                    "meal_date": "2026-10-23",
                    "meal_type": "lunch",
                    "title": " มื้อกลางวัน ",
                },
            )

        assert response.status_code == 201
        assert response.json()["status"] == "success"
        assert response.json()["meal"]["meal_log_id"] == meal_id

        sql, params = next(
            (sql, params) for sql, params in db.calls
            if sql.lstrip().startswith("INSERT INTO meal_logs")
        )
        assert "user_id" in sql
        assert params["user_id"] == USER_ID
        assert params["meal_type"] == "lunch"
        assert params["title"] == "มื้อกลางวัน"
        assert db.committed
    finally:
        teardown_db()


def test_create_meal_rejects_invalid_meal_type():
    setup_db(MealsFakeDB())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals",
                headers=auth_headers(),
                json={
                    "meal_date": "2026-10-23",
                    "meal_type": "brunch",
                },
            )
        assert response.status_code == 422
    finally:
        teardown_db()


def test_create_meal_rejects_unknown_fields():
    setup_db(MealsFakeDB())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals",
                headers=auth_headers(),
                json={
                    "meal_date": "2026-10-23",
                    "meal_type": "dinner",
                    "user_id": "00000000-0000-0000-0000-000000000001",
                },
            )
        assert response.status_code == 422
    finally:
        teardown_db()


def test_list_meals_requires_authentication():
    setup_db(MealsFakeDB())
    try:
        with TestClient(app) as client:
            response = client.get("/meals")
        assert response.status_code == 401
    finally:
        teardown_db()


def test_list_meals_filters_by_authenticated_user():
    db = MealsFakeDB(returned_rows=[{
        "meal_log_id": "meal-1",
        "meal_date": date(2026, 10, 23),
        "meal_type": "breakfast",
        "eaten_at": None,
        "title": "อาหารเช้า",
        "notes": None,
        "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
    }])
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/meals?meal_date=2026-10-23&limit=10",
                headers=auth_headers(),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["items"][0]["meal_type"] == "breakfast"

        sql, params = next(
            (sql, params) for sql, params in db.calls
            if "FROM meal_logs" in sql
        )
        assert "WHERE user_id = :user_id" in sql
        assert params["user_id"] == USER_ID
        assert params["meal_date"] == date(2026, 10, 23)
    finally:
        teardown_db()


def test_list_meals_rejects_invalid_limit():
    setup_db(MealsFakeDB())
    try:
        with TestClient(app) as client:
            response = client.get(
                "/meals?limit=101",
                headers=auth_headers(),
            )
        assert response.status_code == 422
    finally:
        teardown_db()


class MealItemFakeDB:
    def __init__(self, owns_meal=True, food=None, portion=None):
        self.owns_meal = owns_meal
        self.food = food
        self.portion = portion
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}

        if "revoked_auth_tokens" in sql:
            return Result(row=None)

        if "FROM public.app_users" in sql:
            return Result(row={
                "user_id": USER_ID,
                "email": "meal-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            })

        self.calls.append((sql, params))

        if "FROM meal_logs" in sql and "user_id = :user_id" in sql:
            return Result(row={"meal_log_id": "owned-meal"} if self.owns_meal else None)

        if "FROM food_items" in sql:
            return Result(row=self.food)

        if "FROM food_portions" in sql:
            return Result(row=self.portion)

        if sql.lstrip().startswith("INSERT INTO meal_items"):
            return Result(row={
                "meal_item_id": "new-item",
                "meal_log_id": params["meal_log_id"],
                "food_id": params["food_id"],
                "food_name_snapshot": params["food_name_snapshot"],
                "quantity_value": params["quantity_value"],
                "quantity_unit": params["quantity_unit"],
                "weight_g": params["weight_g"],
                "volume_ml": params["volume_ml"],
                "portion_id": params["portion_id"],
                "entry_source": params["entry_source"],
                "confirmation_status": "needs_review",
                "notes": params["notes"],
            })

        raise AssertionError("Unexpected SQL: " + sql)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_create_meal_item_cannot_modify_another_users_meal():
    db = MealItemFakeDB(owns_meal=False)
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
                json={
                    "food_name": "ข้าว",
                    "quantity_value": 1,
                    "quantity_unit": "serving",
                },
            )

        assert response.status_code == 404
        assert not any(
            sql.lstrip().startswith("INSERT INTO meal_items")
            for sql, _ in db.calls
        )
        assert not db.committed
    finally:
        teardown_db()


def test_create_manual_meal_item_for_owned_meal():
    db = MealItemFakeDB()
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
                json={
                    "food_name": " ข้าวสวย ",
                    "quantity_value": 1,
                    "quantity_unit": "serving",
                    "entry_source": "manual",
                },
            )

        assert response.status_code == 201
        data = response.json()["item"]
        assert data["food_name_snapshot"] == "ข้าวสวย"
        assert data["confirmation_status"] == "needs_review"
        assert db.committed

        sql, params = next(
            (sql, params) for sql, params in db.calls
            if sql.lstrip().startswith("INSERT INTO meal_items")
        )
        assert params["meal_log_id"] == "00000000-0000-0000-0000-000000000099"
        assert params["food_id"] is None
        assert params["confirmation_status"] if "confirmation_status" in params else True
    finally:
        teardown_db()


def test_create_meal_item_rejects_inactive_or_missing_food():
    db = MealItemFakeDB(food=None)
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
                json={
                    "food_id": "00000000-0000-0000-0000-000000000088",
                    "quantity_value": 1,
                    "quantity_unit": "g",
                },
            )

        assert response.status_code == 404
        assert not db.committed
    finally:
        teardown_db()


def test_create_meal_item_rejects_unverified_or_mismatched_portion():
    db = MealItemFakeDB(
        food={
            "food_id": "00000000-0000-0000-0000-000000000088",
            "name_th": "ข้าว",
            "name_en": "Rice",
            "preparation_state": None,
        },
        portion=None,
    )
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
                json={
                    "food_id": "00000000-0000-0000-0000-000000000088",
                    "food_name": "ชื่อที่ไม่ควรถูกใช้แทนชื่อในคลัง",
                    "quantity_value": 1,
                    "quantity_unit": "portion",
                    "portion_id": "00000000-0000-0000-0000-000000000077",
                },
            )

        assert response.status_code == 422
        assert not db.committed
    finally:
        teardown_db()


def test_list_meal_items_requires_authentication():
    db = MealItemFakeDB()
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/meals/00000000-0000-0000-0000-000000000099/items"
            )
        assert response.status_code == 401
    finally:
        teardown_db()


def test_list_meal_items_rejects_meal_not_owned_by_user():
    db = MealItemFakeDB(owns_meal=False)
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
            )

        assert response.status_code == 404
        assert not any(
            "FROM meal_items" in sql
            for sql, _ in db.calls
        )
    finally:
        teardown_db()


def test_list_meal_items_returns_only_items_for_owned_meal():
    db = MealItemFakeDB()
    expected_item = {
        "meal_item_id": "00000000-0000-0000-0000-000000000077",
        "meal_log_id": "00000000-0000-0000-0000-000000000099",
        "food_id": None,
        "food_name_snapshot": "ข้าวสวย",
        "preparation_state_snapshot": None,
        "quantity_value": 1,
        "quantity_unit": "serving",
        "weight_g": None,
        "volume_ml": None,
        "portion_id": None,
        "entry_source": "manual",
        "confirmation_status": "needs_review",
        "source_confidence": None,
        "notes": None,
        "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
    }

    original_execute = db.execute

    def execute_with_items(query, params=None):
        sql = str(query)
        if "FROM meal_items" in sql:
            db.calls.append((sql, params or {}))
            return Result(rows=[expected_item])
        return original_execute(query, params)

    db.execute = execute_with_items
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/meals/00000000-0000-0000-0000-000000000099/items",
                headers=auth_headers(),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["meal_log_id"] == "00000000-0000-0000-0000-000000000099"
        assert data["count"] == 1
        assert data["items"][0]["food_name_snapshot"] == "ข้าวสวย"
        assert data["items"][0]["confirmation_status"] == "needs_review"

        item_query, params = next(
            (sql, params) for sql, params in db.calls
            if "FROM meal_items" in sql
        )
        assert "WHERE meal_log_id = :meal_log_id" in item_query
        assert params["meal_log_id"] == "00000000-0000-0000-0000-000000000099"
    finally:
        teardown_db()


class MealItemMutationFakeDB(MealItemFakeDB):
    def __init__(self, owns_meal=True, item_exists=True):
        super().__init__(owns_meal=owns_meal)
        self.item_exists = item_exists
        self.item = {
            "meal_item_id": "00000000-0000-0000-0000-000000000077",
            "meal_log_id": "00000000-0000-0000-0000-000000000099",
            "quantity_unit": "serving",
            "portion_id": None,
        }

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}

        if "revoked_auth_tokens" in sql:
            return Result(row=None)

        if "FROM public.app_users" in sql:
            return Result(row={
                "user_id": USER_ID,
                "email": "meal-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            })

        self.calls.append((sql, params))

        if "FROM meal_logs" in sql and "user_id = :user_id" in sql:
            return Result(row={"meal_log_id": "owned-meal"} if self.owns_meal else None)

        if "FROM meal_items" in sql and sql.lstrip().startswith("SELECT"):
            return Result(row=self.item if self.item_exists else None)

        if sql.lstrip().startswith("UPDATE meal_items"):
            # Simulate RETURNING with unchanged confirmation_status.
            updated = {
                "meal_item_id": params["meal_item_id"],
                "meal_log_id": params["meal_log_id"],
                "food_id": None,
                "food_name_snapshot": params.get("food_name", "ข้าวสวย"),
                "preparation_state_snapshot": params.get("preparation_state"),
                "quantity_value": params.get("quantity_value", 1),
                "quantity_unit": params.get("quantity_unit", "serving"),
                "weight_g": params.get("weight_g"),
                "volume_ml": params.get("volume_ml"),
                "portion_id": None,
                "entry_source": "manual",
                "confirmation_status": "needs_review",
                "source_confidence": None,
                "notes": params.get("notes"),
                "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
            }
            return Result(row=updated)

        if sql.lstrip().startswith("DELETE FROM meal_items"):
            return Result(
                row={"meal_item_id": params["meal_item_id"]}
                if self.item_exists else None
            )

        raise AssertionError("Unexpected SQL: " + sql)


def test_update_meal_item_requires_owned_meal():
    db = MealItemMutationFakeDB(owns_meal=False)
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/meals/00000000-0000-0000-0000-000000000099/items/"
                "00000000-0000-0000-0000-000000000077",
                headers=auth_headers(),
                json={"quantity_value": 2},
            )

        assert response.status_code == 404
        assert not any(
            sql.lstrip().startswith("UPDATE meal_items")
            for sql, _ in db.calls
        )
        assert not db.committed
    finally:
        teardown_db()


def test_update_meal_item_keeps_confirmation_status_unchanged():
    db = MealItemMutationFakeDB()
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/meals/00000000-0000-0000-0000-000000000099/items/"
                "00000000-0000-0000-0000-000000000077",
                headers=auth_headers(),
                json={"quantity_value": 2},
            )

        assert response.status_code == 200
        item = response.json()["item"]
        assert item["quantity_value"] == 2
        assert item["confirmation_status"] == "needs_review"
        sql, params = next(
            (sql, params) for sql, params in db.calls
            if sql.lstrip().startswith("UPDATE meal_items")
        )
        # Check only the UPDATE SET clause; RETURNING may include the status.
        set_clause = sql.split("WHERE", 1)[0].split("SET", 1)[1]
        assert "confirmation_status" not in set_clause
        assert params["quantity_value"] == 2
        assert db.committed
    finally:
        teardown_db()


def test_update_meal_item_rejects_forbidden_fields():
    db = MealItemMutationFakeDB()
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/meals/00000000-0000-0000-0000-000000000099/items/"
                "00000000-0000-0000-0000-000000000077",
                headers=auth_headers(),
                json={"confirmation_status": "user_confirmed"},
            )

        assert response.status_code == 422
        assert not any(
            sql.lstrip().startswith("UPDATE meal_items")
            for sql, _ in db.calls
        )
    finally:
        teardown_db()


def test_delete_meal_item_requires_owned_meal():
    db = MealItemMutationFakeDB(owns_meal=False)
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.delete(
                "/meals/00000000-0000-0000-0000-000000000099/items/"
                "00000000-0000-0000-0000-000000000077",
                headers=auth_headers(),
            )

        assert response.status_code == 404
        assert not any(
            sql.lstrip().startswith("DELETE FROM meal_items")
            for sql, _ in db.calls
        )
        assert not db.committed
    finally:
        teardown_db()


def test_delete_meal_item_for_owned_meal():
    db = MealItemMutationFakeDB()
    setup_db(db)
    try:
        with TestClient(app) as client:
            response = client.delete(
                "/meals/00000000-0000-0000-0000-000000000099/items/"
                "00000000-0000-0000-0000-000000000077",
                headers=auth_headers(),
            )

        assert response.status_code == 204
        assert any(
            sql.lstrip().startswith("DELETE FROM meal_items")
            for sql, _ in db.calls
        )
        assert db.committed
    finally:
        teardown_db()
