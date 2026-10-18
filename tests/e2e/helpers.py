"""Shared by the tour modules: a dev server's handle, the seeded course, locators by role."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Locator, Page

STOP_TIMEOUT_S = 10.0

COURSE = "CSE220"
COURSE_NAME = "Systems Fundamentals I"
COURSE_URL = f"/courses/{COURSE}"
# dev_server.py's seeded files.
SEEDED_FILES = ("CSE220 Syllabus.md", "HW1 Bit Manipulation.txt", "Lecture 3 - Pointers.md")


@dataclass
class DevServer:
    """One ``scripts/dev_server.py`` process and where it keeps its files."""

    url: str
    home: Path
    log: Path
    process: subprocess.Popen[bytes]

    def stop(self) -> None:
        """SIGTERM to its process group, then SIGKILL if it hasn't exited in 10 s. Idempotent."""
        if self.process.poll() is not None:
            return
        try:
            if os.name == "nt":
                self.process.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            self.process.wait(STOP_TIMEOUT_S)
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                self.process.kill()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            self.process.wait(STOP_TIMEOUT_S)


def studio(page: Page) -> Locator:
    """The Studio rail (open beside the chat at desktop width)."""
    return page.get_by_role("complementary", name="Studio")


def sources(page: Page) -> Locator:
    """The Sources rail."""
    return page.get_by_role("complementary", name="Sources")


def tiles(scope: Page | Locator) -> Locator:
    """The Studio home's four tiles, in order: Mastery, Practice exam, Audio Overview, Concepts."""
    return scope.locator("button[data-studio-opener]")


def course_files(page: Page) -> Locator:
    """The rows of the Sources rail's file list."""
    return page.get_by_role("list", name="Course files").get_by_role("listitem")


def file_row(page: Page, name: str) -> Locator:
    return course_files(page).filter(has_text=name)


def upload(page: Page, name: str, text: str, mime: str = "text/markdown") -> None:
    """Picks one file in the Sources rail's (visually hidden) file input."""
    page.locator("input[type=file]").set_input_files(
        {"name": name, "mimeType": mime, "buffer": text.encode()}
    )


def composer(page: Page) -> Locator:
    return page.get_by_role("textbox", name="Message")


def send(page: Page, text: str) -> None:
    """Types a chat message and sends it with Enter."""
    box = composer(page)
    box.fill(text)
    box.press("Enter")


def conversation(page: Page) -> Locator:
    """The chat's messages."""
    return page.get_by_role("log", name="Conversation")


def choose(scope: Page | Locator, combobox_name: str, option_name: str) -> None:
    """Picks an option of a Radix Select: there is no native <select>, so no select_option()."""
    scope.get_by_role("combobox", name=combobox_name).click()
    page = scope if isinstance(scope, Page) else scope.page
    # The listbox is portalled to <body>, outside any rail or dialog.
    page.get_by_role("option", name=option_name, exact=True).click()


def system_section(page: Page, title: str) -> Locator:
    """A /system card by its title ("Doctor", "Provider health", ...)."""
    return page.locator("[data-slot=card]").filter(
        has=page.locator("[data-slot=card-title]").get_by_text(title, exact=True)
    )
