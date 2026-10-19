"""Studio: the tiles, where Back puts the focus, and a concept draft from Seed to Mastery."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_URL, studio, tiles


def test_tiles_and_where_back_puts_the_focus(page: Page) -> None:
    page.goto(COURSE_URL)
    rail = studio(page)
    home = tiles(rail)
    expect(home).to_have_count(4)
    for tile, title, status in zip(
        home.all(),
        ("Mastery", "Practice exam", "Audio Overview", "Concepts"),
        ("5 concepts", "No exams yet", "No episodes yet", "5 active"),
        strict=True,
    ):
        expect(tile).to_contain_text(title)
        expect(tile).to_contain_text(status)

    # A view takes the focus on its heading; Back hands it to whatever opened the view.
    home.nth(1).click()
    expect(rail.get_by_role("heading", name="Practice exams", exact=True)).to_be_focused()
    rail.get_by_role("button", name="New exam").click()
    expect(rail.get_by_role("heading", name="New practice exam", exact=True)).to_be_focused()
    expect(rail.get_by_role("button", name="Back to Practice exams")).to_have_count(1)
    rail.get_by_role("button", name="Back to Practice exams").click()
    expect(rail.get_by_role("button", name="New exam")).to_be_focused()
    rail.get_by_role("button", name="Back to Studio").click()
    expect(home.nth(1)).to_be_focused()


def test_seed_review_apply_then_mastery(page: Page) -> None:
    page.goto(COURSE_URL)
    rail = studio(page)
    home = tiles(rail)
    expect(home.nth(3)).to_contain_text("5 active")

    # Seed: a job that drafts the concept list from the sources.
    home.nth(3).click()
    expect(rail.get_by_role("heading", name="Concepts", exact=True)).to_be_focused()
    rail.get_by_role("button", name="Seed").click()
    expect(
        rail.get_by_role("status").filter(has_text="Concept draft ready: 6 concepts")
    ).to_be_visible()
    drafts = rail.get_by_role("list", name="Concept drafts").get_by_role("button")
    expect(drafts).to_have_count(1)
    expect(drafts.first).to_contain_text("needs review")

    # Review: Apply refuses a draft still marked reviewed: false.
    drafts.first.click()
    editor = rail.get_by_role("textbox", name="Draft YAML")
    expect(editor).to_have_value(re.compile(r"^reviewed: false$", re.M))
    apply = rail.get_by_role("button", name="Apply", exact=True)
    apply.click()
    expect(rail.get_by_role("alert")).to_contain_text(re.compile(r"reviewed", re.I))

    editor.fill(re.sub(r"^reviewed: false$", "reviewed: true", editor.input_value(), flags=re.M))
    expect(apply).to_be_disabled()  # unsaved edits are saved before an apply
    rail.get_by_role("button", name="Save", exact=True).click()
    expect(rail.get_by_role("status").filter(has_text="Saved.")).to_be_visible()
    expect(rail.get_by_role("button", name="reviewed", exact=True)).to_be_visible()

    apply.click()
    applied = rail.get_by_role("status").filter(has_text="Applied:")
    expect(applied).to_contain_text(re.compile(r"Applied: 1 added"))
    expect(applied).to_contain_text("0 retired")

    rail.get_by_role("button", name="Back to Concepts").click()
    expect(drafts.first).to_be_focused()
    expect(drafts.first).to_contain_text("reviewed")
    rail.get_by_role("button", name="Back to Studio").click()
    expect(home.nth(3)).to_be_focused()
    expect(home.nth(0)).to_contain_text("6 concepts")
    expect(home.nth(3)).to_contain_text("6 active")
    made = rail.get_by_role("list", name="Outputs").get_by_role("listitem")
    expect(made.first).to_have_text(re.compile(r"^Draft of .*reviewed"))

    # Mastery: the new concept counts, at level 0 with no evidence behind it.
    home.nth(0).click()
    view = rail.get_by_role("region", name="Mastery")
    expect(view).to_contain_text("6 concepts · 4 below level 3")
    grid = rail.get_by_label("Concepts at each level")
    expect(grid.locator("dt")).to_have_text([f"Level {n}" for n in range(6)])
    expect(grid.locator("dd")).to_have_text(["2", "1", "1", "1", "1", "0"])
    weakest = rail.get_by_role("list", name="Concepts, weakest first").get_by_role("listitem")
    expect(weakest).to_have_count(6)
    expect(weakest.first).to_contain_text("Dynamic memory allocation")
    weakest.first.get_by_role("button", name="Dynamic memory allocation").click()
    evidence = page.get_by_role("dialog", name="Dynamic memory allocation")
    expect(evidence).to_contain_text("No evidence recorded yet.")
    page.keyboard.press("Escape")
    expect(evidence).to_have_count(0)
