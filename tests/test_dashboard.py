from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.routes.auth import get_secret_key

USER_ID = "00000000-0000-0000-0000-000000000021"


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


class DashboardFakeDB:
    def __init__(self, meals=None):
        self.calls = []
        self.meals = meals

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.calls.append((sql, params))

        if "revoked_auth_tokens" in sql:
            return Result()
        if "FROM public.app_users" in sql:
            return Result(row={
                "user_id": USER_ID,
                "email": "dashboard-test@example.com",
                "role": "user",
                "is_active": True,
                "email_verified_at": None,
            })
        if "FROM meal_logs" in sql:
            default_meals = [{
                "meal_log_id": "00000000-0000-0000-0000-000000000099",
                "meal_date": date(2026, 10, 23),
                "meal_type": "lunch",
                "eaten_at": None,
                "title": "มื้อกลางวัน",
                "notes": "บันทึกของฉัน",
                "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
            }]
            return Result(rows=default_meals if self.meals is None else self.meals)
        raise AssertionError("Unexpected SQL: " + sql)

    def close(self):
        pass


def access_token():
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": USER_ID,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        get_secret_key(),
        algorithm="HS256",
    )


def test_dashboard_page_includes_meals_section_and_frontend_script():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        meal_script = client.get("/static/meal-manager.js")
        summary_script = client.get("/static/nutrition-summary.js")
        profile_page = client.get("/my-profile")
        profile_script = client.get("/static/profile.js")

    assert page.status_code == 200
    assert 'id="myMeals"' in page.text
    assert 'id="mealResults"' in page.text
    assert page.text.count('aria-label="เมนูหลัก"') == 1
    assert 'class="primary-navigation"' in page.text
    assert 'href="#home"' in page.text
    assert 'href="#myMeals"' in page.text
    assert 'href="#nutrition-summary"' in page.text
    assert 'href="#nutrition-advisor"' in page.text
    assert 'href="/my-profile"' in page.text
    assert 'id="dashboardRecentMeals"' in page.text
    assert 'id="dashboardMealsMessage"' in page.text
    assert '/static/app.js' in page.text
    assert '/static/meal-manager.js' in page.text
    assert 'id="loginNav"' in page.text
    assert 'id="logoutButton"' in page.text
    assert 'id="profileNav"' in page.text
    assert 'href="#nutrition-summary"' in page.text
    assert 'href="#nutrition-advisor"' in page.text
    assert 'id="nutritionSummaryTitle"' in page.text
    assert 'id="nutritionAdvisorTitle"' in page.text
    assert 'id="nutritionSummaryFilter"' in page.text
    assert 'id="summaryFromDate"' in page.text
    assert 'id="summaryToDate"' in page.text
    assert 'id="summaryReadiness"' in page.text
    assert 'id="summaryMeals"' in page.text
    assert "ยังไม่เปิดใช้งาน AI Advisor" in page.text
    assert script.status_code == 200
    assert 'timeZone: "Asia/Bangkok"' in script.text
    assert 'fetch("/auth/me"' in script.text
    assert 'fetch("/auth/logout"' in script.text
    assert 'window.refreshNutritionSummary' in script.text
    assert 'nouriva:meal-history' in script.text
    assert 'message.textContent = messages[state]' in script.text
    assert 'title.textContent = meal.title' in script.text
    assert 'renderDashboardMeals({ state: "unauthenticated" })' in script.text
    assert '/foods/external/openfoodfacts/barcode/' in script.text
    assert 'textContent = `${label}: ${value}`' in script.text
    assert meal_script.status_code == 200
    assert 'credentials: "same-origin"' in meal_script.text
    assert 'meal_date' in meal_script.text
    assert 'notifyDashboard("success"' in meal_script.text
    assert 'items: data.items.slice(0, 3)' in meal_script.text
    assert 'notifyDashboard(error.status === 401 ? "unauthenticated" : "error")' in meal_script.text
    assert 'method: "PATCH"' in meal_script.text
    assert 'method: "DELETE"' in meal_script.text
    assert '/portions`' in meal_script.text
    assert '/nutrition`' in meal_script.text
    assert 'timeZone: "Asia/Bangkok"' in meal_script.text
    assert 'meal_date: date' in meal_script.text
    assert 'food_id: selectedFood.food_id' in meal_script.text
    assert 'confirmation_status' in meal_script.text
    assert summary_script.status_code == 200
    assert 'credentials: "same-origin"' in summary_script.text
    assert 'api("/rules/NUT-001")' in summary_script.text
    assert 'api(`/meals?limit=${PAGE_SIZE}&offset=${offset}`)' in summary_script.text
    assert 'api(`/meals/${encodeURIComponent(meal.meal_log_id)}/items`)' in summary_script.text
    assert 'data.meal_log_id !== meal.meal_log_id' in summary_script.text
    assert '`${item.quantity_value} ${item.quantity_unit || "ไม่ระบุหน่วย"}`' in summary_script.text
    assert 'api(`/foods/${encodeURIComponent(foodId)}/nutrition`)' in summary_script.text
    assert 'timeZone: "Asia/Bangkok"' in summary_script.text
    assert 'textContent = text' in summary_script.text
    assert 'ยังไม่แสดงยอดสารอาหาร' in summary_script.text
    assert 'basisGroups.size === 1' in summary_script.text
    assert 'item.confirmation_status === "confirmed"' in summary_script.text
    assert 'การยืนยันรายการ:' in summary_script.text
    assert 'nutrition/calculate' not in summary_script.text
    assert profile_page.status_code == 200
    assert 'id="profileForm"' in profile_page.text
    assert profile_script.status_code == 200
    assert 'api("/profile")' in profile_script.text


