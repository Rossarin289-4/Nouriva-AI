import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.auth import get_current_user
from app.services import food_photo_analysis as image_service


JPEG = b"\xff\xd8\xff" + b"nouriva-test-image"


@pytest.fixture
def authenticated_client():
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "00000000-0000-0000-0000-000000000021"
    }
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_photo_analysis_requires_explicit_external_processing_consent(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.foods.analyze_food_image",
        lambda *_args: pytest.fail("provider must not be called without consent"),
    )
    response = authenticated_client.post(
        "/foods/image-analysis",
        content=JPEG,
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 400
    assert "ยืนยัน" in response.json()["detail"]


def test_photo_analysis_rejects_unsupported_or_mismatched_image_type(authenticated_client):
    response = authenticated_client.post(
        "/foods/image-analysis",
        content=b"not an image",
        headers={"Content-Type": "image/gif", "X-Food-Image-Consent": "true"},
    )
    assert response.status_code == 415

    mismatch = authenticated_client.post(
        "/foods/image-analysis",
        content=JPEG,
        headers={"Content-Type": "image/png", "X-Food-Image-Consent": "true"},
    )
    assert mismatch.status_code == 415


def test_photo_analysis_rejects_empty_and_oversized_upload(authenticated_client):
    empty = authenticated_client.post(
        "/foods/image-analysis",
        content=b"",
        headers={"Content-Type": "image/jpeg", "X-Food-Image-Consent": "true"},
    )
    assert empty.status_code == 422

    oversized = authenticated_client.post(
        "/foods/image-analysis",
        content=JPEG + b"x" * image_service.MAX_IMAGE_BYTES,
        headers={"Content-Type": "image/jpeg", "X-Food-Image-Consent": "true"},
    )
    assert oversized.status_code == 413


def test_photo_analysis_requires_authentication():
    with TestClient(app) as client:
        response = client.post(
            "/foods/image-analysis",
            content=JPEG,
            headers={"Content-Type": "image/jpeg", "X-Food-Image-Consent": "true"},
        )
    assert response.status_code == 401


def test_photo_analysis_route_forwards_valid_image_only_after_consent(authenticated_client, monkeypatch):
    received = {}

    def fake_analyzer(content, content_type):
        received["content"] = content
        received["content_type"] = content_type
        return {
            "status": "proposed",
            "food_identification": {"name": "ข้าวผัด", "components": [], "confidence": "low"},
            "nutrition": {"status": "not_calculated"},
        }

    monkeypatch.setattr("app.routes.foods.analyze_food_image", fake_analyzer)
    response = authenticated_client.post(
        "/foods/image-analysis",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Food-Image-Consent": "true"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "proposed"
    assert response.json()["nutrition"]["status"] == "not_calculated"
    assert received == {"content": JPEG, "content_type": "image/jpeg"}


def test_unconfigured_image_provider_fails_safely(monkeypatch):
    for name in (
        "NOURIVAAI_FOOD_IMAGE_PROVIDER",
        "NOURIVAAI_FOOD_IMAGE_API_KEY",
        "NOURIVAAI_FOOD_IMAGE_MODEL",
        "NOURIVAAI_FOOD_IMAGE_API_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(image_service.FoodImageAnalysisUnavailable) as error:
        image_service.analyze_food_image(JPEG, "image/jpeg")
    assert error.value.status_code == 503


def test_provider_network_error_returns_safe_unavailable_error(monkeypatch):
    from urllib.error import URLError

    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_API_KEY", "test-only-key")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_MODEL", "vision-test-model")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_API_URL", "https://vision.example.test/v1/chat/completions")
    monkeypatch.setattr(image_service, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("private network detail")))
    with pytest.raises(image_service.FoodImageAnalysisUnavailable) as error:
        image_service.analyze_food_image(JPEG, "image/jpeg")
    assert error.value.status_code == 503
    assert "private network detail" not in str(error.value)


def test_provider_result_is_proposal_and_never_contains_generated_nutrients(monkeypatch):
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_API_KEY", "test-only-key")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_MODEL", "vision-test-model")
    monkeypatch.setenv("NOURIVAAI_FOOD_IMAGE_API_URL", "https://vision.example.test/v1/chat/completions")

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            result = {
                "choices": [{"message": {"content": json.dumps({
                    "food_name": "ข้าวผัด",
                    "components": ["ข้าว", "ไข่"],
                    "identification_confidence": "medium",
                    "portion_estimate": {"value": 180, "unit": "g", "confidence": "low"},
                    "calories": 400,
                })}}]
            }
            return json.dumps(result).encode("utf-8")

    def mocked_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        assert request.full_url == "https://vision.example.test/v1/chat/completions"
        assert timeout == image_service.PROVIDER_TIMEOUT_SECONDS
        assert "Do not diagnose" in payload["messages"][0]["content"]
        assert payload["messages"][1]["content"][1]["type"] == "image_url"
        assert request.get_header("Authorization") == "Bearer test-only-key"
        return MockResponse()

    monkeypatch.setattr(image_service, "urlopen", mocked_urlopen)
    result = image_service.analyze_food_image(JPEG, "image/jpeg")
    assert result["status"] == "proposed"
    assert result["food_identification"]["name"] == "ข้าวผัด"
    assert result["food_identification"]["confidence"] == "medium"
    assert result["portion_estimate"] == {"value": 180, "unit": "g", "confidence": "low"}
    assert result["nutrition"]["status"] == "not_calculated"
    assert "calories" not in result
    assert "calories" not in result["nutrition"]


def test_invalid_provider_payload_is_rejected(monkeypatch):
    with pytest.raises(image_service.FoodImageAnalysisUnavailable) as error:
        image_service._validated_response("not-json")
    assert error.value.status_code == 502

    with pytest.raises(image_service.FoodImageAnalysisUnavailable) as no_food:
        image_service._validated_response(json.dumps({"food_name": None, "components": []}))
    assert no_food.value.status_code == 422

    invalid_portion = image_service._validated_response(json.dumps({
        "food_name": "อาหาร", "components": [], "portion_estimate": {"value": 50, "unit": "serving"}
    }))
    assert invalid_portion["portion_estimate"] is None
