import json
from io import BytesIO

import pytest

from app.services import ai_chat


class FakeHTTPResponse:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.data if size < 0 else self.data[:size]


def test_rejects_empty_message():
    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("gemini", "   ")

    assert error.value.status_code == 422


def test_rejects_message_over_limit():
    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("gemini", "a" * (ai_chat.MAX_MESSAGE_LENGTH + 1))

    assert error.value.status_code == 422


def test_rejects_unknown_provider():
    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("other", "Hello")

    assert error.value.status_code == 422


def test_gemini_requires_api_key(monkeypatch):
    monkeypatch.delenv("NOURIVAAI_GEMINI_API_KEY", raising=False)

    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("gemini", "Hello")

    assert error.value.status_code == 503


def test_openai_requires_api_key(monkeypatch):
    monkeypatch.delenv("NOURIVAAI_OPENAI_API_KEY", raising=False)

    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("openai", "Hello")

    assert error.value.status_code == 503


def test_gemini_sends_only_explicit_message(monkeypatch):
    monkeypatch.setenv("NOURIVAAI_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("NOURIVAAI_GEMINI_MODEL", "test-gemini-model")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeHTTPResponse({
            "candidates": [{
                "content": {
                    "parts": [{"text": "สวัสดีค่ะ"}]
                }
            }]
        })

    monkeypatch.setattr(ai_chat, "urlopen", fake_urlopen)

    result = ai_chat.chat("gemini", "ช่วยอธิบายโปรเจกต์")

    assert result == {
        "provider": "gemini",
        "model": "test-gemini-model",
        "message": "สวัสดีค่ะ",
    }
    assert captured["payload"] == {
        "contents": [{
            "role": "user",
            "parts": [{"text": "ช่วยอธิบายโปรเจกต์"}],
        }]
    }
    assert captured["headers"]["X-goog-api-key"] == "test-key"
    assert captured["timeout"] == ai_chat.PROVIDER_TIMEOUT_SECONDS


def test_openai_sends_only_explicit_message(monkeypatch):
    monkeypatch.setenv("NOURIVAAI_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("NOURIVAAI_OPENAI_MODEL", "test-openai-model")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "choices": [{
                "message": {"content": "คำตอบทดสอบ"}
            }]
        })

    monkeypatch.setattr(ai_chat, "urlopen", fake_urlopen)

    result = ai_chat.chat("openai", "ทดสอบ")

    assert result == {
        "provider": "openai",
        "model": "test-openai-model",
        "message": "คำตอบทดสอบ",
    }
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["payload"] == {
        "model": "test-openai-model",
        "messages": [{"role": "user", "content": "ทดสอบ"}],
    }


def test_provider_does_not_silently_fallback(monkeypatch):
    monkeypatch.delenv("NOURIVAAI_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("NOURIVAAI_OPENAI_API_KEY", "test-key")

    with pytest.raises(ai_chat.AIChatError):
        ai_chat.chat("gemini", "Hello")


def test_rejects_invalid_gemini_response(monkeypatch):
    monkeypatch.setenv("NOURIVAAI_GEMINI_API_KEY", "test-key")

    monkeypatch.setattr(
        ai_chat,
        "urlopen",
        lambda *args, **kwargs: FakeHTTPResponse({"unexpected": True}),
    )

    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("gemini", "Hello")

    assert error.value.status_code == 502


def test_gemini_quota_error_does_not_retry(monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setenv("NOURIVAAI_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("NOURIVAAI_GEMINI_MODEL", "test-model")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            request.full_url, 429, "Too Many Requests",
            {}, BytesIO(b'{"error":{"message":"quota exceeded"}}')
        )

    monkeypatch.setattr(ai_chat, "urlopen", fake_urlopen)

    with pytest.raises(ai_chat.AIChatError) as error:
        ai_chat.chat("gemini", "ทดสอบ")

    assert error.value.status_code == 503
    assert "โควตา" in str(error.value)
    assert len(calls) == 1


def test_gemini_service_unavailable_retries_once(monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setenv("NOURIVAAI_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("NOURIVAAI_GEMINI_MODEL", "test-model")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(
            request.full_url, 503, "Service Unavailable",
            {}, BytesIO(b'{"error":{"message":"temporarily unavailable"}}')
        )

    monkeypatch.setattr(ai_chat, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda _: None)

    with pytest.raises(ai_chat.AIChatError):
        ai_chat.chat("gemini", "ทดสอบ")

    assert len(calls) == 2
