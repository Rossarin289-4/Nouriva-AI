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


def test_external_barcode_rejects_invalid_code_before_lookup(client, monkeypatch):
    test_client, fake_db = client

    def fail_lookup(_barcode):
        raise AssertionError("external lookup must not run")

    monkeypatch.setattr(
        "app.routes.foods.lookup_openfoodfacts_barcode", fail_lookup
    )
    response = test_client.get(
        "/foods/external/openfoodfacts/barcode/invalid"
    )

    assert response.status_code == 422
    assert fake_db.queries == []


def test_external_barcode_returns_unverified_attributed_record(client, monkeypatch):
    test_client, _ = client
    external = {
        "status": "external_unverified",
        "item": {
            "barcode": "8850051006863",
            "name": "External product",
            "verification_status": "external_unverified",
            "nutrition_reference_per_100g": {"proteins_100g": 2.5},
        },
        "source": {
            "source_code": "OPEN_FOOD_FACTS",
            "source_name": "Open Food Facts",
            "license_or_attribution": "ODbL",
        },
    }
    monkeypatch.setattr(
        "app.routes.foods.lookup_openfoodfacts_barcode",
        lambda barcode: external if barcode == "8850051006863" else None,
    )

    response = test_client.get(
        "/foods/external/openfoodfacts/barcode/8850051006863"
    )

    assert response.status_code == 200
    assert response.json() == external


def test_external_barcode_not_found_returns_404(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(
        "app.routes.foods.lookup_openfoodfacts_barcode", lambda _barcode: None
    )

    response = test_client.get(
        "/foods/external/openfoodfacts/barcode/8850051006863"
    )

    assert response.status_code == 404


def test_external_barcode_failure_returns_503(client, monkeypatch):
    test_client, _ = client

    def fail_lookup(_barcode):
        from app.services.openfoodfacts import OpenFoodFactsUnavailable
        raise OpenFoodFactsUnavailable("external unavailable")

    monkeypatch.setattr(
        "app.routes.foods.lookup_openfoodfacts_barcode", fail_lookup
    )
    response = test_client.get(
        "/foods/external/openfoodfacts/barcode/8850051006863"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "external unavailable"


def test_openfoodfacts_lookup_without_user_agent_stops_before_network(monkeypatch):
    from app.services import openfoodfacts
    from app.services.openfoodfacts import OpenFoodFactsUnavailable

    monkeypatch.delenv("NOURIVAAI_OPENFOODFACTS_USER_AGENT", raising=False)
    openfoodfacts._cache.clear()

    def network_must_not_run(*_args, **_kwargs):
        raise AssertionError("lookup must stop before sending a request")

    monkeypatch.setattr(openfoodfacts, "urlopen", network_must_not_run)
    with pytest.raises(OpenFoodFactsUnavailable, match="ยังไม่ได้ตั้งค่า User-Agent"):
        openfoodfacts.lookup_barcode("3017620422003")


def test_openfoodfacts_lookup_uses_timeout_user_agent_and_keeps_unverified_data(
    monkeypatch,
):
    import json
    from app.services import openfoodfacts

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "status": "success",
                "product": {
                    "code": "8850051006863",
                    "product_name": "Test product",
                    "brands": "Test brand",
                    "quantity": "250 g",
                    "image_url": "https://images.example/product.jpg",
                    "nutriments": {
                        "proteins_100g": 4.2,
                        "energy-kcal_100g": 120,
                        "missing_100g": None,
                    },
                },
            }).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv(
        "NOURIVAAI_OPENFOODFACTS_USER_AGENT",
        "NourivaAI/0.1 (contact@example.org)",
    )
    monkeypatch.setattr(openfoodfacts, "urlopen", fake_urlopen)
    openfoodfacts._cache.clear()

    result = openfoodfacts.lookup_barcode("8850051006863")

    assert captured["timeout"] == openfoodfacts.TIMEOUT_SECONDS
    assert "/api/v3/product/" in captured["request"].full_url
    assert captured["request"].get_header("User-agent") == (
        "NourivaAI/0.1 (contact@example.org)"
    )
    assert result["status"] == "external_unverified"
    assert result["item"]["name"] == "Test product"
    assert result["item"]["nutrition_reference_per_100g"] == {
        "energy-kcal_100g": 120,
        "proteins_100g": 4.2,
    }
    assert result["source"]["source_code"] == "OPEN_FOOD_FACTS"
    assert result["source"]["fetched_at"]
    openfoodfacts._cache.clear()


class MockOffResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def _mock_off_lookup(monkeypatch, body_or_error):
    import json
    from app.services import openfoodfacts

    monkeypatch.setenv("NOURIVAAI_OPENFOODFACTS_USER_AGENT", "test-agent")
    openfoodfacts._cache.clear()
    if isinstance(body_or_error, Exception):
        def fake_urlopen(*_args, **_kwargs):
            raise body_or_error
    else:
        body = body_or_error
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")

        def fake_urlopen(*_args, **_kwargs):
            return MockOffResponse(body)

    monkeypatch.setattr(openfoodfacts, "urlopen", fake_urlopen)
    return openfoodfacts


def test_openfoodfacts_v3_success_with_product_is_unverified(monkeypatch):
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(monkeypatch, {
        "status": "success",
        "product": {"code": "3017620422003", "product_name": "Nutella"},
    })

    result = lookup_barcode("3017620422003")

    assert result["item"]["name"] == "Nutella"
    assert result["status"] == "external_unverified"
    assert result["item"]["verification_status"] == "external_unverified"
    assert result["item"]["nutrition_reference_per_100g"] == {}
    service._cache.clear()


def test_openfoodfacts_maps_complete_nutrition_data_without_unit_conflation(
    monkeypatch,
):
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(monkeypatch, {
        "status": "success",
        "product": {
            "code": "3017620422003",
            "product_name": "Nutella",
            "nutrition_data_per": "100g",
            "nutriments": {
                "energy-kcal_100g": 539,
                "energy-kcal_unit": "kcal",
                "energy-kj_100g": 2252,
                "energy-kj_unit": "kJ",
                "fat_100g": 30.9,
                "fat_unit": "g",
                "saturated-fat_100g": 10.6,
                "saturated-fat_unit": "g",
                "carbohydrates_100g": 57.5,
                "carbohydrates_unit": "g",
                "sugars_100g": 56.3,
                "sugars_unit": "g",
                "proteins_100g": 6.3,
                "proteins_unit": "g",
                "fiber_100g": 0,
                "fiber_unit": "g",
                "salt_100g": 0.107,
                "salt_unit": "g",
                "sodium_100g": 0.0428,
                "sodium_unit": "g",
            },
        },
    })

    result = lookup_barcode("3017620422003")

    assert result["item"]["nutrition_reference_per_100g"] == {
        "energy-kcal_100g": 539,
        "energy-kj_100g": 2252,
        "fat_100g": 30.9,
        "saturated-fat_100g": 10.6,
        "carbohydrates_100g": 57.5,
        "sugars_100g": 56.3,
        "proteins_100g": 6.3,
        "fiber_100g": 0,
        "salt_100g": 0.107,
        "sodium_100g": 0.0428,
    }
    assert result["item"]["verification_status"] == "external_unverified"
    assert result["status"] == "external_unverified"
    assert result["source"]["source_url"].endswith("/3017620422003")
    assert result["source"]["fetched_at"]
    assert "ยังไม่ผ่านการตรวจสอบ" in result["message"]
    service._cache.clear()


def test_openfoodfacts_keeps_only_present_partial_nutrients(monkeypatch):
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(monkeypatch, {
        "status": "success",
        "product": {
            "code": "3017620422003",
            "nutriments": {
                "energy-kcal_100g": 539,
                "fat_100g": 30.9,
                "salt_100g": 0.107,
            },
        },
    })

    result = lookup_barcode("3017620422003")

    assert result["item"]["nutrition_reference_per_100g"] == {
        "energy-kcal_100g": 539,
        "fat_100g": 30.9,
        "salt_100g": 0.107,
    }
    service._cache.clear()


@pytest.mark.parametrize("product_fields", [{}, {"nutriments": None}, {"nutriments": []}])
def test_openfoodfacts_missing_or_non_object_nutriments_returns_empty(
    monkeypatch, product_fields
):
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(monkeypatch, {
        "status": "success",
        "product": {"code": "3017620422003", **product_fields},
    })

    result = lookup_barcode("3017620422003")

    assert result["item"]["nutrition_reference_per_100g"] == {}
    assert result["status"] == "external_unverified"
    service._cache.clear()


