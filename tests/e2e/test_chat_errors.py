"""A tutor turn neither model can answer: the error bubble, its reset time, and provider health.

"rate limit" in a question makes both fake models rate-limited for 20 s, in the server's database,
so this module has a server of its own and nothing after it here needs a model.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import COURSE_URL, conversation, send, system_section


def test_a_rate_limited_turn_says_who_and_until_when(page: Page) -> None:
    page.goto(COURSE_URL)
    page.get_by_role("button", name="Start session").click()
    banner = page.get_by_role("status").filter(has_text="Challenger question on Pointers.")
    banner.get_by_role("button", name="Skip").click()
    expect(banner).to_have_count(0)

    send(page, "Please hit the rate limit now")
    alerts = conversation(page).get_by_role("alert")
    error = alerts.nth(0)
    expect(error).to_contain_text("couldn't answer")
    expect(error).to_contain_text("usage limit")
    expect(error).to_contain_text(re.compile(r"Resets at \d"))

    # The top bar's health dots catch up at once, not at their next poll.
    health = page.get_by_role("list", name="Provider health")
    expect(health.get_by_role("button", name="claude: rate limited")).to_be_visible()
    expect(health.get_by_role("button", name="codex: rate limited")).to_be_visible()

    # Within the cooldown the router has no provider left to try.
    error.get_by_role("button", name="Try again").click()
    expect(alerts).to_have_count(2)
    retried = alerts.nth(1)
    expect(retried).to_contain_text("No provider could answer")
    expect(retried.get_by_role("button", name="Try again")).to_be_enabled()
    expect(error.get_by_role("button", name="Try again")).to_have_count(0)  # its way out was taken

    page.get_by_role("button", name="End session").click()
    expect(page.get_by_role("button", name="Start session")).to_be_visible()

    page.get_by_role("link", name="System status").click()
    expect(page).to_have_url(re.compile(r"/system$"))
    rows = system_section(page, "Provider health").get_by_role("row")
    for provider in ("claude", "codex"):
        row = rows.filter(has=page.get_by_role("cell", name=provider, exact=True))
        expect(row.get_by_text("rate limited", exact=True)).to_be_visible()
        expect(row).to_contain_text("usage limit")
