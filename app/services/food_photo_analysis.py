"""Provider-backed food photo identification.

Images are sent to the configured provider only after explicit user consent.
The provider is never asked for nutrition values; its output is a proposal and
must not be used as verified food or nutrition data.
"""

import base64
import json
import math
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}
PROVIDER_TIMEOUT_SECONDS = 30


class FoodImageAnalysisUnavailable(Exception):
    """Raised when analysis cannot safely be completed."""

    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def detect_image_type(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validated_response(content):
    try:
        result = json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise FoodImageAnalysisUnavailable(
            "บริการวิเคราะห์ภาพส่งผลลัพธ์ที่อ่านไม่ได้", 502
        ) from error

    if not isinstance(result, dict):
        raise FoodImageAnalysisUnavailable("ผลวิเคราะห์ภาพไม่ถูกต้อง", 502)

    name = result.get("food_name")
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 160):
        name = None

    components = result.get("components", [])
    if not isinstance(components, list):
        components = []
    components = [
        value.strip()[:120]
        for value in components[:20]
        if isinstance(value, str) and value.strip()
    ]

    confidence = result.get("identification_confidence")
    if confidence not in ("low", "medium", "high"):
        confidence = "unknown"

    estimate = result.get("portion_estimate")
    portion = None
    if isinstance(estimate, dict):
        value = estimate.get("value")
        unit = estimate.get("unit")
        portion_confidence = estimate.get("confidence")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
            and unit in ("g", "ml", "piece")
        ):
            portion = {
                "value": value,
                "unit": unit,
                "confidence": (
                    portion_confidence
                    if portion_confidence in ("low", "medium", "high")
                    else "unknown"
                ),
            }

    if name is None and not components:
        raise FoodImageAnalysisUnavailable(
            "ยังระบุอาหารจากภาพนี้ไม่ได้ กรุณาลองภาพอื่นหรือค้นหาชื่ออาหาร", 422
        )

    return {
        "status": "proposed",
        "food_identification": {
            "name": name,
            "components": components,
            "confidence": confidence,
            "confirmation_status": "user_confirmation_required",
        },
        "portion_estimate": portion,
        "nutrition": {
            "status": "not_calculated",
            "reason": "ผลระบุอาหารจากภาพยังไม่ใช่ข้อมูลโภชนาการที่ผ่านการตรวจสอบ",
        },
        "limitations": [
            "ผลจากภาพเป็นข้อเสนอจาก AI ต้องตรวจสอบและยืนยันด้วยตนเอง",
            "ความมั่นใจในการระบุภาพไม่ใช่ความถูกต้องของข้อมูลโภชนาการ",
            "ไม่มีการคำนวณสารอาหารจากภาพนี้",
        ],
    }


class FoodImageProvider(Protocol):
    """Interface for a provider that returns identification proposals only."""

    def analyze(self, content, content_type):
        ...


class OpenAICompatibleFoodImageProvider:
    def __init__(self, api_key, model, endpoint):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint

    def analyze(self, content, content_type):
        data_url = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
        provider_payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Identify only foods visibly supported by the image. Do not diagnose, "
                        "recommend treatment, or provide any nutrition or calorie values. "
                        "Return JSON with food_name (string or null), components (string array), "
                        "identification_confidence (low|medium|high|unknown), and "
                        "portion_estimate (object with positive value, unit g|ml|piece, and "
                        "confidence low|medium|high|unknown, or null). Use null when uncertain."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "ช่วยระบุอาหารที่มองเห็นในภาพนี้"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        request = Request(
            self.endpoint,
            data=json.dumps(provider_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
                provider_result = json.loads(response.read(1_000_001).decode("utf-8"))
        except HTTPError as error:
            status = 503 if error.code == 429 or error.code >= 500 else 502
            raise FoodImageAnalysisUnavailable(
                "ผู้ให้บริการวิเคราะห์ภาพไม่พร้อมใช้งาน", status
            ) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise FoodImageAnalysisUnavailable(
                "เชื่อมต่อผู้ให้บริการวิเคราะห์ภาพไม่สำเร็จ", 503
            ) from error

        if len(json.dumps(provider_result)) > 1_000_000:
            raise FoodImageAnalysisUnavailable("ผลลัพธ์จากผู้ให้บริการมีขนาดใหญ่เกินไป", 502)
        try:
            model_content = provider_result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise FoodImageAnalysisUnavailable(
                "ผู้ให้บริการส่งผลลัพธ์ไม่ครบถ้วน", 502
            ) from error
        analysis = _validated_response(model_content)
        analysis["provider"] = "openai_compatible"
        analysis["model"] = self.model
        return analysis


def analyze_food_image(content, content_type):
    """Analyze an image using an explicitly configured OpenAI-compatible API."""
    if not content:
        raise FoodImageAnalysisUnavailable("ไฟล์ภาพว่างเปล่า", 422)
    if len(content) > MAX_IMAGE_BYTES:
        raise FoodImageAnalysisUnavailable("ภาพใหญ่เกินไป (สูงสุด 10 MB)", 413)
    actual_type = detect_image_type(content)
    if actual_type is None or actual_type != content_type:
        raise FoodImageAnalysisUnavailable(
            "ชนิดไฟล์ภาพไม่ถูกต้อง รองรับ JPEG, PNG และ WebP", 415
        )

    provider = os.getenv("NOURIVAAI_FOOD_IMAGE_PROVIDER", "").strip().lower()
    api_key = os.getenv("NOURIVAAI_FOOD_IMAGE_API_KEY", "").strip()
    model = os.getenv("NOURIVAAI_FOOD_IMAGE_MODEL", "").strip()
    endpoint = os.getenv("NOURIVAAI_FOOD_IMAGE_API_URL", "").strip()
    if provider != "openai_compatible" or not api_key or not model or not endpoint:
        raise FoodImageAnalysisUnavailable(
            "บริการวิเคราะห์ภาพยังไม่ได้ตั้งค่า กรุณาใช้ค้นหาชื่ออาหารแทน"
        )
    if not endpoint.startswith("https://"):
        raise FoodImageAnalysisUnavailable("URL ของผู้ให้บริการต้องใช้ HTTPS", 503)
    provider: FoodImageProvider = OpenAICompatibleFoodImageProvider(api_key, model, endpoint)
    return provider.analyze(content, content_type)
