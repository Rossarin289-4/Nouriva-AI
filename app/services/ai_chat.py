"""Provider adapters for NourivaAI text chat.

Only the user's explicit message is sent to the selected provider.
No profile, meal history, or other health data is attached automatically.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROVIDER_TIMEOUT_SECONDS = 30
MAX_MESSAGE_LENGTH = 4000
MAX_RESPONSE_BYTES = 1_000_000


class AIChatError(Exception):
    """Safe, user-facing AI chat error."""

    def __init__(self, message, status_code=503):
        super().__init__(message)
        self.status_code = status_code


def _read_json_response(response):
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AIChatError("ผลลัพธ์จาก AI มีขนาดใหญ่เกินไป", 502)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AIChatError("ไม่สามารถอ่านผลลัพธ์จาก AI ได้", 502) from error

    if not isinstance(payload, dict):
        raise AIChatError("รูปแบบผลลัพธ์จาก AI ไม่ถูกต้อง", 502)

    return payload


def _post_json(url, api_key, payload, *, key_header="Authorization",
               key_prefix="Bearer"):
    if not url.startswith("https://"):
        raise AIChatError("การเชื่อมต่อ AI ต้องใช้ HTTPS", 503)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    headers[key_header] = f"{key_prefix} {api_key}".strip()

    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
                return _read_json_response(response)

        except HTTPError as error:
            if error.code == 429:
                error.close()
                raise AIChatError(
                    "Gemini ใช้โควตาถึงขีดจำกัดแล้ว กรุณารอสักครู่ "
                    "หรือกลับมาใช้งานภายหลัง",
                    503,
                ) from error

            if error.code == 503 and attempt < max_retries:
                import time
                print(
                    f"[AI Chat] Provider returned HTTP {error.code}; "
                    "retrying once after 1 second",
                    flush=True,
                )
                error.close()
                time.sleep(1)
                continue

            error.close()
            print(
                f"[AI Chat] Provider HTTP error: status={error.code}",
                flush=True,
            )

            status = 503 if error.code == 429 or error.code >= 500 else 502
            raise AIChatError(
                f"ผู้ให้บริการ AI ไม่พร้อมใช้งาน (HTTP {error.code})",
                status,
            ) from error

        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            reason = getattr(error, "reason", error)
            is_timeout = (
                isinstance(error, TimeoutError)
                or "timed out" in str(reason).lower()
                or "timeout" in str(reason).lower()
            )

            if is_timeout:
                print(
                    "[AI Chat] Provider request timed out; "
                    "not retrying to avoid duplicate processing",
                    flush=True,
                )
                raise AIChatError(
                    "คำขอใช้เวลานานเกินไป อาจมีการประมวลผลที่ผู้ให้บริการแล้ว "
                    "โปรดตรวจสอบก่อนส่งข้อความเดิมซ้ำ",
                    503,
                ) from error

            print(
                f"[AI Chat] Connection error: "
                f"type={type(error).__name__}",
                flush=True,
            )
            raise AIChatError(
                "เชื่อมต่อผู้ให้บริการ AI ไม่สำเร็จ", 503
            ) from error

    raise AIChatError("เชื่อมต่อผู้ให้บริการ AI ไม่สำเร็จ", 503)

def _validate_message(message):
    if not isinstance(message, str):
        raise AIChatError("ข้อความไม่ถูกต้อง", 422)

    message = message.strip()
    if not message:
        raise AIChatError("กรุณาพิมพ์ข้อความก่อนส่ง", 422)
    if len(message) > MAX_MESSAGE_LENGTH:
        raise AIChatError(
            f"ข้อความต้องมีความยาวไม่เกิน {MAX_MESSAGE_LENGTH} ตัวอักษร",
            422,
        )

    return message


def _extract_gemini_text(payload):
    try:
        candidates = payload["candidates"]
        parts = candidates[0]["content"]["parts"]
        text = "".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
    except (KeyError, IndexError, TypeError) as error:
        raise AIChatError("ผู้ให้บริการ AI ส่งผลลัพธ์ไม่ครบถ้วน", 502) from error

    if not text:
        raise AIChatError("AI ไม่ได้ส่งข้อความตอบกลับ", 502)

    return text


def _extract_openai_text(payload):
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise AIChatError("ผู้ให้บริการ AI ส่งผลลัพธ์ไม่ครบถ้วน", 502) from error

    if not isinstance(text, str) or not text.strip():
        raise AIChatError("AI ไม่ได้ส่งข้อความตอบกลับ", 502)

    return text.strip()


def chat(provider, message):
    """Send one explicit user message to the selected configured provider."""
    message = _validate_message(message)

    if provider == "gemini":
        api_key = os.getenv("NOURIVAAI_GEMINI_API_KEY", "").strip()
        model = os.getenv(
            "NOURIVAAI_GEMINI_MODEL", "gemini-2.5-flash"
        ).strip()

        if not api_key or not model:
            raise AIChatError("Gemini ยังไม่ได้ตั้งค่า API key หรือ model", 503)

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": message}],
                }
            ],
        }
        result = _post_json(
            url,
            api_key,
            payload,
            key_header="x-goog-api-key",
            key_prefix="",
        )
        return {
            "provider": "gemini",
            "model": model,
            "message": _extract_gemini_text(result),
        }

    if provider == "openai":
        api_key = os.getenv("NOURIVAAI_OPENAI_API_KEY", "").strip()
        model = os.getenv(
            "NOURIVAAI_OPENAI_MODEL", "gpt-4.1-mini"
        ).strip()

        if not api_key or not model:
            raise AIChatError("OpenAI ยังไม่ได้ตั้งค่า API key หรือ model", 503)

        result = _post_json(
            "https://api.openai.com/v1/chat/completions",
            api_key,
            {
                "model": model,
                "messages": [{"role": "user", "content": message}],
            },
        )
        return {
            "provider": "openai",
            "model": model,
            "message": _extract_openai_text(result),
        }

    raise AIChatError("ไม่รองรับ provider ที่เลือก", 422)
