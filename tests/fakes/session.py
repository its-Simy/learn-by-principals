from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from core.providers.lms.session import WHOAMI_PATH, HttpResponse

BASE_URL = "https://mycourses.example.edu"
FIXTURES = Path(__file__).parent.parent / "fixtures"

Route = HttpResponse | Callable[[], HttpResponse]


def json_response(path: str, payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        url=BASE_URL + path,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload).encode(),
    )


def fixture_response(path: str, fixture: str) -> HttpResponse:
    return json_response(path, json.loads((FIXTURES / fixture).read_text()))


def login_redirect() -> HttpResponse:
    return HttpResponse(
        status=200,
        url=BASE_URL + "/d2l/login?target=%2fd2l%2fhome",
        headers={"content-type": "text/html"},
        body=b"<html>login</html>",
    )


class FakeSession:
    """Serves canned responses by exact path; ``logged_in`` controls whoami and every route."""

    def __init__(self, routes: dict[str, Route] | None = None, logged_in: bool = True) -> None:
        self.base_url = BASE_URL
        self.routes: dict[str, Route] = dict(routes or {})
        self.logged_in = logged_in
        self.logins = 0
        self.requests: list[str] = []

    def get(self, path: str) -> HttpResponse:
        self.requests.append(path)
        if path == WHOAMI_PATH:
            if not self.logged_in:
                return login_redirect()
            return json_response(path, {"Identifier": "1", "FirstName": "Test"})
        if not self.logged_in:
            return login_redirect()
        route = self.routes.get(path)
        if route is None:
            return HttpResponse(status=404, url=BASE_URL + path)
        return route() if callable(route) else route

    def whoami_ok(self) -> bool:
        return self.get(WHOAMI_PATH).status == 200 and self.logged_in

    def login(self) -> None:
        self.logins += 1
        self.logged_in = True

    def close(self) -> None:
        pass
