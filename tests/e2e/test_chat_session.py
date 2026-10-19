"""A tutoring session end to end, as one ordered tour: each step needs the state the last one left.

The first session opens with the seeded Challenger probe on Pointers; answering it upholds level 4.
A tutoring turn, a rating, a "Sources only" ask, then End: the fake Analyzer finds evidence on the
weakest concept and queues a probe on it, which the second session opens with and Skip defers.
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import COURSE_URL, conversation, send, studio, tiles


def bubble(page: Page, caption: str | re.Pattern[str]) -> Locator:
    """The newest message whose caption (the line above the bubble) is ``caption``."""
    return (
        conversation(page)
        .locator("ol > li")
        .filter(has=page.locator("p").get_by_text(caption, exact=True))
        .last
    )


def note(page: Page, text: str | re.Pattern[str]) -> Locator:
    """A quiet note in the stream (a session started or ended, a command's reply)."""
    return conversation(page).locator("ol > li").filter(has_text=text).last


def probe_banner(page: Page) -> Locator:
    return page.get_by_role("status").filter(has_text="Challenger question on")


def start(page: Page) -> None:
    page.get_by_role("button", name="Start session").click()
    expect(page.get_by_text("live session", exact=True)).to_be_visible()


def end(page: Page) -> None:
    page.get_by_role("button", name="End session").click()
    expect(page.get_by_role("button", name="Start session")).to_be_visible()


def test_a_tutoring_session_tour(page: Page) -> None:
    page.goto(COURSE_URL)
    persona = page.get_by_role("combobox", name="Persona")
    expect(persona).to_have_text("simplifier")

    # 1. The first session opens with the seeded probe on Pointers.
    start(page)
    expect(note(page, "Tutoring session started with the simplifier persona.")).to_be_visible()
    banner = probe_banner(page)
    expect(banner).to_contain_text("Challenger question on Pointers.")
    expect(banner.get_by_role("button", name="Skip")).to_be_enabled()
    question = bubble(page, "Challenger · Pointers")
    expect(question).to_contain_text("what is the key idea of Pointers")
    expect(page.get_by_role("textbox", name="Message")).to_have_attribute(
        "placeholder", "Answer the challenge…"
    )

    # 2. Answering it: the Analyzer grades the exchange and upholds the proposed level.
    send(page, "A pointer holds the address of another object, and dereferencing it reads that.")
    graded = bubble(page, "Challenger")
    expect(graded).to_contain_text(re.compile(r"Challenge graded by \w+: \d+ evidence\."))
    expect(graded).to_contain_text("Upheld: Pointers is now level 4.")
    expect(banner).to_have_count(0)

    # 3. A tutoring turn: the persona and the provider label a Markdown answer with a table.
    send(page, "What is a pointer?")
    tutor = bubble(page, "Simplifier · Claude")
    expect(tutor).to_be_visible()
    expect(tutor.locator("table")).to_be_visible()
    expect(tutor.locator("table th").first).to_have_text("Expression")

    # 4. Rating it.
    tutor.get_by_role("group", name="Rate this answer").get_by_role(
        "button", name="Rate 4 out of 5"
    ).click()
    expect(tutor.get_by_role("status")).to_have_text("Rated the last answer 4/5.")
    expect(tutor.get_by_role("group", name="Rate this answer")).to_have_count(0)

    # 5. "Sources only" sends an ask, in the session's own conversation, unscoped.
    sources_only = page.get_by_role("button", name="Sources only")
    sources_only.click()
    expect(sources_only).to_have_attribute("aria-pressed", "true")
    send(page, "What does &x give?")
    asked = bubble(page, "Sources · every source")
    expect(asked).to_contain_text("Scoping is off during a session")
    expect(asked.get_by_role("list", name="Cited sources").get_by_role("listitem")).to_have_count(2)
    sources_only.click()
    expect(sources_only).to_have_attribute("aria-pressed", "false")

    # 6. End: the Analyzer's note, with a probe queued for the next session.
    end(page)
    ended = note(page, "Session ended.")
    expect(ended).to_contain_text(re.compile(r"Analyzer \(\w+\): [1-9]\d* evidence"))
    expect(ended).to_contain_text("1 challenge(s) queued for next session.")

    # 7. The upheld level shows in the Studio's Mastery view.
    rail = studio(page)
    tiles(rail).first.click()
    expect(rail.get_by_role("heading", name="Mastery")).to_be_focused()
    pointers = rail.get_by_role("meter", name="Pointers mastery")
    expect(pointers).to_have_attribute("aria-valuenow", "4")
    rail.get_by_role("button", name="Back to Studio").click()

    # 8. The second session opens with the queued probe; Skip defers it; End with no turn.
    start(page)
    banner = probe_banner(page)
    expect(banner).to_contain_text("Challenger question on Dynamic memory allocation.")
    expect(bubble(page, "Challenger · Dynamic memory allocation")).to_be_visible()
    banner.get_by_role("button", name="Skip").click()
    expect(note(page, "deferred")).to_contain_text("1 challenge(s) deferred to a later session.")
    expect(banner).to_have_count(0)
    end(page)
    expect(note(page, "Session ended.")).to_have_text("Session ended.")

    # 9. History lists both sessions; the first one's transcript holds its turns.
    page.get_by_role("button", name="History").click()
    history = page.get_by_role("dialog").filter(has_text="Sessions on CSE220")
    rows = history.get_by_role("listitem")
    expect(rows).to_have_count(2)
    for row in rows.all():
        expect(row.get_by_text("ended", exact=True)).to_be_visible()
    tutored = rows.filter(has_text="Tutor: claude")
    expect(tutored).to_have_count(1)
    tutored.get_by_role("button", name="Transcript").click()
    transcript = page.get_by_role("dialog", name="Session transcript")
    expect(transcript).to_contain_text("What is a pointer?")
    expect(transcript).to_contain_text("Upheld: Pointers is now level 4.")
    page.keyboard.press("Escape")
    expect(transcript).to_have_count(0)
