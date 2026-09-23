import hashlib

import pytest

from core.providers.lms.base import LMSError, Resource
from core.providers.lms.brightspace import (
    ENROLLMENTS_PATH,
    VERSIONS_PATH,
    BrightspaceSessionProvider,
    course_code,
    filename_from_disposition,
)
from core.providers.lms.session import HttpResponse, is_whoami_ok
from core.providers.state import ProviderState
from tests.fakes.session import BASE_URL, FakeSession, fixture_response

TOC_PATH = "/d2l/api/le/1.97/100001/content/toc"
FILE_PATH = "/d2l/api/le/1.97/100001/content/topics/5003/file"


def make_session(**kwargs) -> FakeSession:
    page2 = f"{ENROLLMENTS_PATH}?orgUnitTypeId=3&bookmark=bm-1"
    session = FakeSession(
        {
            VERSIONS_PATH: fixture_response(VERSIONS_PATH, "versions.json"),
            f"{ENROLLMENTS_PATH}?orgUnitTypeId=3": fixture_response(
                ENROLLMENTS_PATH, "myenrollments_page1.json"
            ),
            page2: fixture_response(page2, "myenrollments_page2.json"),
            TOC_PATH: fixture_response(TOC_PATH, "toc.json"),
        },
        **kwargs,
    )
    return session


def resource(topic_id: int = 5003, title: str = "helloWorld") -> Resource:
    return Resource(100001, topic_id, "Week 1", title, "File", None, "2026-08-25T09:05:00.000Z")


def test_le_version_comes_from_versions_endpoint():
    assert BrightspaceSessionProvider(make_session()).le_version() == "1.97"


def test_list_courses_pages_and_keeps_only_active_course_offerings():
    courses = BrightspaceSessionProvider(make_session()).list_courses()
    assert [(c.org_unit_id, c.code) for c in courses] == [
        (100001, "CSE220"),
        (100003, "WRTSEM-F26"),
    ]


def test_list_resources_flattens_nested_modules():
    resources = BrightspaceSessionProvider(make_session()).list_resources(100001)
    assert [r.topic_id for r in resources] == [5001, 5002, 5003, 5004, 5005]
    hw = resources[-1]
    assert hw.module_path == "Week 1 / Homework"
    assert hw.title == "text1"
    assert resources[3].type_identifier == "Link"


def test_download_uses_content_disposition_filename(tmp_path):
    body = b"int main(void) { return 0; }\n"
    session = make_session()
    session.routes[FILE_PATH] = HttpResponse(
        status=200,
        url=BASE_URL + FILE_PATH,
        headers={
            "content-type": "text/x-csrc",
            "content-disposition": "attachment; filename*=UTF-8''hello%20World.c",
        },
        body=body,
    )
    dest = tmp_path / "abc"
    result = BrightspaceSessionProvider(session).download(resource(), dest)
    assert result.filename == "hello World.c"
    assert result.md5 == hashlib.md5(body).hexdigest()
    assert result.size == len(body)
    assert dest.read_bytes() == body


def test_download_without_disposition_falls_back_to_title_plus_extension(tmp_path):
    session = make_session()
    session.routes[FILE_PATH] = HttpResponse(
        200, BASE_URL + FILE_PATH, {"content-type": "application/pdf"}, b"%PDF"
    )
    result = BrightspaceSessionProvider(session).download(resource(), tmp_path / "x")
    assert result.filename == "helloWorld.pdf"


def test_session_expiry_mid_run_pauses_for_login_and_retries():
    session = make_session()
    lms = BrightspaceSessionProvider(session)
    lms.le_version()
    session.logged_in = False
    assert len(lms.list_resources(100001)) == 5
    assert session.logins == 1


def test_forbidden_with_live_session_raises_without_login():
    session = make_session()
    session.routes[TOC_PATH] = HttpResponse(403, BASE_URL + TOC_PATH)
    with pytest.raises(LMSError, match="403"):
        BrightspaceSessionProvider(session).list_resources(100001)
    assert session.logins == 0


def test_ensure_session_opens_login_only_when_whoami_fails():
    live = make_session()
    BrightspaceSessionProvider(live).ensure_session()
    assert live.logins == 0

    expired = make_session(logged_in=False)
    BrightspaceSessionProvider(expired).ensure_session()
    assert expired.logins == 1


def test_health_never_logs_in():
    session = make_session(logged_in=False)
    assert BrightspaceSessionProvider(session).health() is ProviderState.AUTH_EXPIRED
    assert session.logins == 0


def test_whoami_redirected_to_login_page_is_not_ok():
    login_page = HttpResponse(200, BASE_URL + "/d2l/login", {"content-type": "text/html"}, b"")
    assert not is_whoami_ok(login_page, BASE_URL)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('attachment; filename="CSE220 Syllabus.pdf"', "CSE220 Syllabus.pdf"),
        (
            "attachment; filename*=UTF-8''Lecture%201%20%E2%80%94%20Bits.pptx",
            "Lecture 1 — Bits.pptx",
        ),
        ('attachment; filename="../../etc/passwd"', ".._.._etc_passwd"),
        ("inline", None),
        (None, None),
    ],
)
def test_filename_from_disposition(header, expected):
    assert filename_from_disposition(header) == expected


@pytest.mark.parametrize(
    ("org_unit", "expected"),
    [
        ({"Id": 1, "Code": "2268-CSE-220-01", "Name": "x"}, "CSE220"),
        ({"Id": 1, "Code": "F26_SEC01", "Name": "AMS 161: Calculus"}, "AMS161"),
        ({"Id": 1, "Code": "WRT/SEM", "Name": "Writing"}, "WRT_SEM"),
    ],
)
def test_course_code(org_unit, expected):
    assert course_code(org_unit) == expected
