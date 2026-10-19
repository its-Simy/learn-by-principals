"""Audio Overview: generate a brief episode on the weakest concept, play it, read its brief."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_URL, choose, studio, tiles


def test_an_audio_overview(page: Page) -> None:
    page.goto(COURSE_URL)
    rail = studio(page)
    tiles(rail).nth(2).click()
    expect(rail.get_by_role("heading", name="Audio Overview", exact=True)).to_be_focused()
    expect(
        rail.get_by_text("No episodes yet. Generate one aimed at your weakest concepts.")
    ).to_be_visible()

    choose(rail, "Format", "Brief")
    expect(rail.get_by_role("combobox", name="Format")).to_have_text("Brief")
    rail.get_by_role("button", name="Generate").click()
    expect(rail.get_by_role("status").filter(has_text="Audio overview ready")).to_be_visible()

    episodes = rail.get_by_role("list", name="Episodes").get_by_role("listitem")
    expect(episodes).to_have_count(1)
    episode = episodes.first
    expect(episode).to_contain_text("On Dynamic memory allocation")
    audio = episode.locator("audio")
    expect(audio).to_have_attribute("src", re.compile(r"/api/podcasts/\d+/audio$"))
    response = page.request.get(audio.get_attribute("src") or "")
    assert response.status == 200
    assert response.headers["content-type"].startswith("audio/mp4")

    episode.get_by_role("button", name="Brief").click()
    brief = page.get_by_role("dialog", name="Episode brief")
    expect(brief).to_contain_text("Dwell on")
    page.keyboard.press("Escape")
    expect(brief).to_have_count(0)

    rail.get_by_role("button", name="Back to Studio").click()
    expect(tiles(rail).nth(2)).to_be_focused()
    expect(tiles(rail).nth(2)).to_contain_text("1 episode")
    made = rail.get_by_role("list", name="Outputs").get_by_role("listitem")
    expect(made.first).to_have_text(re.compile(r"^Episode of .*On Dynamic memory allocation"))
