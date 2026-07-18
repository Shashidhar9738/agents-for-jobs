from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import requests

from src.agent_core.net import use_system_trust_store


class AIClientError(RuntimeError):
    """Raised when the AI provider is misconfigured or fails permanently."""


class AIUnavailableError(AIClientError):
    """Raised when no usable provider credential is configured.

    Callers treat this as a signal to fall back to deterministic generation
    rather than aborting the run.
    """


# Providers that speak the OpenAI /chat/completions contract.
_OPENAI_COMPATIBLE: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Approximate USD per 1M tokens (input, output). Overridable via a "pricing"
# block in config/ai-models.json so cost reporting stays config-driven.
_DEFAULT_PRICING: Dict[str, Tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (1.00, 5.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek-chat": (0.27, 1.10),
}

_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3  # Spec section 14: external API calls get 3 retries with backoff.
_BACKOFF_BASE_SECONDS = 1.5
_REQUEST_TIMEOUT_SECONDS = 120


@dataclass
class ModelUsage:
    provider: str
    model: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    purposes: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_metadata(self) -> Dict[str, Any]:
        """Shape recorded as model_usage in the Application JSON contract."""
        return {
            "provider": self.provider,
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "purposes": list(self.purposes),
        }


@dataclass
class AIResponse:
    text: str
    data: Dict[str, Any] | None
    purpose: str


class AIClient:
    """Provider-agnostic JSON completion client driven by config/ai-models.json."""

    def __init__(
        self,
        provider: str,
        model: str,
        provider_config: Dict[str, Any],
        pricing: Dict[str, Tuple[float, float]] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._config = provider_config
        self._pricing = pricing or dict(_DEFAULT_PRICING)
        self._api_key = self._resolve_api_key()
        self.usage = ModelUsage(provider=provider, model=model)

    @classmethod
    def from_run_context(cls, run_context: Dict[str, Any]) -> "AIClient":
        ai_models = run_context.get("ai_models")
        if not isinstance(ai_models, dict):
            raise AIClientError("run context is missing the 'ai_models' config block")

        provider = str(run_context.get("ai_provider", "")).strip()
        model = str(run_context.get("ai_model", "")).strip()
        if not provider or not model:
            raise AIClientError("run context is missing ai_provider/ai_model")

        provider_config = ai_models.get(provider)
        if not isinstance(provider_config, dict):
            raise AIClientError(f"ai-models config has no section for provider '{provider}'")

        return cls(
            provider=provider,
            model=model,
            provider_config=provider_config,
            pricing=_load_pricing_overrides(ai_models),
        )

    @property
    def available(self) -> bool:
        """True when this provider can actually be called."""
        if self.provider == "ollama":
            return bool(self._config.get("base_url"))
        return bool(self._api_key)

    def _resolve_api_key(self) -> str:
        api_key_env = self._config.get("api_key_env")
        if not isinstance(api_key_env, str) or not api_key_env:
            return ""
        return os.getenv(api_key_env, "").strip()

    def require_available(self) -> None:
        if self.available:
            return
        api_key_env = self._config.get("api_key_env", "<unset>")
        raise AIUnavailableError(
            f"Provider '{self.provider}' is enabled but no credential was found "
            f"(expected environment variable {api_key_env})"
        )

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        purpose: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> AIResponse:
        """Call the configured provider and parse a JSON object from the reply."""
        self.require_available()

        text, prompt_tokens, completion_tokens = self._dispatch(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        self.usage.calls += 1
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.estimated_cost_usd += self._estimate_cost(prompt_tokens, completion_tokens)
        if purpose not in self.usage.purposes:
            self.usage.purposes.append(purpose)

        return AIResponse(text=text, data=_parse_json_object(text), purpose=purpose)

    def _dispatch(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, int, int]:
        if self.provider in _OPENAI_COMPATIBLE:
            return self._call_openai_compatible(system_prompt, user_prompt, max_tokens, temperature)
        if self.provider == "claude":
            return self._call_anthropic(system_prompt, user_prompt, max_tokens, temperature)
        if self.provider == "gemini":
            return self._call_gemini(system_prompt, user_prompt, max_tokens, temperature)
        if self.provider == "ollama":
            return self._call_ollama(system_prompt, user_prompt, temperature)
        raise AIClientError(f"Unsupported AI provider '{self.provider}'")

    def _base_url(self, fallback: str) -> str:
        configured = self._config.get("base_url")
        if isinstance(configured, str) and configured.strip():
            return configured.strip().rstrip("/")
        return fallback

    def _call_openai_compatible(
        self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float
    ) -> Tuple[str, int, int]:
        url = f"{self._base_url(_OPENAI_COMPATIBLE[self.provider])}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # OpenRouter proxies many models and not all of them accept json_object mode,
        # so it stays configurable. Replies are parsed leniently either way.
        if self._config.get("json_mode", True):
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self.provider == "openrouter":
            headers.update(self._openrouter_attribution())

        body = self._post(url, payload, headers)

        # OpenRouter can report upstream failures inside a 200 response body.
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            raise AIClientError(f"{self.provider} upstream error: {_redact(str(error['message']))[:300]}")

        choices = body.get("choices") or []
        if not choices:
            raise AIClientError(f"{self.provider} returned no choices")
        text = str(choices[0].get("message", {}).get("content", "")).strip()
        usage = body.get("usage") or {}
        return (
            text,
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
        )

    def _openrouter_attribution(self) -> Dict[str, str]:
        """Optional ranking headers OpenRouter uses to attribute traffic."""
        headers: Dict[str, str] = {}
        referer = self._config.get("site_url")
        title = self._config.get("app_name")
        if isinstance(referer, str) and referer.strip():
            headers["HTTP-Referer"] = referer.strip()
        if isinstance(title, str) and title.strip():
            headers["X-Title"] = title.strip()
        return headers

    def _call_anthropic(
        self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float
    ) -> Tuple[str, int, int]:
        url = f"{self._base_url('https://api.anthropic.com/v1')}/messages"
        payload = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = self._post(
            url,
            payload,
            {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
        )

        blocks = body.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
        usage = body.get("usage") or {}
        return (
            text,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )

    def _call_gemini(
        self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float
    ) -> Tuple[str, int, int]:
        base = self._base_url("https://generativelanguage.googleapis.com/v1beta")
        url = f"{base}/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        body = self._post(url, payload, {"x-goog-api-key": self._api_key})

        candidates = body.get("candidates") or []
        if not candidates:
            raise AIClientError("gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        usage = body.get("usageMetadata") or {}
        return (
            text,
            int(usage.get("promptTokenCount", 0)),
            int(usage.get("candidatesTokenCount", 0)),
        )

    def _call_ollama(
        self, system_prompt: str, user_prompt: str, temperature: float
    ) -> Tuple[str, int, int]:
        url = f"{self._base_url('http://localhost:11434')}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": temperature},
            "format": "json",
            "stream": False,
        }
        body = self._post(url, payload, {})

        text = str(body.get("message", {}).get("content", "")).strip()
        # Ollama reports eval counts rather than token usage; fall back to an estimate.
        prompt_tokens = int(body.get("prompt_eval_count", 0)) or _estimate_tokens(system_prompt + user_prompt)
        completion_tokens = int(body.get("eval_count", 0)) or _estimate_tokens(text)
        return text, prompt_tokens, completion_tokens

    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        use_system_trust_store()
        request_headers = {"Content-Type": "application/json", **headers}
        last_error: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    url,
                    headers=request_headers,
                    json=payload,
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise AIClientError(f"{self.provider} returned non-JSON response body") from exc

                # 4xx other than the retryable set are permanent - fail fast.
                if response.status_code not in _RETRY_STATUS:
                    raise AIClientError(
                        f"{self.provider} request failed with HTTP {response.status_code}: "
                        f"{_redact(response.text)[:400]}"
                    )
                last_error = AIClientError(
                    f"{self.provider} returned retryable HTTP {response.status_code}"
                )

            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BACKOFF_BASE_SECONDS ** attempt)

        raise AIClientError(
            f"{self.provider} request failed after {_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        rates = self._pricing.get(self.model)
        if rates is None:
            # Fall back to the longest matching prefix so model date-suffixes still price.
            matches = [key for key in self._pricing if self.model.startswith(key)]
            if matches:
                rates = self._pricing[max(matches, key=len)]
        if rates is None:
            return 0.0
        input_rate, output_rate = rates
        return (prompt_tokens / 1_000_000) * input_rate + (completion_tokens / 1_000_000) * output_rate


def _load_pricing_overrides(ai_models: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    pricing = dict(_DEFAULT_PRICING)
    configured = ai_models.get("pricing")
    if not isinstance(configured, dict):
        return pricing

    for model_name, rates in configured.items():
        if isinstance(rates, dict) and "input" in rates and "output" in rates:
            pricing[model_name] = (float(rates["input"]), float(rates["output"]))
        elif isinstance(rates, list) and len(rates) == 2:
            pricing[model_name] = (float(rates[0]), float(rates[1]))
    return pricing


def _parse_json_object(text: str) -> Dict[str, Any] | None:
    """Extract a JSON object from a model reply, tolerating code fences."""
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _redact(text: str) -> str:
    """Mask anything key-shaped before it reaches logs or exception messages."""
    return re.sub(r"(sk-|key-|Bearer\s+)[A-Za-z0-9_\-]{8,}", r"\1<redacted>", text)