def test_openfoodfacts_omits_malformed_nutrient_values(monkeypatch):
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(monkeypatch, {
        "status": "success",
        "product": {
            "code": "3017620422003",
            "nutriments": {
                "energy-kcal_100g": 539,
                "energy-kj_100g": "2252",
                "fat_100g": True,
                "saturated-fat_100g": -1,
                "carbohydrates_100g": float("nan"),
                "sugars_100g": float("inf"),
                "proteins_100g": None,
                "fiber_100g": 0,
                "salt_100g": 0.107,
                "sodium_100g": -0.1,
            },
        },
    })

    result = lookup_barcode("3017620422003")

    assert result["item"]["nutrition_reference_per_100g"] == {
        "energy-kcal_100g": 539,
        "fiber_100g": 0,
        "salt_100g": 0.107,
    }
    service._cache.clear()


def test_openfoodfacts_http_404_is_not_found(monkeypatch):
    from urllib.error import HTTPError
    from app.services.openfoodfacts import lookup_barcode

    service = _mock_off_lookup(
        monkeypatch,
        HTTPError("https://example.invalid", 404, "Not Found", None, None),
    )
    assert lookup_barcode("3017620422003") is None
    service._cache.clear()


@pytest.mark.parametrize("status_code", [400, 429, 500, 503])
def test_openfoodfacts_http_errors_are_not_reported_as_not_found(
    monkeypatch, status_code
):
    from urllib.error import HTTPError
    from app.services.openfoodfacts import OpenFoodFactsUnavailable, lookup_barcode

    service = _mock_off_lookup(
        monkeypatch,
        HTTPError("https://example.invalid", status_code, "upstream error", None, None),
    )
    with pytest.raises(OpenFoodFactsUnavailable) as caught:
        lookup_barcode("3017620422003")
    expected_status = 503 if status_code == 429 or status_code >= 500 else 502
    assert caught.value.status_code == expected_status
    assert f"HTTP {status_code}" in str(caught.value)
    service._cache.clear()


def test_openfoodfacts_timeout_and_network_errors_are_distinguished(monkeypatch):
    from urllib.error import URLError
    from app.services.openfoodfacts import OpenFoodFactsUnavailable, lookup_barcode

    for timeout_error in (TimeoutError("timeout"), URLError(TimeoutError("timeout"))):
        service = _mock_off_lookup(monkeypatch, timeout_error)
        with pytest.raises(OpenFoodFactsUnavailable) as caught_timeout:
            lookup_barcode("3017620422003")
        assert caught_timeout.value.status_code == 504
        service._cache.clear()

    service = _mock_off_lookup(monkeypatch, URLError("network unavailable"))
    with pytest.raises(OpenFoodFactsUnavailable) as network_error:
        lookup_barcode("3017620422003")
    assert network_error.value.status_code == 503
    service._cache.clear()


def test_openfoodfacts_invalid_json_and_invalid_payload_are_upstream_errors(
    monkeypatch,
):
    from app.services.openfoodfacts import OpenFoodFactsUnavailable, lookup_barcode

    service = _mock_off_lookup(monkeypatch, b"not-json")
    with pytest.raises(OpenFoodFactsUnavailable) as json_error:
        lookup_barcode("3017620422003")
    assert json_error.value.status_code == 502
    service._cache.clear()

    service = _mock_off_lookup(monkeypatch, {"status": "failure"})
    with pytest.raises(OpenFoodFactsUnavailable) as payload_error:
        lookup_barcode("3017620422003")
    assert payload_error.value.status_code == 502
    service._cache.clear()


def test_external_route_preserves_upstream_error_status(client, monkeypatch):
    from app.services.openfoodfacts import OpenFoodFactsUnavailable

    test_client, _ = client
    monkeypatch.setattr(
        "app.routes.foods.lookup_openfoodfacts_barcode",
        lambda _barcode: (_ for _ in ()).throw(
            OpenFoodFactsUnavailable("upstream timeout", 504)
        ),
    )
    response = test_client.get(
        "/foods/external/openfoodfacts/barcode/3017620422003"
    )
    assert response.status_code == 504
    assert response.json()["detail"] == "upstream timeout"
