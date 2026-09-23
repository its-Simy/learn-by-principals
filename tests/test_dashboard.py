"""BL-037: the usage dashboard renders from a seeded DB and runs cleanly in headless Chromium."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from cli.app import app
from core.config import load_config
from core.ledger.ledger import Ledger, ModelRun
from core.memory.db import Manifest, ResourceRow, connect
from core.memory.learner import Concept, LearnerMemory
from core.podcast.episodes import PodcastStore
from core.providers.state import ProviderState
from core.router.benchmarks import Benchmarks
from core.router.health import HealthStore
from dashboard.data import collect
from dashboard.render import render

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)


def at(delta: timedelta) -> str:
    return (NOW - delta).isoformat(timespec="seconds")


def seed(conn) -> None:
    ledger = Ledger(conn)
    runs = [
        # today
        ("claude", "explain", timedelta(hours=1), True, 1200, None),
        ("claude", "explain", timedelta(hours=2), True, 1800, None),
        ("claude", "explain", timedelta(hours=3), False, 300, None),
        ("codex", "explain", timedelta(hours=1), True, 2500, "claude"),
        # earlier this week
        ("codex", "analyze_transcript", timedelta(days=2), True, 4100, None),
        ("codex", "analyze_transcript", timedelta(days=3), True, 3900, None),
        ("notebooklm", "generate_audio", timedelta(days=1), True, 600000, None),
        ("notebooklm", "generate_quiz", timedelta(days=2), True, 90000, None),
        ("notebooklm", "query", timedelta(days=2), True, 3000, None),
        # older than a week: counts only toward all-time artifacts
        ("claude", "explain", timedelta(days=9), True, 999, None),
        ("notebooklm", "generate_audio", timedelta(days=20), True, 500000, None),
    ]
    for provider, task, ago, ok, ms, fallback in runs:
        ledger.record(ModelRun(provider, task, at(ago), ok, duration_ms=ms, fallback_from=fallback))
    health = HealthStore(conn)
    health.set(
        "claude",
        ProviderState.RATE_LIMITED,
        NOW - timedelta(minutes=5),
        NOW + timedelta(minutes=55),
        "usage limit reached",
    )
    health.set("codex", ProviderState.AVAILABLE, NOW - timedelta(minutes=1))
    marks = Benchmarks(conn)
    for _ in range(12):
        marks.record("codex", "question_gen", format_compliance=1.0, latency_ms=2000)
    marks.record("codex", "question_gen", accuracy=0.75, groundedness=0.5)
    PodcastStore(conn).record("CSE220", ["cse220/pointers"], "/x/brief.md", "/x/audio.m4a")
    manifest = Manifest(conn)
    states = ["synced"] * 7 + ["stale"] * 2 + ["failed"] + ["link"] * 3 + ["deferred"]
    for topic_id, state in enumerate(states, start=1):
        manifest.upsert(
            ResourceRow(
                course="CSE220",
                org_unit_id=1,
                topic_id=topic_id,
                module_path="",
                title=f"t{topic_id}",
                type_identifier="File",
                last_seen="",
                sync_state=state,
            )
        )
    learner = LearnerMemory(conn)
    for i, name in enumerate(["Pointers", "Structs", "Bitwise operators"]):
        learner.upsert_concept(Concept(f"cse220/{i}", "CSE220", name))
    e = learner.add_evidence("cse220/2", "applied", "strong")
    learner.set_mastery("cse220/2", 3, 0.8, [e])


@pytest.fixture
def html():
    conn = connect(":memory:")
    seed(conn)
    return render(collect(conn, NOW))


def cells(html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", html)]


def test_runs_per_provider_today_and_this_week(html):
    tables = cells(html)
    # provider, today, failed today, 7 days, failed, median, fallbacks
    i = tables.index("claude")
    assert tables[i : i + 7] == ["claude", "3", "1", "3", "1", "1.2 s", "0"]
    j = tables.index("codex")
    assert tables[j : j + 7] == ["codex", "1", "0", "3", "0", "3.9 s", "1"]
    assert re.search(r"Calls today \(UTC\)</div><div class=\"value\">4<", html)
    assert re.search(r"Calls, last 7 days</div><div class=\"value\">9<", html)
    assert 'data-tip="claude · 3 calls · 1 failed · median 1.2 s"' in html


def test_health_benchmarks_artifacts_sync_and_weakest(html):
    text = cells(html)
    assert "RATE_LIMITED" in text and "2026-09-23T18:55+00:00" in text
    assert '<span class="status serious">RATE_LIMITED</span>' in html
    assert '<span class="status good">AVAILABLE</span>' in html
    # benchmarks: codex question_gen, 12 runs, accuracy .75, groundedness .5, score
    k = text.index("12")
    assert text[k - 1 : k + 7] == ["codex", "12", "0.75", "0.50", "1.00", "2.0 s", "—", "0.75"]
    assert re.search(r"Audio overviews</div><div class=\"value\">1 <span[^>]*>of 2 total", html)
    assert re.search(r"Quizzes</div><div class=\"value\">1 <span[^>]*>of 1 total", html)
    assert re.search(r"Podcast episodes recorded</div><div class=\"value\">1<", html)
    s = text.index("CSE220")
    assert text[s : s + 8] == ["CSE220", "7", "2", "1", "3", "1", "0", "14"]  # sync order + total
    assert 'data-tip="CSE220 · synced · 7"' in html
    w = text.index("Pointers")
    assert text[w : w + 5] == ["Pointers", "CSE220", "0/5", "—", "0.00"]
    assert text.index("Bitwise operators") > text.index("Structs")  # level 3 is least weak


def test_self_contained(html):
    assert "<script src" not in html and "<link" not in html
    assert not re.search(r"https?://", html)
    assert "prefers-color-scheme: dark" in html


def test_empty_database_renders(tmp_path):
    page = render(collect(connect(":memory:"), NOW))
    assert "No measured runs yet." in page and "Nothing synced yet." in page


def test_cli_writes_the_page(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIGHTLEARN_HOME", str(tmp_path / "home"))
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    result = CliRunner().invoke(app, ["dashboard"])
    assert result.exit_code == 0, result.output
    path = load_config().home / "dashboard.html"
    assert path.read_text().startswith("<!doctype html>")
    assert opened == [path.as_uri()]
    assert CliRunner().invoke(app, ["dashboard", "--no-open"]).exit_code == 0
    assert len(opened) == 1


def test_opens_without_errors_in_headless_chromium(html, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    page_path = tmp_path / "dashboard.html"
    page_path.write_text(html)
    errors: list[str] = []
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: r.url.startswith("file:") or errors.append(r.url))
            page.goto(page_path.as_uri())
            assert page.title() == "BrightLearn usage"

            page.hover('[data-tip^="claude"]')
            tip = page.locator("#tip")
            assert tip.is_visible()
            assert tip.text_content() == "claude · 3 calls · 1 failed · median 1.2 s"

            page.emulate_media(color_scheme="dark")
            dark = page.evaluate("getComputedStyle(document.body).backgroundColor")
            page.emulate_media(color_scheme="light")
            light = page.evaluate("getComputedStyle(document.body).backgroundColor")
            browser.close()
    except sync_api.Error as exc:  # Chromium not installed here
        pytest.skip(f"headless Chromium unavailable: {exc}")
    assert errors == []
    assert (dark, light) == ("rgb(13, 13, 13)", "rgb(249, 249, 247)")
