"""Read-only Open Food Facts barcode lookup.

External records are returned as unverified references and are never persisted
or treated as approved NourivaAI nutrition data.
"""

import json
import math
import os
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


TIMEOUT_SECONDS = 4
CACHE_TTL_SECONDS = 300
CACHE_MAX_ITEMS = 128
_cache = {}
_cache_lock = threading.Lock()
_CACHE_MISS = object()


class OpenFoodFactsUnavailable(Exception):
    """The external lookup could not complete safely."""

    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def _configured_user_agent():
    return os.getenv("NOURIVAAI_OPENFOODFACTS_USER_AGENT", "").strip()


def _cache_get(barcode):
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(barcode)
        if entry and entry[0] > now:
            return entry[1]
        if entry:
            _cache.pop(barcode, None)
    return _CACHE_MISS


def _cache_set(barcode, value):
    now = time.monotonic()
    with _cache_lock:
        expired = [key for key, entry in _cache.items() if entry[0] <= now]
        for key in expired:
            _cache.pop(key, None)
        while len(_cache) >= CACHE_MAX_ITEMS:
            _cache.pop(next(iter(_cache)))
        _cache[barcode] = (now + CACHE_TTL_SECONDS, value)


def lookup_barcode(barcode):
    """Return a small, attributed source record without persisting it."""
    cached = _cache_get(barcode)
    if cached is not _CACHE_MISS:
        return cached

    user_agent = _configured_user_agent()
    if not user_agent:
        raise OpenFoodFactsUnavailable(
            "ยังไม่ได้ตั้งค่า User-Agent สำหรับ Open Food Facts"
        )

    fields = "code,product_name,brands,quantity,image_url,nutriments"
    url = (
        "https://world.openfoodfacts.org/api/v3/product/"
        f"{quote(barcode, safe='')}.json?fields={fields}"
    )
    request = Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            _cache_set(barcode, None)
            return None
        status_code = 503 if error.code == 429 or error.code >= 500 else 502
        raise OpenFoodFactsUnavailable(
            f"Open Food Facts ตอบกลับ HTTP {error.code}", status_code
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise OpenFoodFactsUnavailable(
            "หมดเวลารอการตอบกลับจาก Open Food Facts", 504
        ) from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise OpenFoodFactsUnavailable(
                "หมดเวลารอการตอบกลับจาก Open Food Facts", 504
            ) from error
        raise OpenFoodFactsUnavailable("เชื่อมต่อ Open Food Facts ไม่สำเร็จ") from error
    except OSError as error:
        raise OpenFoodFactsUnavailable("เชื่อมต่อ Open Food Facts ไม่สำเร็จ") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenFoodFactsUnavailable(
            "Open Food Facts ส่งข้อมูล JSON ที่อ่านไม่ได้", 502
        ) from error

    if not isinstance(payload, dict):
        raise OpenFoodFactsUnavailable(
            "Open Food Facts ส่งโครงสร้าง JSON ที่ไม่ถูกต้อง", 502
        )

    status = payload.get("status")
    product = payload.get("product")
    # API v3 uses string statuses; accept the legacy v2 integer status for
    # compatibility with existing integrations and fixtures.
    successful_status = status in ("success", "success_with_warnings") or (
        type(status) is int and status == 1
    )
    if not successful_status or not isinstance(product, dict):
        raise OpenFoodFactsUnavailable(
            "Open Food Facts ส่งสถานะหรือข้อมูลสินค้าไม่ถูกต้อง", 502
        )

    nutriments = product.get("nutriments")
    if not isinstance(nutriments, dict):
        nutriments = {}

    # Open Food Facts documents *_100g values as normalized to standard units:
    # kcal for energy-kcal, kJ for energy-kj, and g for the nutrients below.
    # Do not use *_value or convert between salt/sodium or kcal/kJ here.
    nutrient_fields = (
        "energy-kcal_100g", "energy-kj_100g", "fat_100g",
        "saturated-fat_100g", "carbohydrates_100g", "sugars_100g",
        "proteins_100g", "fiber_100g", "salt_100g", "sodium_100g",
    )
    nutrition_reference = {}
    for key in nutrient_fields:
        value = nutriments.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        try:
            is_finite = math.isfinite(value)
        except OverflowError:
            continue
        if is_finite and value >= 0:
            nutrition_reference[key] = value

    code = str(product.get("code") or barcode)
    result = {
        "item": {
            "barcode": code,
            "external_product_id": code,
            "name": product.get("product_name"),
            "brand_name": product.get("brands"),
            "package_quantity": product.get("quantity"),
            "image_url": product.get("image_url"),
            "nutrition_reference_per_100g": nutrition_reference,
            "verification_status": "external_unverified",
        },
        "source": {
            "source_code": "OPEN_FOOD_FACTS",
            "source_name": "Open Food Facts",
            "source_url": f"https://world.openfoodfacts.org/product/{quote(code, safe='')}",
            "license_or_attribution": (
                "Database: Open Database License (ODbL); contents: Database "
                "Contents License; product images: CC BY-SA. โปรดตรวจเงื่อนไข "
                "และ attribution ก่อนนำข้อมูลไปใช้ซ้ำหรือเผยแพร่"
            ),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "status": "external_unverified",
        "message": (
            "ข้อมูลจากแหล่งภายนอกยังไม่ผ่านการตรวจสอบของ NourivaAI "
            "ใช้เป็นข้อมูลอ้างอิงเท่านั้นและไม่นำไปคำนวณสารอาหาร"
        ),
    }
    _cache_set(barcode, result)
    return result
