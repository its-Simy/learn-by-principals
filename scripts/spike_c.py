"""Spike C (throwaway): notebooklm-py on the Android backend, end to end.

Setup (once):
    uv pip install "notebooklm-py[android,browser]"
    brightlearn dev nlm-login --account <gmail>

Run (after uploading the syllabus, so it is in the manifest):
    .venv/bin/python scripts/spike_c.py

Like the provider, the script points NOTEBOOKLM_HOME at ~/.brightlearn/notebooklm itself.

Paste the output into docs/spike_c_results.md.

Imports notebooklm directly on purpose: the spike exists to learn the raw library before the
provider in core/providers/knowledge/ wraps it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import time
import traceback
from pathlib import Path

os.environ["NOTEBOOKLM_HOME"] = str(Path.home() / ".brightlearn" / "notebooklm")

from notebooklm import AudioFormat, AudioLength, NotebookLMClient  # noqa: E402

NOTEBOOK_TITLE = "BrightLearn-spike"
QUESTION = "What is the grading breakdown?"
PROMPT = "Cover only grading policy and exam dates."


def syllabus_from_manifest(db_path: Path, course: str) -> Path:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT local_path FROM resources WHERE course = ? AND bucket = 'syllabus'"
        " AND local_path IS NOT NULL ORDER BY added_at LIMIT 1",
        (course,),
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"No uploaded syllabus for {course} in {db_path}; upload it first")
    return Path(row[0])


class Steps:
    def __init__(self) -> None:
        self.timings: list[tuple[str, float, str]] = []

    async def run(self, name: str, coro):
        print(f"\n=== {name}")
        t0 = time.monotonic()
        try:
            result = await coro
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"!!! {type(exc).__module__}.{type(exc).__name__}: {exc}")
            traceback.print_exc()
            self.timings.append((name, elapsed, f"FAILED {type(exc).__name__}"))
            return None
        elapsed = time.monotonic() - t0
        self.timings.append((name, elapsed, "ok"))
        print(f"--- {elapsed:.1f}s")
        return result

    def summary(self) -> None:
        print("\n=== Timings")
        for name, elapsed, outcome in self.timings:
            print(f"{elapsed:8.1f}s  {outcome:<24} {name}")


async def main(args: argparse.Namespace) -> None:
    pdf = args.file or syllabus_from_manifest(args.db, args.course)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"file: {pdf} ({pdf.stat().st_size} bytes)")
    steps = Steps()

    async with NotebookLMClient.from_storage(args.storage, backend=args.backend) as client:
        print(f"backends: {dict(client.backends)}")

        # 1. notebook (reused if a previous spike run created it)
        notebooks = await steps.run("notebooks.list()", client.notebooks.list())
        nb = next((n for n in notebooks or [] if n.title == NOTEBOOK_TITLE), None)
        if nb is None:
            nb = await steps.run(
                f"notebooks.create({NOTEBOOK_TITLE!r})", client.notebooks.create(NOTEBOOK_TITLE)
            )
        else:
            print(f"reusing notebook {nb.id}")
        if nb is None:
            steps.summary()
            return
        print(f"notebook: id={nb.id} title={nb.title!r} sources_count={nb.sources_count}")

        # 2. add the syllabus
        source = await steps.run(
            "sources.add_file(wait=True)", client.sources.add_file(nb.id, pdf, wait=True)
        )
        if source is not None:
            print(f"source: id={source.id} title={source.title!r} status={source.status!r}")

        # 3. list sources
        sources = await steps.run("sources.list()", client.sources.list(nb.id))
        for s in sources or []:
            print(f"  {s.id}  {s.kind}  {s.status!r}  {s.title!r}  created={s.created_at}")

        # 4. grounded question
        answer = await steps.run(f"chat.ask({QUESTION!r})", client.chat.ask(nb.id, QUESTION))
        if answer is not None:
            print(f"answer (conversation {answer.conversation_id}, turn {answer.turn_number}):")
            print(answer.answer)
            for ref in answer.references:
                print(
                    f"  [{ref.citation_number}] {ref.source_id}: {(ref.cited_text or '')[:160]!r}"
                )

        # 5. audio overview from a prompt file
        prompt_file = out_dir / "spike_prompt.md"
        prompt_file.write_text(PROMPT + "\n", encoding="utf-8")
        status = await steps.run(
            "artifacts.generate_audio(brief, short)",
            client.artifacts.generate_audio(
                nb.id,
                instructions=prompt_file.read_text(encoding="utf-8"),
                audio_format=AudioFormat.BRIEF,
                audio_length=AudioLength.SHORT,
            ),
        )
        if status is not None:
            print(f"generation: task_id={status.task_id} status={status.status}")
            done = await steps.run(
                "artifacts.wait_for_completion(timeout=1200)",
                client.artifacts.wait_for_completion(nb.id, status.task_id, timeout=1200),
            )
            if done is not None:
                print(f"completed: status={done.status} url={done.url} error={done.error}")
                audio = await steps.run(
                    "artifacts.download_audio()",
                    client.artifacts.download_audio(nb.id, str(out_dir / "spike_audio.m4a")),
                )
                if audio:
                    print(f"audio: {audio} ({Path(audio).stat().st_size} bytes)")

        # 6. remove and re-add: does the same file get a new source id?
        if source is not None:
            await steps.run("sources.delete()", client.sources.delete(nb.id, source.id))
            again = await steps.run(
                "sources.add_file(again)", client.sources.add_file(nb.id, pdf, wait=True)
            )
            if again is not None:
                print(f"re-added: old={source.id} new={again.id} same={again.id == source.id}")
            asked = await steps.run(
                "chat.ask() right after re-add", client.chat.ask(nb.id, QUESTION)
            )
            if asked is not None:
                print(f"references after re-add: {[r.source_id for r in asked.references]}")

    steps.summary()


if __name__ == "__main__":
    home = Path.home() / ".brightlearn"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", default="CSE220")
    parser.add_argument("--db", type=Path, default=home / "brightlearn.db")
    parser.add_argument("--file", type=Path, help="Use this file instead of the manifest syllabus")
    parser.add_argument("--storage", help="storage_state.json path (default: NOTEBOOKLM_HOME)")
    parser.add_argument("--backend", default="android", choices=["android", "web"])
    parser.add_argument("--out", type=Path, default=Path("/tmp/brightlearn-spike"))
    asyncio.run(main(parser.parse_args()))
