"""A practice exam end to end, as one ordered tour: write the spec, generate, take (through a
reload), hand in, grade, read the results and the paper, and see the mastery it moved.

FakeQuestioner's multiple-choice answer is always "B", and FakeCritic marks an open answer correct
when it contains "correct", so answering B, skipping, then "correct: ..." grades 2 of 2.
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import COURSE_URL, studio, tiles

SPEC = """course: CSE220
exam: Quick check
formats: {multiple_choice: 2, short_answer: 1}
difficulty: {easy: 100}
mode: realistic
"""


def exam_row(rail: Locator, name: str) -> Locator:
    return (
        rail.get_by_role("list", name="Practice exams")
        .get_by_role("listitem")
        .filter(has_text=name)
    )


def test_a_practice_exam_tour(page: Page) -> None:
    page.goto(COURSE_URL)
    rail = studio(page)

    # 1. The spec: prefilled from the template, replaced by a short one.
    tiles(rail).nth(1).click()
    expect(rail.get_by_text("No practice exams yet.")).to_be_visible()
    rail.get_by_role("button", name="New exam").click()
    spec = rail.get_by_role("textbox", name="Exam spec (YAML)")
    expect(spec).to_have_value(re.compile(r"^course: CSE220$", re.M))
    spec.fill(SPEC)
    rail.get_by_role("button", name="Create").click()

    # 2. Generating: back on Practice exams, the job's row, then the exam.
    expect(rail.get_by_role("heading", name="Practice exams", exact=True)).to_be_visible()
    expect(rail.get_by_role("status").filter(has_text="Exam ready: 3 questions")).to_be_visible()
    row = exam_row(rail, "Quick check")
    expect(row).to_contain_text("3 questions")
    expect(row.get_by_role("button", name="critiqued")).to_be_visible()
    expect(row).to_contain_text("Not taken yet")
    take = row.get_by_role("link", name="Take")
    expect(take).to_be_visible()
    expect(row.get_by_role("button", name="Grade")).to_be_disabled()
    expect(row.get_by_role("button", name="Results")).to_be_disabled()

    # 3. Taking it, one question at a time, in the chat area.
    take.click()
    page.wait_for_url(re.compile(r"/courses/CSE220/exams/[^/]+/take$"))
    area = page.get_by_role("region", name="Practice exam", exact=True)
    expect(area.get_by_role("heading", name="Quick check")).to_be_visible()
    area.get_by_role("button", name="Start").click()
    expect(area).to_contain_text("Attempt 1 · 1 of 3")
    expect(area.get_by_role("heading", name="Question 1")).to_be_focused()
    area.get_by_role("radio", name=re.compile(r"^B\.")).check()
    area.get_by_role("button", name="Answer").click()
    expect(area).to_contain_text("Attempt 1 · 2 of 3")
    expect(area.get_by_role("heading", name="Question 2")).to_be_focused()
    area.get_by_role("button", name="Skip").click()
    expect(area.get_by_role("heading", name="Question 3")).to_be_focused()
    expect(area.get_by_role("textbox", name="Your answer")).to_be_visible()

    # 4. Every answer is saved as given: a reload comes back to the same question.
    page.reload()
    expect(area.get_by_role("heading", name="Question 3")).to_be_visible()
    expect(area).to_contain_text("Attempt 1 · 3 of 3")
    tiles(rail).nth(1).click()  # the Studio's view is per tab, so a reload opens on its tiles
    row = exam_row(rail, "Quick check")
    expect(row).to_contain_text("Attempt 1 in progress · 2 of 3 done")
    expect(row.get_by_role("link", name="Resume")).to_be_visible()

    area.get_by_role("textbox", name="Your answer").fill("correct: it holds an address")
    area.get_by_role("button", name="Answer").click()
    expect(area.get_by_text("Every question has an answer or was skipped.")).to_be_visible()
    area.get_by_role("button", name="Finish").click()
    expect(area).to_contain_text("handed in")

    # 5. Grading: a job, then the results.
    area.get_by_role("button", name="Grade").click()
    expect(area.get_by_role("status").filter(has_text="Graded: 2 of 2 correct")).to_be_visible()
    expect(area.get_by_text("Attempt 1 is graded: 2 of 2 correct.")).to_be_visible()
    area.get_by_role("button", name="Results").click()
    results = page.get_by_role("dialog", name="Results: Quick check")
    expect(results).to_contain_text("Attempt 1: 2 of 2 correct")
    by_concept = results.get_by_role("region", name="By concept").get_by_role("row")
    expect(by_concept.first).to_contain_text("Concept")
    expect(by_concept).not_to_have_count(1)  # the header and at least one concept
    by_question = results.get_by_role("region", name="By question").locator(":scope > ol > li")
    expect(by_question).to_have_count(3)
    for item, verdict in zip(by_question.all(), ("correct", "skipped", "correct"), strict=True):
        expect(item.get_by_text(verdict, exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(results).to_have_count(0)

    # 6. Back in the chat, the Studio's row has caught up.
    area.get_by_role("link", name="Back to chat").first.click()
    expect(page).to_have_url(re.compile(r"/courses/CSE220$"))
    expect(page.get_by_role("region", name="Chat")).to_be_visible()
    row = exam_row(rail, "Quick check")
    expect(row).to_contain_text("Attempt 1: 2 of 2 correct")
    expect(row.get_by_role("button", name="Grade")).to_be_disabled()
    expect(row.get_by_role("link", name="Retake")).to_be_visible()

    row.get_by_role("button", name="Paper").click()
    paper = page.get_by_role("dialog", name="Paper with answer key")
    expect(paper).to_contain_text("Answer key")
    page.keyboard.press("Escape")
    expect(paper).to_have_count(0)

    # 7. Grading moved the mastery of the concept the questions were on.
    rail.get_by_role("button", name="Back to Studio").click()
    tiles(rail).first.click()
    expect(rail.get_by_role("meter", name="Pointers mastery")).to_have_attribute(
        "aria-valuenow", "4"
    )
