"""Pluggable provider layer for the recommendation runner.

Each provider exposes the same call shape and returns the same envelope, so the
runner never contains provider-specific logic. Providers are enabled
independently, because API keys and billing arrive at different times.

Deliberate choices worth knowing about:

Every provider gets the same plain-text prompt and the same parser. None of them
use native structured output, tool calling or response schemas. Those are three
different machines that shape output in provider-specific ways, and a comparison
between conditions has to hold the machinery identical or it is measuring the
machinery. The cost is more malformed responses, which are recorded rather than
retried into submission.

Temperature is 1.0 everywhere. That is both the documented default for all three
providers and the same number, which is a rare coincidence worth using. It also
matters for the stability measure: at temperature 0 the three samples would be
near copies and stability would describe API determinism rather than the model.

sent_parameters records what was actually transmitted, per provider, because
some models reject an explicit temperature and the honest record is what went
over the wire rather than what was intended.
"""

import json
import time
import urllib.error
import urllib.request

from config import optional

TIMEOUT_SECONDS = 120
MAX_ATTEMPTS = 4
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """Raised when a call fails in a way retrying will not fix."""


def _post(url, payload, headers):
    """POST JSON and return (status, body_text). Network errors raise."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", errors="replace")


def _post_with_retry(url, payload, headers):
    """Retry only on statuses that plausibly clear on their own.

    Backoff is deliberately generous. A rate limit hit at speed across 1890
    calls will otherwise burn the whole budget on 429s.
    """
    delay = 2.0
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, body = _post(url, payload, headers)
        if status == 200:
            return body
        last = (status, body)
        if status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
            break
        time.sleep(delay)
        delay *= 2
    raise ProviderError(f"HTTP {last[0]}: {last[1][:400]}")


class AnthropicProvider:
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"

    def __init__(self, model_id, temperature=1.0, max_tokens=8192):
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

    def available(self):
        return optional(self.key_env) is not None

    def complete(self, prompt):
        payload = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = _post_with_retry(
            "https://api.anthropic.com/v1/messages",
            payload,
            {"x-api-key": optional(self.key_env), "anthropic-version": "2023-06-01"},
        )
        raw = json.loads(body)
        text = "".join(
            block.get("text", "") for block in raw.get("content", [])
            if block.get("type") == "text"
        )
        return {
            "text": text,
            "raw": raw,
            "usage": raw.get("usage", {}),
            "sent_parameters": {"temperature": self.temperature,
                                "max_tokens": self.max_tokens},
        }


class OpenAIProvider:
    name = "openai"
    key_env = "OPENAI_API_KEY"

    def __init__(self, model_id, temperature=1.0, max_tokens=8192):
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

    def available(self):
        return optional(self.key_env) is not None

    def complete(self, prompt):
        # Newer OpenAI reasoning models reject an explicit temperature and only
        # accept their default, which is 1.0. Omitting it therefore produces the
        # same sampling behaviour we asked for, and sent_parameters records that
        # the field was not transmitted rather than pretending it was.
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": self.max_tokens,
        }
        sent = {"temperature": "omitted, provider default is 1.0",
                "max_completion_tokens": self.max_tokens}
        body = _post_with_retry(
            "https://api.openai.com/v1/chat/completions",
            payload,
            {"Authorization": f"Bearer {optional(self.key_env)}"},
        )
        raw = json.loads(body)
        choices = raw.get("choices", [])
        text = choices[0]["message"].get("content", "") if choices else ""
        return {"text": text or "", "raw": raw,
                "usage": raw.get("usage", {}), "sent_parameters": sent}


class GeminiProvider:
    name = "gemini"
    key_env = "GEMINI_API_KEY"

    def __init__(self, model_id, temperature=1.0, max_tokens=8192):
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

    def available(self):
        return optional(self.key_env) is not None

    def complete(self, prompt):
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model_id}:generateContent?key={optional(self.key_env)}")
        body = _post_with_retry(url, payload, {})
        raw = json.loads(body)
        candidates = raw.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        # Gemini interleaves reasoning parts with answer parts and marks the
        # former with thought=true. Including them would corrupt the parse.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return {
            "text": text,
            "raw": raw,
            "usage": raw.get("usageMetadata", {}),
            "sent_parameters": {"temperature": self.temperature,
                                "maxOutputTokens": self.max_tokens},
        }


PROVIDER_CLASSES = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def build(provider_name, model_id, temperature=1.0, max_tokens=8192):
    if provider_name not in PROVIDER_CLASSES:
        raise SystemExit(f"Unknown provider {provider_name}. "
                         f"Known: {sorted(PROVIDER_CLASSES)}")
    return PROVIDER_CLASSES[provider_name](model_id, temperature, max_tokens)
