"""The NotebookLM-only tier (``--no-models``): both model CLIs "not installed". The hints say what
to install, a tutor turn's error names the install step, and provider health says why."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_URL, DevServer, send, studio, system_section

HINT = "need Claude Code or Codex"


@pytest.fixture(scope="module")
def server(dev_server_factory: Callable[..., DevServer]) -> Iterator[DevServer]:
    started = dev_server_factory(no_models=True)
    yield started
    started.stop()


def test_the_hints_name_the_missing_models(page: Page) -> None:
    page.goto(COURSE_URL)
    expect(page.get_by_text(HINT).first).to_be_visible()
    health = page.get_by_role("list", name="Provider health")
    expect(health.get_by_role("button", name="claude: disabled")).to_be_visible()
    expect(health.get_by_role("button", name="codex: disabled")).to_be_visible()
    expect(health.get_by_role("button", name="notebooklm: available")).to_be_visible()

    rail = studio(page)
    rail.get_by_role("button", name="Practice exam").click()
    expect(rail.get_by_text(HINT)).to_be_visible()


def test_a_tutor_turn_names_the_install_step(page: Page) -> None:
    page.goto(COURSE_URL)
    page.get_by_role("button", name="Start session").click()
    expect(page.get_by_text("live session", exact=True)).to_be_visible(timeout=15_000)
    send(page, "What is a pointer?")
    error = page.get_by_role("alert").filter(has_text="Claude Code or Codex")
    expect(error.first).to_be_visible(timeout=20_000)

    page.get_by_role("button", name="End session").click()
    expect(page.get_by_role("button", name="Start session")).to_be_visible()


def test_system_says_the_models_are_not_installed(page: Page) -> None:
    page.goto("/system")
    rows = system_section(page, "Provider health").get_by_role("row")
    for provider in ("claude", "codex"):
        row = rows.filter(has=page.get_by_role("cell", name=provider, exact=True))
        expect(row.get_by_text("disabled", exact=True)).to_be_visible()
        expect(row).to_contain_text("not on PATH")
    notebooklm = rows.filter(has=page.get_by_role("cell", name="notebooklm", exact=True))
    expect(notebooklm.get_by_text("available", exact=True)).to_be_visible()
