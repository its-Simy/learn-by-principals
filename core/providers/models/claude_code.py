"""Claude Code on the Pro/Max subscription, via ``claude -p … --output-format json``.

Flags checked against ``claude --help`` and a live run (Claude Code 2.1.302, Oct 17, 2026; the
output is ``tests/fixtures/cli/claude_hi.json``): ``-p/--print`` (the prompt itself arrives on
stdin, see ``cli_base``), ``--output-format json``,
``--tools ""`` (no tools), ``--no-session-persistence``, ``--strict-mcp-config`` and
``--system-prompt``. The last two are always passed: without them the CLI sends its coding-agent
prompt, the user's MCP tool definitions and the git state of the working directory, 17k tokens
on a two-token question; with them, 1.4k (P106). ``--bare`` would cut more but only accepts an
API key, which principle 1 forbids. The CLI has no max-output-tokens flag.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from core.config import Config
from core.providers.models.base import ModelError, ModelRateLimited, TaskPackage, UsageHint
from core.providers.models.cli_base import CLIModelProvider, Completed, classify_failure, limit_hint

# A "successful" result that is only a limit notice, e.g. "Claude AI usage limit reached|1758650400"
LIMIT_NOTICE_RE = re.compile(
    r"^\s*(claude ai usage limit reached|you've hit your (usage )?limit|[^\n]{0,60}limit reached)",
    re.IGNORECASE,
)
EPOCH_RE = re.compile(r"\|(\d{9,11})\b")
# For tasks that bring no persona (health checks, `dev model-test`): a replacement for the CLI's
# default prompt, not an instruction set.
DEFAULT_SYSTEM_PROMPT = "Answer the user directly and briefly."


class ClaudeCodeProvider(CLIModelProvider):
    name = "claude"
    binary = "claude"

    @classmethod
    def from_config(cls, config: Config) -> ClaudeCodeProvider:
        return cls(config.home / "scratch" / "claude", timeout_s=config.model_timeout_s)

    def argv(self, task: TaskPackage) -> list[str]:
        argv = ["-p", "--output-format", "json", "--tools", ""]
        argv += ["--no-session-persistence", "--strict-mcp-config"]
        # Always given, or the CLI's own coding-agent prompt goes out with every call.
        argv += ["--system-prompt", task.system or DEFAULT_SYSTEM_PROMPT]
        return argv

    def stdin_text(self, task: TaskPackage) -> str:
        return task.user

    def parse(self, done: Completed) -> tuple[str, str | None, UsageHint | None]:
        try:
            payload = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise classify_failure(done.stderr or done.stdout or "no output", self.binary) from None
        if not isinstance(payload, dict):
            raise ModelError(f"claude returned unexpected JSON: {done.stdout[:200]}")
        text = str(payload.get("result") or "")
        if payload.get("is_error") or done.returncode != 0 or payload.get("subtype") != "success":
            raise classify_failure(text or done.stderr or done.stdout, self.binary)
        if len(text) < 300 and LIMIT_NOTICE_RE.match(text):
            raise ModelRateLimited(f"claude: {text.strip()}", _limit_hint(text))
        usage = payload.get("usage") or {}
        model_usage = payload.get("modelUsage") or {}
        # The model that produced the most output; never hardcoded.
        model = max(
            model_usage,
            key=lambda m: (model_usage[m] or {}).get("outputTokens", 0),
            default=None,
        )
        hint = UsageHint(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw={k: payload.get(k) for k in ("usage", "modelUsage", "total_cost_usd", "num_turns")},
        )
        return text, model, hint


def _limit_hint(text: str) -> UsageHint:
    epoch = EPOCH_RE.search(text)
    if epoch:
        resets = datetime.fromtimestamp(int(epoch.group(1)), UTC).isoformat(timespec="seconds")
        return UsageHint(limit_message=text.strip(), resets_at=resets)
    return limit_hint(text)
