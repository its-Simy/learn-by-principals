import pytest

from core.sync.classify import BUCKETS, classify


@pytest.mark.parametrize(
    ("title", "filename", "bucket"),
    [
        ("Syllabus", "CSE220_Syllabus_F26.pdf", "syllabus"),
        ("Midterm 1 Study Guide", "mt1.pdf", "exams"),
        ("Lab 3", "lab3.pdf", "labs"),
        ("Lab 1 starter", "helloWorld.c", "labs"),
        ("text1", "hw1.pdf", "assignments"),
        ("HW2 starter", "hw2.c", "assignments"),
        ("helloWorld", "helloWorld.c", "code"),
        ("Lecture 2 demo", "demo.s", "code"),
        ("Lecture 1 - Data Representation", "lec1.pdf", "lectures"),
        ("Slides", "Week4.pptx - Google Slides.pptx", "lectures"),
        ("Chapter 2", "ch2.pdf", "readings"),
        ("dweight2", "dweight2", "other"),
        ("Available resources", "policy.pdf", "other"),
        ("Final Project", "final_project.pdf", "assignments"),
    ],
)
def test_classify(title, filename, bucket):
    assert classify(title, filename) == bucket


def test_every_result_is_a_known_bucket():
    assert classify("", None) in BUCKETS


def test_the_fallback_sees_the_title_and_filename_only_when_no_rule_matches():
    asked = []

    def fallback(title, filename):
        asked.append((title, filename))
        return "labs"

    assert classify("Lecture 3", "lec3.pdf", fallback) == "lectures"
    assert classify("dweight2", "dweight2.csv", fallback) == "labs"
    assert asked == [("dweight2", "dweight2.csv")]