def test_dashboard_primary_navigation_is_shared_and_responsive():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = (root / "app" / "static" / "index.html").read_text()
    style = (root / "app" / "static" / "style.css").read_text()

    assert page.count('<nav class="primary-navigation"') == 1
    assert 'class="bottom-nav"' not in page
    assert "@media (max-width: 800px)" in style
    assert ".primary-navigation {" in style
    assert "prefers-reduced-motion: reduce" in style


def test_food_diary_create_and_item_fields_have_explicit_labels():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = (root / "app" / "static" / "index.html").read_text()

    for control_id in (
        "newMealDate",
        "newMealType",
        "newMealTime",
        "newMealTitle",
        "newMealNotes",
        "mealItemQuantity",
        "mealItemUnit",
        "mealPortionSelect",
        "mealItemNotes",
    ):
        assert f'<label for="{control_id}"' in page
        assert f'id="{control_id}"' in page


def test_empty_meal_items_show_status_without_changing_existing_api():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (root / "app" / "static" / "meal-manager.js").read_text()
    routes = (root / "app" / "routes" / "meals.py").read_text()

    assert 'if (!Array.isArray(data.items))' in script
    assert 'if (!data.items.length)' in script
    assert 'setMealItemsMessage("มื้อนี้ยังไม่มีรายการอาหาร", "empty")' in script
    assert 'api(`/meals/${encodeURIComponent(meal.meal_log_id)}/items`)' in script
    assert 'data.meal_log_id !== meal.meal_log_id' in script
    assert 'selectedMeal?.meal_log_id !== meal.meal_log_id' in script
    assert 'quantity.textContent = `${item.quantity_value} ${units[item.quantity_unit]' in script
    assert '@router.get("/{meal_log_id}/items")' in routes
    assert '@router.post("/{meal_log_id}/items"' in routes


def test_shared_theme_tokens_load_on_dashboard_login_and_profile():
    with TestClient(app) as client:
        dashboard = client.get("/")
        login = client.get("/login")
        profile = client.get("/my-profile")
        theme = client.get("/static/theme.css")

    for page in (dashboard, login, profile):
        assert page.status_code == 200
        assert '/static/theme.css' in page.text

    assert theme.status_code == 200
    assert "--leaf: #076653" in theme.text
    assert "--canvas: #F8FAF6" in theme.text
    assert "--radius-pill: 9999px" in theme.text
    assert ":focus-visible" in theme.text


