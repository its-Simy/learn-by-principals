"""CodexProvider against a fake ``codex`` script on PATH."""

import json

import pytest

from core.providers.models.base import ModelError, ModelRateLimited, ModelTimeout, TaskPackage
from core.providers.models.codex import CodexProvider
from core.providers.state import ProviderState
from tests.fakes.fake_cli import install

HEADER = """OpenAI Codex v0.99.0 (research preview)
--------
workdir: /tmp/scratch
model: gpt-5.6-terra
provider: openai
approval: never
sandbox: read-only
--------
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    install(tmp_path / "bin", "codex", monkeypatch, log)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    def calls():
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return calls


@pytest.fixture
def provider(tmp_path):
    return CodexProvider(tmp_path / "scratch", timeout_s=5)


def task(system="You write exam questions.") -> TaskPackage:
    return TaskPackage("question_gen", "questioner", system, "Say hi", 64)


def test_success_reads_last_message_and_model_from_output(provider, fake, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_LAST_MESSAGE", "Hi there!\n")
    monkeypatch.setenv(
        "FAKE_STDERR", HEADER + "user\nSay hi\ncodex\nHi there!\ntokens used: 1,234\n"
    )

    result = provider.run(task())

    assert result.text == "Hi there!"
    assert result.provider == "codex"
    assert result.model == "gpt-5.6-terra"
    assert result.usage_hint.raw == {"tokens_used": 1234}
    assert provider.state is ProviderState.AVAILABLE
    (call,) = fake()
    argv = call["argv"]
    assert argv[:2] == ["exec", "--skip-git-repo-check"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[-2] == "-o" and not argv[-1].startswith("You write")  # no prompt in argv
    assert call["stdin"] == "You write exam questions.\n\n---\n\nSay hi"
    assert call["api_key"] is False
    assert call["cwd"] == str((tmp_path / "scratch").resolve())
    assert list((tmp_path / "scratch").iterdir()) == []  # -o file cleaned up


def test_openai_api_key_is_scrubbed(provider):
    assert "OPENAI_API_KEY" not in provider.env()
    assert "ANTHROPIC_API_KEY" not in provider.env()


def test_unknown_model_stays_unknown(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_LAST_MESSAGE", "Hi")
    assert provider.run(task()).model is None


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: You've hit your usage limit. Upgrade to Pro or try again in 2 hours.",
        "stream error: exceeded retry limit, last status: 429 Too Many Requests",
    ],
)
def test_rate_limit_messages(provider, fake, monkeypatch, stderr):
    monkeypatch.setenv("FAKE_STDERR", HEADER + stderr)
    monkeypatch.setenv("FAKE_EXIT", "1")
    with pytest.raises(ModelRateLimited):
        provider.run(task())
    assert provider.state is ProviderState.RATE_LIMITED
    assert provider.usage_hint().limit_message


def test_timeout(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    provider = CodexProvider(tmp_path / "scratch", timeout_s=0.5)
    with pytest.raises(ModelTimeout):
        provider.run(task())


def test_no_final_message_is_an_error(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", HEADER)
    with pytest.raises(ModelError, match="no final message"):
        provider.run(task())
    assert provider.state is ProviderState.BROKEN


def test_not_logged_in(provider, fake, monkeypatch):
    monkeypatch.setenv("FAKE_STDERR", "Not logged in. Run `codex login`.")
    monkeypatch.setenv("FAKE_EXIT", "1")
    with pytest.raises(ModelError):
        provider.run(task())
    assert provider.state is ProviderState.AUTH_EXPIRED


def test_version(provider, fake):
    assert provider.version() == "9.9.9 (fake)"
