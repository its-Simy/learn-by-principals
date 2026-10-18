"""Sources: the seeded files, the selection, uploads that link, fail and retry, code files."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    COURSE,
    COURSE_URL,
    SEEDED_FILES,
    choose,
    course_files,
    file_row,
    sources,
    upload,
)

SEEDED_BUCKETS = {
    "CSE220 Syllabus.md": "syllabus",
    "HW1 Bit Manipulation.txt": "assignments",
    "Lecture 3 - Pointers.md": "lectures",
}


def link_jobs(page: Page) -> list[dict]:
    response = page.request.get(f"/api/jobs?course={COURSE}")
    assert response.ok
    return [job for job in response.json() if job["kind"] == "link"]


def select_all(page: Page, selected: int, total: int):
    """The rail's "Select all sources (n/m)" checkbox. Its accessible name has no space before the
    count: the visible gap is a CSS margin."""
    # The slash is escaped: Playwright parses a regex name inside its own /.../ selector syntax.
    name = re.compile(rf"^Select all sources\s*\({selected}\/{total}\)$")
    return sources(page).get_by_role("checkbox", name=name)


def badge(row, text: str):
    """A row's bucket or state badge, by its exact text."""
    return row.get_by_text(text, exact=True)


def test_seeded_files_are_linked_and_selectable(page: Page) -> None:
    page.goto(COURSE_URL)
    rows = course_files(page)
    expect(rows).to_have_count(3)
    for name in SEEDED_FILES:
        row = file_row(page, name)
        expect(badge(row, SEEDED_BUCKETS[name])).to_be_visible()
        expect(badge(row, "linked")).to_be_visible()
        expect(row.get_by_role("checkbox", name=f"Use {name} in questions")).to_be_checked()

    expect(select_all(page, 3, 3)).to_be_checked()
    syllabus = sources(page).get_by_role("checkbox", name="Use CSE220 Syllabus.md in questions")
    syllabus.click()
    expect(syllabus).not_to_be_checked()
    expect(select_all(page, 2, 3)).to_have_attribute("aria-checked", "mixed")

    select_all(page, 2, 3).click()  # indeterminate -> every source
    expect(select_all(page, 3, 3)).to_be_checked()
    expect(syllabus).to_be_checked()


def test_an_upload_is_linked(page: Page) -> None:
    page.goto(COURSE_URL)
    expect(course_files(page)).to_have_count(3)
    upload(page, "Lecture 4 - Memory.md", "# Lecture 4\n\nmalloc and free manage the heap.\n")

    row = file_row(page, "Lecture 4 - Memory.md")
    expect(badge(row, "lectures")).to_be_visible()
    expect(badge(row, "linked")).to_be_visible(timeout=5_000)
    expect(row.get_by_role("checkbox")).to_be_checked()  # a new source joins the selection
    done = sources(page).get_by_role("status").filter(has_text="Sources: 1 linked")
    expect(done).to_be_visible()
    expect(course_files(page)).to_have_count(4)


def test_a_failing_file_shows_failed_and_retry(page: Page) -> None:
    page.goto(COURSE_URL)
    expect(course_files(page).first).to_be_visible()
    upload(page, "Lecture 5 fail.md", "# Lecture 5\n\nThe dev server refuses this name.\n")

    row = file_row(page, "Lecture 5 fail.md")
    expect(badge(row, "lectures")).to_be_visible()
    expect(badge(row, "failed")).to_be_visible()
    expect(row.get_by_role("checkbox")).to_have_count(0)  # not in NotebookLM: nothing to select
    warning = sources(page).get_by_role("alert").filter(has_text="Sources: 1 failed")
    expect(warning).to_be_visible()
    # Under the bar, the reason, naming the file.
    expect(
        sources(page).get_by_role("listitem").filter(has_text="its name contains 'fail'")
    ).to_contain_text("Lecture 5 fail")

    before = len(link_jobs(page))
    warning.get_by_role("button", name="Retry").click()
    # A new link job runs and fails the same way; the bar and the row say so again.
    page.wait_for_function(
        """async ([course, count]) => {
            const jobs = await (await fetch(`/api/jobs?course=${course}`)).json()
            const links = jobs.filter((j) => j.kind === "link")
            return links.length > count && links.every((j) => j.status === "done")
        }""",
        arg=[COURSE, before],
        polling=250,
    )
    latest = link_jobs(page)[-1]
    assert latest["result"]["failed"] == 1, latest
    expect(warning).to_be_visible()
    expect(warning.get_by_role("button", name="Retry")).to_be_enabled()
    expect(badge(row, "failed")).to_be_visible()


def test_a_code_file_is_stored_not_linked(page: Page) -> None:
    page.goto(COURSE_URL)
    expect(course_files(page).first).to_be_visible()
    choose(sources(page), "Bucket for these files", "code")
    expect(sources(page).get_by_role("combobox", name="Bucket for these files")).to_have_text(
        re.compile(r"^\s*code\s*$")
    )
    upload(page, "util.py", "def mask(n):\n    return (1 << n) - 1\n", mime="text/x-python")

    row = file_row(page, "util.py")
    expect(badge(row, "code")).to_be_visible()
    expect(badge(row, "stored")).to_be_visible()
    expect(row.get_by_role("checkbox")).to_have_count(0)
    # Nothing is left uploading.
    expect(sources(page).get_by_role("list", name="Uploads")).to_have_count(0)
