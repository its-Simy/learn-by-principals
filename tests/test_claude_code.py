"""ClaudeCodeProvider against a fake ``claude`` script on PATH."""

import json

import pytest

from core.providers.models.base import ModelError, ModelRateLimited, ModelTimeout, TaskPackage
from core.providers.models.claude_code import ClaudeCodeProvider
from core.providers.state import ProviderState
from tests.fakes.fake_cli import install

SUCCESS = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "Hi! A pointer stores an address.",
    "num_turns": 1,
    "usage": {"input_tokens": 12, "output_tokens": 9},
    "modelUsage": {"claude-fable-5-1": {"inputTokens": 12, "outputTokens": 9}},
}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    install(tmp_path / "bin", "claude", monkeypatch, log)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()]

    return calls


@pytest.fixture
def provider(tmp_path):
    return ClaudeCodeProvider(tmp_path / "scratch", timeout_s=5)


def task(system="You are a patient tutor.") -> TaskPackage:
    return TaskPackage("explain", "simplifier", system, "Say hi", 64)


def test_success_parses_text_model_and_usage(provider, fake, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_STDOUT", json.dumps(SUCCESS))

    result = provider.run(task())

    assert result.text == "Hi! A pointer stores an address."
    assert result.provider == "claude"
    assert result.model == "claude-fable-5-1"
    assert (result.usage_hint.input_tokens, result.usage_hint.output_tokens) == (12, 9)
    assert provider.state is ProviderState.AVAILABLE
    assert provider.usage_hint() == result.usage_hint
    (call,) = fake()
    assert call["argv"][:4] == ["-p", "Say hi", "--output-format", "json"]
    assert call["argv"][call["argv"].index("--system-prompt") + 1] == "You are a patient tutor."
    assert call["argv"][call["argv"].index("--tools") + 1] == ""
    assert call["api_key"] is False  # ANTHROPIC_API_KEY scrubbed
    assert call["cwd"] == str((tmp_path / "scratch").resolve())


@pytest.mark.parametrize(
    ("stdout", "stderr", "exit_code"),
    [
        (
            json.dumps(
                {**SUCCESS, "is_error": True, "result": "5-hour limit reached ∙ resets 3pm"}
            ),
            "",
            1,
        ),
        (json.dumps({**SUCCESS, "result": "Claude AI usage limit reached|1758650400"}), "", 0),
        ("", "Error: You've hit your usage limit. Resets at 3pm.", 1),
    ],
)
def test_rate_limit_messages_mark_rate_limited(
    provider, fake, monkeypatch, stdout, stderr, exit_code
):
    monkeypatch.setenv("FAKE_STDOUT", stdout)
    monkeypatch.setenv("FAKE_STDERR", stderr)
    monkeypatch.setenv("FAKE_EXIT", str(exit_code))

    with pytest.raises(ModelRateLimited) as info:
        provider.run(task())

    assert provider.state is ProviderState.RATE_LIMITED
    assert info.value.hint.limit_message
    assert provider.usage_hint() == info.value.hint


def test_epoch_reset_time_is_parsed(provider, fake, monkeypatch):
    monkeypatch.setenv(
        "FAKE_STDOUT", json.dumps({**SUCCESS, "result": "Claude AI usage limit reached|1758650400"})
    )
    with pytest.raises(ModelRateLimited) as info:
        provider.run(task())
    assert info.value.hint.resets_at == "2025-09-23T18:00:00+00:00"


def test_timeout(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    provider = ClaudeCodeProvider(tmp_path / "scratch", timeout_s=0.5)
    with pytest.raises(ModelTimeout):
        provider.run(task())
    assert provider.state is ProviderState.LIMITED


def test_login_error_is_auth_expired(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", "Invalid API key · Please run /login")
    monkeypatch.setenv("FAKE_EXIT", "1")
    with pytest.raises(ModelError):
        provider.run(task())
    assert provider.state is ProviderState.AUTH_EXPIRED


def test_other_failure_is_broken(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", "segfault")
    monkeypatch.setenv("FAKE_EXIT", "139")
    with pytest.raises(ModelError, match="segfault"):
        provider.run(task())
    assert provider.state is ProviderState.BROKEN


def test_no_system_prompt_flag_when_empty(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", json.dumps(SUCCESS))
    provider.run(task(system=""))
    assert "--system-prompt" not in fake()[0]["argv"]


def test_health_is_a_cached_one_token_call(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", json.dumps({**SUCCESS, "result": "OK"}))
    now = [1000.0]
    provider = ClaudeCodeProvider(tmp_path / "scratch", timeout_s=5, clock=lambda: now[0])

    assert provider.health() is ProviderState.AVAILABLE
    assert provider.health() is ProviderState.AVAILABLE
    assert len(fake()) == 1
    now[0] += 601
    provider.health()
    assert len(fake()) == 2


def test_missing_binary_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    provider = ClaudeCodeProvider(tmp_path / "scratch")
    assert provider.health() is ProviderState.DISABLED
    assert provider.version() is None
    with pytest.raises(ModelError, match="not on PATH"):
        provider.run(task())


def test_version(provider, fake):
    assert provider.version() == "9.9.9 (fake)"
