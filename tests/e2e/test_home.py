"""Home: the course list, the theme, a new course's empty panes, and the not-found page."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_NAME, sources, studio, tiles

LIGHT_BODY = "rgb(248, 250, 253)"
DARK_BODY = "rgb(31, 31, 31)"


def test_light_by_default_with_one_course_card(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_role("heading", name="Courses", level=1)).to_be_visible()
    expect(page.locator("html")).not_to_have_class(re.compile(r"\bdark\b"))
    expect(page.locator("body")).to_have_css("background-color", LIGHT_BODY)

    brand = page.get_by_role("link", name="BrightLearn home")
    expect(brand).to_have_text("BrightLearn")
    expect(brand.locator("svg")).to_have_count(0)

    cards = page.get_by_role("list", name="Courses").get_by_role("listitem")
    expect(cards).to_have_count(1)
    card = cards.first
    expect(card.get_by_role("heading")).to_have_text(COURSE_NAME)
    expect(card).to_contain_text("3 sources · 3 linked · 5 concepts")
    # The name only: the code and the term are the folder's business.
    expect(card).not_to_contain_text("CSE220")


def test_dark_theme_survives_a_reload(page: Page) -> None:
    page.goto("/")
    page.get_by_role("button", name="Switch to dark theme").click()
    expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
    expect(page.locator("body")).to_have_css("background-color", DARK_BODY)

    page.reload()
    expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
    expect(page.locator("body")).to_have_css("background-color", DARK_BODY)

    page.get_by_role("button", name="Switch to light theme").click()
    expect(page.locator("html")).not_to_have_class(re.compile(r"\bdark\b"))
    expect(page.locator("body")).to_have_css("background-color", LIGHT_BODY)


def test_unknown_page_and_unknown_api_route(page: Page) -> None:
    page.goto("/no/such/page")
    expect(page.get_by_text("There is no page at this address.")).to_be_visible()
    back = page.get_by_role("link", name="Back to courses")
    expect(back).to_be_visible()
    assert page.request.get("/api/nope").status == 404
    back.click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_role("heading", name="Courses", level=1)).to_be_visible()


def new_course(page: Page, name: str) -> None:
    page.goto("/")
    page.get_by_role("button", name="New course").click()
    dialog = page.get_by_role("dialog", name="New course")
    expect(dialog.locator("input")).to_have_count(1)  # the name only: the code is derived
    dialog.get_by_role("textbox", name="Name").fill(name)
    dialog.get_by_role("button", name="Create").click()


def test_new_course_asks_for_a_name_and_opens_empty(page: Page) -> None:
    new_course(page, "Linear Algebra")
    page.wait_for_url("**/courses/LINEAR-ALGEBRA")
    expect(page.locator("header h1")).to_have_text("Linear Algebra")

    expect(sources(page).get_by_text("Upload the syllabus to start.")).to_be_visible()
    chat = page.get_by_role("region", name="Chat")
    expect(chat.get_by_text("Upload course files to ask about them.")).to_be_visible()

    home = studio(page)
    expect(tiles(home)).to_have_count(4)
    for tile, status in zip(
        tiles(home).all(),
        ("No concepts yet", "No exams yet", "No episodes yet", "Nothing seeded yet"),
        strict=True,
    ):
        expect(tile).to_contain_text(status)
    expect(home.get_by_text("Nothing made yet. Pick a tile to start.")).to_be_visible()

    # The same name again gets the next free code.
    new_course(page, "Linear Algebra")
    page.wait_for_url("**/courses/LINEAR-ALGEBRA-2")
    expect(page.locator("header h1")).to_have_text("Linear Algebra")
