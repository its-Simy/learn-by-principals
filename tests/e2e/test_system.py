"""/system: doctor's checks and the usage dashboard on the seeded data."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE, COURSE_NAME, system_section

# core/doctor.py's checks, in order. Their statuses depend on the machine (Claude Code is ok where
# it is installed; NotebookLM fails with no login in the scratch home), so only the rows are pinned.
DOCTOR_ROWS = [
    "Config",
    "DB schema",
    "Storage root",
    "Temp dir",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "NotebookLM",
    "Claude Code",
    "Codex",
]


def test_doctor_and_the_dashboard(page: Page) -> None:
    page.goto("/")
    page.get_by_role("link", name="System status").click()
    expect(page).to_have_url(re.compile(r"/system$"))
    expect(page.get_by_role("heading", name="System", level=1)).to_be_visible()

    doctor = system_section(page, "Doctor")
    expect(doctor.locator("tbody tr td:first-child")).to_have_text(DOCTOR_ROWS, timeout=30_000)
    for row in doctor.locator("tbody tr").all():
        expect(row.locator("td").nth(1)).to_have_text(re.compile(r"^(ok|warn|fail|off)$"))

    health = system_section(page, "Provider health").get_by_role("row")
    for provider in ("claude", "codex", "notebooklm"):
        row = health.filter(has=page.get_by_role("cell", name=provider, exact=True))
        expect(row.get_by_text("available", exact=True)).to_be_visible()

    runs = system_section(page, "Model runs")
    expect(runs.get_by_text("Last 7 days")).to_be_visible()
    for provider in ("claude", "codex", "notebooklm"):
        expect(runs.get_by_role("cell", name=provider, exact=True).first).to_be_visible()

    benchmarks = system_section(page, "Benchmarks")
    expect(benchmarks.get_by_role("meter").first).to_be_visible()
    expect(benchmarks.get_by_role("meter", name="claude explain score")).to_be_visible()

    expect(system_section(page, "NotebookLM artifacts")).to_contain_text("0 audio overviews saved.")

    files = system_section(page, "Course files")
    cells = (
        files.get_by_role("row")
        .filter(has=page.get_by_role("cell", name=COURSE))
        .get_by_role("cell")
    )
    expect(cells).to_have_text([COURSE, "3", "0", "0", "0", "0"])

    weakest = system_section(page, "Weakest concepts").locator("tbody tr")
    expect(weakest).to_have_count(5)
    first = weakest.first.locator("td")
    expect(first.nth(0)).to_have_text("Dynamic memory allocation")
    expect(first.nth(1)).to_have_text(COURSE_NAME)
    expect(
        weakest.first.get_by_role("meter", name="Dynamic memory allocation mastery")
    ).to_have_attribute("aria-valuenow", "0")