def test_dashboard_meals_empty_response_is_preserved_for_empty_summary_state():
    db = DashboardFakeDB(meals=[])
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("nouriva_access_token", access_token())
            response = client.get("/meals?limit=100&offset=0")

        assert response.status_code == 200
        assert response.json()["count"] == 0
        assert response.json()["items"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_nutrition_summary_displays_status_only_and_never_calculates_totals():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "nutrition-summary.js"
    ).read_text()

    assert 'rule.lifecycle_status !== "active"' in script
    assert 'item.confirmation_status !== "confirmed"' in script
    assert 'trustedStatuses.has(foodStatus)' in script
    assert 'trustedStatuses.has(basis.verification_status)' in script
    assert 'source.source_is_active === true' in script
    assert 'if (seen.has(item.meal_item_id)) return false' in script
    assert 'if (!item.food_id || !foodData)' in script
    assert 'item.external_status === "external_unverified"' in script
    assert 'item.external_status !== "external_unverified"' in script
    assert 'ไม่รวมในการคำนวณสารอาหาร' in script
    assert 'basisRows.length > 0' in script
    assert 'fromDate > toDate' in script
    assert 'error.status === 401' in script
    assert 'setMessage(`โหลดสรุปไม่สำเร็จ:' in script
    assert 'nutrition/calculate' not in script
    assert 'calculate-from-food' not in script


def test_barcode_external_food_add_requires_explicit_quantity_and_confirmation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (root / "app" / "static" / "app.js").read_text()

    assert 'appendExternalFoodDiaryAction(result, data, code)' in script
    assert 'quantity.value = "' not in script
    assert 'confirmation.type = "checkbox"' in script
    assert 'confirm_add: true' in script
    assert '/external-items' in script
    assert 'credentials: "same-origin"' in script
    assert 'window.refreshNutritionSummary' in script
    assert 'encodeURIComponent(meal.meal_log_id)}/external-items' in script
    assert 'quantity_value: amount' in script
    assert 'quantity_unit: unit.value' in script


def test_barcode_external_food_form_handles_hidden_required_fields_and_feedback():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()
    action = script.split("function appendExternalFoodDiaryAction", 1)[1].split(
        "// Search the local catalog", 1
    )[0]

    # A required select in the hidden new-meal panel previously prevented the
    # browser from dispatching submit for a selected existing meal.
    assert "form.noValidate = true" in action
    assert action.count('form.addEventListener("submit"') == 1
    assert "กรุณาเลือกมื้ออาหาร" in action
    assert "กรุณาติ๊กยืนยัน" in action
    assert "กรุณาระบุปริมาณมากกว่า 0" in action
    assert "เพิ่มรายการไม่สำเร็จ:" in action
    assert "saved.status !== \"success\" || !saved.item" in action
    assert "form.classList.add(\"hidden\")" in action
    assert "quantity_unit: unit.value" in action
    assert 'String(saved.item.meal_log_id) !== String(meal.meal_log_id)' in action
    assert 'Number(saved.item.quantity_value) !== amount' in action
    assert 'saved.item.quantity_unit !== unit.value' in action
    assert "if (error.responseMismatch)" in action
    assert "พบข้อมูลตอบกลับไม่ตรงกัน" in action


def test_food_search_does_not_treat_user_confirmed_as_catalog_verification():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "app.js"
    ).read_text()

    assert 'const isVerified = ["reviewed", "source_verified"].includes(status)' in script
    assert '"user_confirmed"].includes(status)' not in script


def test_dashboard_meals_api_requires_authentication():
    db = DashboardFakeDB()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.get("/meals?limit=20")

        assert response.status_code == 401
        assert not any("FROM meal_logs" in sql for sql, _ in db.calls)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_dashboard_meals_use_same_origin_cookie_and_authenticated_user_filter():
    db = DashboardFakeDB()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("nouriva_access_token", access_token())
            response = client.get("/meals?limit=20")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["items"][0]["title"] == "มื้อกลางวัน"
        sql, params = next(
            (sql, params) for sql, params in db.calls
            if "FROM meal_logs" in sql
        )
        assert "WHERE user_id = :user_id" in sql
        assert params["user_id"] == USER_ID
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_meal_history_event_handlers_do_not_treat_dom_events_as_pagination():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "meal-manager.js"
    ).read_text()

    assert 'retry.addEventListener("click", () => loadMealHistory())' in script
    assert 'cancel.addEventListener("click", () => loadMealHistory())' in script
    assert '$("mealHistoryDate").addEventListener("change", () => loadMealHistory())' in script
