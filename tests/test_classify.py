import pytest

from core.providers.lms.base import Resource
from core.sync.classify import BUCKETS, classify


def res(module_path: str, title: str) -> Resource:
    return Resource(1, 1, module_path, title, "File", None, None)


@pytest.mark.parametrize(
    ("module_path", "title", "filename", "bucket"),
    [
        ("Course Information", "Syllabus", "CSE220_Syllabus_F26.pdf", "syllabus"),
        ("Exams", "Midterm 1 Study Guide", "mt1.pdf", "exams"),
        ("Week 3", "Lab 3", "lab3.pdf", "labs"),
        ("Labs", "helloWorld", "helloWorld.c", "labs"),
        ("Week 1 / Homework", "text1", "hw1.pdf", "assignments"),
        ("Week 2", "HW2 starter", "hw2.c", "assignments"),
        ("Week 1", "helloWorld", "helloWorld.c", "code"),
        ("Lecture 2", "demo", "demo.s", "code"),
        ("Week 1", "Lecture 1 - Data Representation", "lec1.pdf", "lectures"),
        ("Week 4", "Slides", "Week4.pptx - Google Slides.pptx", "lectures"),
        ("Readings", "Chapter 2", "ch2.pdf", "readings"),
        ("Week 1", "dweight2", "dweight2", "other"),
        ("Collaboration policy", "Available resources", "policy.pdf", "other"),
        ("Projects", "Final Project", "final_project.pdf", "assignments"),
    ],
)
def test_classify(module_path, title, filename, bucket):
    assert classify(res(module_path, title), filename) == bucket


def test_every_result_is_a_known_bucket():
    assert classify(res("", ""), None) in BUCKETS
