"""A local Ollama model for housekeeping only (BL-036): classify, extract_metadata, summarize.

Talks to Ollama's HTTP API (default ``http://localhost:11434``): ``POST /api/generate`` to run,
``GET /api/tags`` for health. Local and free (principle 1); the router refuses it any other task
type because it declares ``task_types``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from core.config import DEFAULT_OLLAMA_MODEL as DEFAULT_MODEL
from core.config import DEFAULT_OLLAMA_URL as DEFAULT_URL
from core.config import Config
from core.providers.models.base import (
    ModelError,
    ModelProvider,
    ModelResult,
    ModelTimeout,
    ProviderState,
    TaskPackage,
    UsageHint,
)

log = logging.getLogger(__name__)

HEALTH_TTL_S = 60.0


class OllamaProvider(ModelProvider):
    name = "ollama"
    task_types = frozenset({"classify", "extract_metadata", "summarize"})

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 120.0,
        clock=time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._clock = clock
        self._state: ProviderState | None = None  # unknown until the first check or run
        self._checked_at: float | None = None
        self.detail: str | None = None

    @classmethod
    def from_config(cls, config: Config) -> OllamaProvider:
        return cls(config.ollama_url, config.ollama_model)

    @property
    def state(self) -> ProviderState:
        """Checked with ``GET /api/tags`` the first time anyone asks."""
        if self._state is None:
            return self.health()
        return self._state

    # -- ModelProvider ------------------------------------------------------------------------

    def run(self, task: TaskPackage) -> ModelResult:
        if task.task_type not in self.task_types:
            raise ModelError(f"ollama only does {sorted(self.task_types)}, not {task.task_type}")
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": task.user,
            "stream": False,
            "options": {"num_predict": task.max_output_tokens},
        }
        if task.system:
            body["system"] = task.system
        t0 = time.monotonic()
        payload = self._request("POST", "/api/generate", body)
        duration_ms = int((time.monotonic() - t0) * 1000)
        text = str(payload.get("response") or "")
        if not text.strip():
            self._state = ProviderState.BROKEN
            raise ModelError(f"ollama returned no text: {str(payload)[:200]}")
        self._state = ProviderState.AVAILABLE
        hint = UsageHint(
            input_tokens=payload.get("prompt_eval_count"),
            output_tokens=payload.get("eval_count"),
        )
        return ModelResult(
            text.strip(), self.name, payload.get("model") or self.model, duration_ms, hint
        )

    def health(self) -> ProviderState:
        """AVAILABLE when Ollama answers ``/api/tags`` and has the model pulled. Cached briefly."""
        now = self._clock()
        if (
            self._state is not None
            and self._checked_at is not None
            and now - self._checked_at < HEALTH_TTL_S
        ):
            return self._state
        try:
            tags = self._request("GET", "/api/tags")
        except ModelError:
            pass  # _request set the state
        else:
            names = {m.get("name") for m in tags.get("models", []) if isinstance(m, dict)}
            if self.model in names or f"{self.model}:latest" in names:
                self._state, self.detail = ProviderState.AVAILABLE, None
            else:
                self._state = ProviderState.DISABLED
                self.detail = f"model {self.model} not pulled; run `ollama pull {self.model}`"
        self._checked_at = now
        assert self._state is not None
        return self._state

    def usage_hint(self) -> UsageHint | None:
        return None

    # -- internals ----------------------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            self._state = ProviderState.BROKEN
            self.detail = f"HTTP {exc.code}: {detail}"
            raise ModelError(f"ollama {path}: HTTP {exc.code} {detail}") from exc
        except TimeoutError as exc:
            self._state = ProviderState.LIMITED
            raise ModelTimeout(f"ollama timed out after {self.timeout_s:.0f}s") from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                self._state = ProviderState.LIMITED
                raise ModelTimeout(f"ollama timed out after {self.timeout_s:.0f}s") from exc
            self._state = ProviderState.DISABLED
            self.detail = f"not running at {self.base_url}"
            raise ModelError(f"ollama is not running at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            self._state = ProviderState.BROKEN
            raise ModelError(f"ollama {path} returned non-JSON") from exc
