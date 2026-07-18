from __future__ import annotations

import unittest
from typing import Any, Dict
from unittest import mock

from src.agent_core.ai_client import (
    AIClient,
    AIClientError,
    AIUnavailableError,
    _parse_json_object,
    _redact,
)


def _run_context(provider: str = "openai", model: str = "gpt-4.1") -> Dict[str, Any]:
    return {
        "ai_provider": provider,
        "ai_model": model,
        "ai_models": {
            "default": model,
            "openai": {"enabled": True, "api_key_env": "TEST_OPENAI_KEY", "model": model},
            "claude": {"enabled": False, "api_key_env": "TEST_ANTHROPIC_KEY", "model": model},
            "ollama": {"enabled": False, "base_url": "http://localhost:11434", "model": model},
        },
    }


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _openai_payload(content: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> Dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class JsonParsingTests(unittest.TestCase):
    def test_parses_bare_object(self) -> None:
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})

    def test_parses_fenced_object(self) -> None:
        self.assertEqual(_parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_parses_object_with_surrounding_prose(self) -> None:
        self.assertEqual(_parse_json_object('Sure!\n{"a": 1}\nHope that helps.'), {"a": 1})

    def test_returns_none_for_unparseable_text(self) -> None:
        self.assertIsNone(_parse_json_object("not json at all"))

    def test_returns_none_for_json_array(self) -> None:
        # Callers expect an object; a bare array must not be silently accepted.
        self.assertIsNone(_parse_json_object("[1, 2, 3]"))


class AvailabilityTests(unittest.TestCase):
    def test_unavailable_without_credential(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            client = AIClient.from_run_context(_run_context())
            self.assertFalse(client.available)
            with self.assertRaises(AIUnavailableError):
                client.complete_json("sys", "user", purpose="test")

    def test_available_with_credential(self) -> None:
        with mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test-value"}, clear=True):
            self.assertTrue(AIClient.from_run_context(_run_context()).available)

    def test_ollama_available_via_base_url_without_key(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(AIClient.from_run_context(_run_context(provider="ollama")).available)

    def test_missing_provider_section_raises(self) -> None:
        context = _run_context()
        context["ai_provider"] = "nonexistent"
        with self.assertRaises(AIClientError):
            AIClient.from_run_context(context)


class CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict("os.environ", {"TEST_OPENAI_KEY": "sk-test-value"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_successful_call_records_usage_and_cost(self) -> None:
        client = AIClient.from_run_context(_run_context())
        with mock.patch("requests.post", return_value=_FakeResponse(200, _openai_payload('{"ok": true}'))):
            response = client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(response.data, {"ok": True})
        usage = client.usage.as_metadata()
        self.assertEqual(usage["calls"], 1)
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 150)
        self.assertEqual(usage["purposes"], ["wf03"])
        # gpt-4.1 at (2.00, 8.00) per 1M tokens.
        self.assertAlmostEqual(usage["estimated_cost_usd"], 100 / 1e6 * 2.00 + 50 / 1e6 * 8.00, places=8)

    def test_usage_accumulates_across_calls(self) -> None:
        client = AIClient.from_run_context(_run_context())
        with mock.patch("requests.post", return_value=_FakeResponse(200, _openai_payload('{"ok": true}'))):
            client.complete_json("sys", "user", purpose="wf03")
            client.complete_json("sys", "user", purpose="wf04")

        usage = client.usage.as_metadata()
        self.assertEqual(usage["calls"], 2)
        self.assertEqual(usage["total_tokens"], 300)
        self.assertEqual(usage["purposes"], ["wf03", "wf04"])

    def test_retries_on_rate_limit_then_succeeds(self) -> None:
        client = AIClient.from_run_context(_run_context())
        responses = [
            _FakeResponse(429, text="rate limited"),
            _FakeResponse(200, _openai_payload('{"ok": true}')),
        ]
        with mock.patch("requests.post", side_effect=responses) as post, mock.patch("time.sleep"):
            response = client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(response.data, {"ok": True})
        self.assertEqual(post.call_count, 2)

    def test_gives_up_after_three_attempts(self) -> None:
        client = AIClient.from_run_context(_run_context())
        with mock.patch("requests.post", return_value=_FakeResponse(503, text="down")) as post, mock.patch("time.sleep"):
            with self.assertRaises(AIClientError):
                client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(post.call_count, 3)

    def test_does_not_retry_permanent_client_error(self) -> None:
        client = AIClient.from_run_context(_run_context())
        with mock.patch("requests.post", return_value=_FakeResponse(401, text="bad key")) as post, mock.patch("time.sleep"):
            with self.assertRaises(AIClientError):
                client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(post.call_count, 1)

    def test_failed_call_does_not_record_usage(self) -> None:
        client = AIClient.from_run_context(_run_context())
        with mock.patch("requests.post", return_value=_FakeResponse(401, text="bad key")), mock.patch("time.sleep"):
            with self.assertRaises(AIClientError):
                client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(client.usage.as_metadata()["calls"], 0)

    def test_anthropic_request_shape_and_usage(self) -> None:
        context = _run_context(provider="claude", model="claude-sonnet-4")
        with mock.patch.dict("os.environ", {"TEST_ANTHROPIC_KEY": "sk-ant-test"}, clear=True):
            client = AIClient.from_run_context(context)
            payload = {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            with mock.patch("requests.post", return_value=_FakeResponse(200, payload)) as post:
                response = client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(response.data, {"ok": True})
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(kwargs["json"]["system"], "sys")
        self.assertEqual(client.usage.as_metadata()["total_tokens"], 15)

    def test_unknown_model_prices_at_zero_without_crashing(self) -> None:
        client = AIClient.from_run_context(_run_context(model="some-unlisted-model"))
        with mock.patch("requests.post", return_value=_FakeResponse(200, _openai_payload('{"ok": true}'))):
            client.complete_json("sys", "user", purpose="wf03")

        self.assertEqual(client.usage.as_metadata()["estimated_cost_usd"], 0.0)

    def test_model_prefix_matching_prices_dated_variants(self) -> None:
        client = AIClient.from_run_context(_run_context(model="gpt-4o-mini-2024-07-18"))
        with mock.patch("requests.post", return_value=_FakeResponse(200, _openai_payload('{"ok": true}'))):
            client.complete_json("sys", "user", purpose="wf03")

        self.assertGreater(client.usage.as_metadata()["estimated_cost_usd"], 0.0)


class RedactionTests(unittest.TestCase):
    def test_masks_api_keys_in_error_text(self) -> None:
        masked = _redact("failed with key sk-abcdef1234567890 attached")
        self.assertNotIn("abcdef1234567890", masked)
        self.assertIn("<redacted>", masked)

    def test_masks_bearer_tokens(self) -> None:
        self.assertNotIn("supersecrettoken123", _redact("Bearer supersecrettoken123"))


if __name__ == "__main__":
    unittest.main()
