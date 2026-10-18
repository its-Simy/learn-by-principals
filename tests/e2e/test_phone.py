"""Phone width: the rails become icon strips that open sheets, and nothing scrolls sideways."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_URL, SEEDED_FILES, tiles

WIDTH = 390
pytestmark = pytest.mark.browser_context_args(viewport={"width": WIDTH, "height": 844})


def scroll_width(page: Page) -> int:
    return page.evaluate("document.documentElement.scrollWidth")


def test_rails_open_as_sheets(page: Page) -> None:
    page.goto(COURSE_URL)
    # Before any sheet opens: behind one, Radix hides the rest of the page from the a11y tree.
    expect(page.get_by_role("link", name="BrightLearn home")).to_be_visible()
    expect(page.get_by_role("heading", name="Systems Fundamentals I", level=1)).to_be_visible()
    expect(page.get_by_role("textbox", name="Message")).to_be_visible()

    page.get_by_role("button", name="Open Studio").click()
    sheet = page.get_by_role("dialog", name="Studio")
    expect(tiles(sheet)).to_have_count(4)
    expect(tiles(sheet).first).to_contain_text("5 concepts")
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)

    page.get_by_role("button", name="Open Sources").click()
    sheet = page.get_by_role("dialog", name="Sources")
    rows = sheet.get_by_role("list", name="Course files").get_by_role("listitem")
    expect(rows).to_have_count(len(SEEDED_FILES))
    for name in SEEDED_FILES:
        expect(rows.filter(has_text=name)).to_have_count(1)
    assert scroll_width(page) <= WIDTH
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    assert scroll_width(page) <= WIDTH


@pytest.mark.parametrize("path", ["/", COURSE_URL, "/system"])
def test_no_sideways_scroll(page: Page, path: str) -> None:
    page.goto(path)
    expect(page.get_by_role("link", name="BrightLearn home")).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert scroll_width(page) <= WIDTH
