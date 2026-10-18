"""Asking the sources with no session: the answer, its citations, and the source selection."""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import COURSE_URL, composer, conversation, send, sources


def answer(page: Page, scope: str) -> Locator:
    """The sources answer whose caption names ``scope``."""
    caption = f"Sources · {scope}"
    return conversation(page).locator("li").filter(has=page.get_by_text(caption, exact=True))


def chip(bubble: Locator, n: int, filename: str) -> Locator:
    # A chip's name is "[n]" then the file name: no space between, as the spans render it.
    name = re.compile(rf"^\[{n}\]\s*{re.escape(filename)}$")
    return bubble.get_by_role("list", name="Cited sources").get_by_role("button", name=name)


def test_an_ask_answers_with_citations(page: Page) -> None:
    page.goto(COURSE_URL)
    expect(page.get_by_role("button", name="Start session")).to_be_enabled()
    send(page, "What is a pointer?")

    bubble = answer(page, "all sources")
    expect(bubble).to_be_visible()
    # Markdown: bold text, a list and a code block.
    expect(bubble.locator("strong", has_text="pointer")).to_be_visible()
    expect(bubble.locator("pre code")).to_contain_text("int *p = &x;")
    chips = bubble.get_by_role("list", name="Cited sources").get_by_role("listitem")
    expect(chips).to_have_count(2)
    expect(chip(bubble, 1, "CSE220 Syllabus.md")).to_be_visible()
    expect(chip(bubble, 2, "Lecture 3 - Pointers.md")).to_be_visible()
    expect(composer(page)).to_be_focused()  # focus returns to the box after a reply

    first = chip(bubble, 1, "CSE220 Syllabus.md")
    first.click()
    excerpt = page.get_by_role("dialog")
    expect(excerpt).to_contain_text("[1] CSE220 Syllabus.md")
    expect(excerpt.locator("blockquote")).to_contain_text("Week 1: data representation")
    page.keyboard.press("Escape")
    expect(excerpt).to_have_count(0)
    # Focus goes back to the chip that opened the excerpt (a popover returns it to its trigger),
    # so the next chip is a Tab away; the composer is not refocused.
    expect(first).to_be_focused()


def test_an_ask_is_scoped_to_the_checked_sources(page: Page) -> None:
    page.goto(COURSE_URL)
    sources(page).get_by_role("checkbox", name="Use CSE220 Syllabus.md in questions").click()
    expect(page.get_by_text("Asking 2 selected sources.")).to_be_visible()
    send(page, "What is a pointer?")

    bubble = answer(page, "2 selected sources")
    expect(bubble).to_be_visible()
    learner = conversation(page).locator("li").filter(has_text="What is a pointer?")
    expect(learner).to_contain_text("2 selected sources")  # the question is tagged with its scope
    expect(bubble.get_by_role("list", name="Cited sources").get_by_role("listitem")).to_have_count(
        2
    )
    expect(chip(bubble, 1, "Lecture 3 - Pointers.md")).to_be_visible()
    expect(chip(bubble, 2, "HW1 Bit Manipulation.txt")).to_be_visible()
    expect(bubble).not_to_contain_text("CSE220 Syllabus.md")
