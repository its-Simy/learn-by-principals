# Validation log: running BrightLearn against real accounts

Every piece so far was built against fakes. This log records each manual step the first time it runs against real NotebookLM, Claude Code and Codex, mostly through the web app. Fill in an entry as you go, and don't tidy up failures: a failed step with a clear output summary is the most useful entry here.

Run the entries in order: each one depends on the ones before it. To rehearse the web app first, with no accounts and no quota, run `scripts/dev_server.py` against a scratch home (see `web/README.md`); nothing it does counts as an entry here.

Paths are the defaults: `~/.brightlearn/` holds the database, `courses/`, `vault/` and `notebooklm/`. CSE220's term folder is `Fall-2026`, the term it is created with in step 2.

## How to fill in an entry

- **Command:** exactly what you ran, including flags. For a step in the browser, what you clicked, in order.
- **Expected:** already filled in below. It's what passing looks like.
- **Output summary:** the few lines that matter, not the whole log. Include error messages word for word. Remove anything secret: no cookies, tokens, email addresses or file contents.
- **Problems opened:** each new `P` number you (or I) add to `problems.md` because of this step.
- **Tickets created:** each new `BL-0XX` this step caused.
- **Status:** `not run`, `pass`, `pass with problems`, or `fail`.

## Entry template

Copy this block for any step not listed below.

```markdown
### N. <step name>
- **Date:**
- **Command:**
- **Expected:**
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run
```

---

## Entries

### 1. NotebookLM login, then doctor
- **Date:**
- **Command:**
  ```
  env -u CONDA_PREFIX uv pip install --python .venv/bin/python "notebooklm-py[android,browser]"
  brightlearn dev nlm-login --account <gmail>
  brightlearn doctor
  ```
  `nlm-login` opens a browser for the Google login. Doctor never does: every check is read-only and spends no quota. Before the install, doctor's NotebookLM row suggests a bare `uv pip install`; use the line above instead, or it lands in the conda base env (P103).
- **Expected:**
  - Credentials land in `~/.brightlearn/notebooklm/`, not `~/.notebooklm/` (P20).
  - Doctor has nine rows: Config, DB schema, Storage root, Temp dir, `ANTHROPIC_API_KEY`, NotebookLM, Claude Code, Codex and Ollama.
  - NotebookLM is green.
  - `ANTHROPIC_API_KEY` is green (unset). Red means the key is exported: unset it before going on, or Claude Code would bill the API (principle 1).
  - Config is green and names the term new courses get, e.g. `term Fall-2026`. Storage root and Temp dir are green.
  - DB schema is yellow, "no database yet; `brightlearn courses add` creates it", on a machine with no database: step 2 creates it. On one that has a database, it's green at v13, or yellow saying it migrates to v13 on the next run.
  - Claude Code and Codex are yellow (not on PATH) until step 4 installs them. Green only means `--version` ran: doctor never checks the login, because that would spend quota.
  - Ollama is an optional yellow warning.
  - Doctor exits 0. It exits 1 only when a row is red.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 2. Create CSE220 and upload files in the web app
- **Date:**
- **Command:**
  ```
  pnpm --dir web install && pnpm --dir web build
  brightlearn web
  ```
  It serves `http://127.0.0.1:8765/` and opens it. In the browser:
  1. **New course:** Course code `CSE220`, Name `Systems Fundamentals I`, Term left at `Fall-2026`. **Create course.**
  2. Open the CSE220 card. With **Auto bucket** selected, drop the syllabus and two lectures on the Sources pane (or use **Upload**).
  3. Upload one of the lectures again, unchanged.

  Then, in a second terminal:
  ```
  brightlearn courses list
  brightlearn doctor
  ```
  The CLI equivalent of the first click is `brightlearn courses add CSE220 --name "Systems Fundamentals I"`; files come in through the web app only.
- **Expected:**
  - **Before uploading:** the home grid shows a CSE220 card, "CSE220 · Fall-2026", "0 sources · 0 linked · 0 concepts". The Sources pane says "Upload the syllabus to start." and the chat "Upload course files to ask about them."
  - **Upload:** each file shows a pending row until it's stored, then a source row with its bucket badge: `syllabus`, `lectures`, `lectures`. The link bar shows "Linking to NotebookLM" with the elapsed time ("typically a few seconds a file") while the badges read "linking". It ends "Sources: 3 linked", with three "linked" badges. Nothing is "deferred": that only happens past the 50-source cap.
  - **The unchanged re-upload:** no new row, the badge stays "linked", and its link job ends "Sources already up to date". This is the old "second run skips everything" check (P16, P93).
  - **On disk:** the files are in `~/.brightlearn/courses/Fall-2026/CSE220/syllabus/` and `~/.brightlearn/courses/Fall-2026/CSE220/lectures/`. `courses list` shows CSE220, term `Fall-2026`, 3 files, and that folder.
  - **Doctor afterwards:** DB schema is green at v13. Temp dir is green, so `/tmp/brightlearn` was emptied after the uploads.
  - **Home again:** the card reads "3 sources · 3 linked · 0 concepts".
  - **Check by hand:** if a file landed in the wrong bucket, note its name and the bucket. A file NotebookLM rejects shows "failed" with the reason and a Retry button (P32).
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 3. Spike C, then the provider's own check
- **Date:**
- **Command:**
  ```
  .venv/bin/python scripts/spike_c.py
  brightlearn dev nlm-test
  ```
  Both read the syllabus uploaded in step 2 from the manifest.
- **Expected:**
  - The spike creates or finds `BrightLearn-spike`, adds the syllabus, answers "What is the grading breakdown?" with citations, generates audio from the prompt file on the Android backend, then removes and re-adds the syllabus and reports whether the source id changed.
  - `nlm-test` covers the first three of those through `GeminiNotebookProvider`: find the notebook, add the syllabus, ask the same question. It removes its source afterwards (P18, P22). No audio and no re-add: those are only in the spike.
  - Both use the `BrightLearn-spike` notebook, never CSE220's.
  - Paste the spike's output into `docs/spike_c_results.md`, and note anything that disagrees with what that file says the library does.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 4. Capture the model CLI outputs for BL-039
- **Date:**
- **Command:** Install the `claude` CLI on PATH (P49) and Codex (P52), check `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are unset, then capture exactly what the providers will parse:
  ```
  claude -p "Say hi" --output-format json --tools "" --no-session-persistence > claude_hi.json
  codex --help > codex_help.txt
  codex exec --skip-git-repo-check --sandbox read-only --color never -o codex_last.txt "Say hi" > codex_hi.txt 2>&1
  ```
  `-o` matters: `CodexProvider` reads the reply from that file and uses stdout and stderr only for the `model:` and `tokens used` lines. Paste all four files (`claude_hi.json`, `codex_help.txt`, `codex_hi.txt`, `codex_last.txt`) into the chat; they become `tests/fixtures/cli/`.
- **Expected:**
  - `claude_hi.json` is one JSON object with `result`, `subtype`, `usage` and `modelUsage` (P50).
  - `codex_hi.txt` holds the run's header and footer; `codex_last.txt` holds only the final message (P52).
  - Any usage-limit wording you run into goes into P50 or P52.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 5. BL-039: model-test
- **Date:**
- **Command:** After BL-039 lands:
  ```
  brightlearn dev model-test claude "Say hi"
  brightlearn dev model-test codex "Say hi"
  brightlearn doctor
  ```
- **Expected:**
  - Both model tests print a reply with the provider, the model name (read from the output, never hardcoded) and a duration.
  - Each run is one row in `model_runs`.
  - Doctor shows Claude Code and Codex green.
  - Any usage-limit wording you run into goes into P50 or P52.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 6. Seed and apply CSE220's concepts from the Studio pane
- **Date:**
- **Command:** In the browser, on CSE220's Studio pane:
  1. **Seed** in the Concepts card (or in the Mastery card's empty state).
  2. Open the new draft from the Concepts card's list. Click **Apply** once before editing.
  3. In the draft view, fix names, modules and weeks; add `aliases:` for any renames; set `reviewed: true`. **Save.**
  4. **Apply**, then **Apply** again.

  The CLI does the same:
  ```
  brightlearn concepts seed --course CSE220
  # edit the newest ~/.brightlearn/vault/courses/CSE220/concepts.draft.*.yaml
  brightlearn concepts apply --course CSE220
  ```
- **Expected:**
  - **Seed:** a "Seeding concepts" row with the elapsed time, then "Concept draft ready: N concepts". The draft is a new `~/.brightlearn/vault/courses/CSE220/concepts.draft.{timestamp}.yaml`, listed as "latest" and "needs review"; it never overwrites an earlier one (P65). The draft view shows the changes from the draft before it, or says it's the first.
  - **Apply before review:** refused with the reason (the draft still says `reviewed: false`); nothing changes.
  - **Save:** a YAML mistake (a bad indent, `week: two`) shows its error under the editor and leaves the file as it was.
  - **First apply:** "Applied: N added · 0 updated · 0 unchanged · 0 retired". The Concepts card reads "N active · 0 retired"; the Mastery card reads "N concepts · N below level 3" and lists the weakest five.
  - **Second apply:** "Applied: 0 added · 0 updated · N unchanged · 0 retired".
  - **CLI instead:** the first `apply` prints "Applied concepts.draft.{timestamp}.yaml: N added, 0 updated, 0 retired (0 unchanged)." `seed` refuses while a tutor session is open on CSE220.
  - Every concept has a week, because exam specs select concepts by week (P74).
  - **Check by hand:** whether the concept list reads like the syllabus (P47).
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 7. A tutor session in the Chat pane
- **Date:**
- **Command:** In the browser, on CSE220:
  1. With no session, uncheck both lectures in the Sources pane, so only the syllabus is checked (every linked source starts checked), and ask "What is the grading breakdown?".
  2. **Start session** with the Simplifier persona. If a Challenger question is waiting, answer it.
  3. Five turns on pointers.
  4. Rate the last answer with the 1–5 buttons under it.
  5. Turn on **Sources only**, ask one question, and turn it off again.
  6. While the session is live, click **Seed** in the Studio's Concepts card.
  7. **End session.**
  8. Open **History**, then the session's **Transcript**.

  Then:
  ```
  brightlearn sessions list --course CSE220
  brightlearn dashboard
  ```
  The CLI session is `brightlearn tutor --course CSE220 --persona simplifier`, with `/ask`, `/rate 1-5`, `/skip` and `/end`.
- **Expected:**
  - **The ask before the session:** the answer is captioned "Sources · 1 selected source", with citation chips such as `[1] <syllabus file>`. A chip opens its excerpt on click, and on Tab then Enter.
  - **Start:** the note "Tutoring session started with the simplifier persona." and a "live session" badge with the persona and start time. A waiting probe shows "Challenger question on <concept>. Your next message is your answer." with **Skip**. None waits on the first session: the Analyzer queues them when a session ends.
  - **Each turn:** a pending bubble with the step and elapsed time ("Simplifier is answering · 14 s"), the composer disabled, then a Markdown answer grounded in the course sources and routed to Claude (or Codex on fallback). The page doesn't name the provider during the session; History does once it has ended.
  - **Rate:** the buttons give way to "Rated the last answer 4/5." (your number).
  - **Sources only:** the answer is captioned "Sources · every source", with chips and the note that scoping is off during a session: it was asked in the session's own NotebookLM conversation (P66).
  - **Seed while live:** refused with a note, "Tutor session … is open on CSE220 …; NotebookLM keeps one live conversation per course." Nothing is queued.
  - **End:** "Analyzer is reading the transcript" with the elapsed time (a few minutes is normal), then a note: "Session ended." and the Analyzer's summary from the *other* provider. It may add "N challenge(s) queued for next session."
  - **Vault:** the transcript `~/.brightlearn/vault/sessions/<session_id>.md` and `<session_id>.summary.md`.
  - **History:** the session is ended, with "Tutor: claude · Analyzer: codex" (different after a fallback, but never one provider for both); **Transcript** opens it in a dialog.
  - **`sessions list`:** shows the session as ended.
  - **Dashboard:** `brightlearn dashboard`, and the System page (`/system`), show the runs, provider health and the rating (P61).
  - **Check by hand:** do the evidence excerpts quote your own words? A concept's name in the Mastery card opens its evidence rows, but without their excerpts (P103), so read those with `sqlite3 ~/.brightlearn/brightlearn.db "SELECT concept_id, type, excerpt_ref FROM evidence WHERE session_id = '<session_id>'"`.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 8. An exam from the Studio pane
- **Date:**
- **Command:** In the browser, on CSE220's Studio pane:
  1. **New exam** in the Practice exams card. The editor opens with a template for CSE220 (Midterm 1, weeks 1–5). For a shorter first run, set `formats: {multiple_choice: 6, short_answer: 3, coding: 1}`. **Create.**
  2. Once the exam's row appears: **Paper**, then **Take** and **Start**. Answer a few questions, reload the page, then carry on to the last question, skipping one on the way, and **Finish**.
  3. **Grade**, then **Results**.

  The CLI does the same with the template's text saved outside the repo, e.g. as `~/.brightlearn/exams/cse220-midterm1.yaml`:
  ```
  brightlearn exam create --spec ~/.brightlearn/exams/cse220-midterm1.yaml
  brightlearn exam take ~/.brightlearn/vault/courses/CSE220/exams/<exam>.json
  brightlearn exam grade ~/.brightlearn/vault/courses/CSE220/exams/<exam>.json
  ```
  Whichever way you go, run `exam grade` on the graded exam once more from the CLI.
- **Expected:**
  - **Create:** a mistake in the spec (an unknown key, another course) shows under the editor and starts no job. A valid spec shows "Generating exam" with the elapsed time, then "Exam ready: 10 questions" (fewer if any were dropped; the CLI reports "10 of 10 questions" or lists them). It's generated on one provider and critiqued on the other: the row has a "critiqued" badge, and the exam's JSON in `~/.brightlearn/vault/courses/CSE220/exams/` says `"review": "critiqued"`.
  - **Paper:** the "Paper with answer key" dialog, the key at the end. The exam's `.md`, next to its JSON, has the same key.
  - **Take:** opens at `/courses/CSE220/exams/<exam>/take`, "10 questions · not taken yet", then after **Start** one question at a time ("Attempt 1 · 1 of 10"): multiple choice as radio buttons, short answers in a text box, coding in a monospace one. After the reload it resumes on the same question with the answers kept. **Finish** shows "Attempt 1 handed in · 9 answered, 1 skipped". (The CLI's `take` stops with `/quit` and resumes.)
  - **Grade:** "Grading exam", then "Graded: X of Y correct", and one evidence row per answered question. While it runs, the take view's **Take again** is refused with "Grading is in progress on this course. Your answers are saved; carry on once it has finished." (P101).
  - **Results:** each concept with its correct count and level, and each question with your answer, the feedback and the reference answer.
  - **Grading again:** the CLI writes no new evidence: "0 new evidence row(s); 9 answer(s) were already graded." In the web app, the card's Grade is disabled once the attempt is graded ("Attempt 1 is graded"), and the take view no longer offers it.
  - **Check by hand:** are the questions grounded, and is the answer key right?
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 9. A podcast from the Audio Overview card
- **Date:**
- **Command:** In the browser, on CSE220's Studio pane, in the Audio Overview card: Format **Deep dive**, Length **Default**, Exam **Midterm 1**. **Generate.** Once it's ready, play the episode and open its **Brief**.
  The CLI equivalent: `brightlearn podcast --course CSE220 --exam "Midterm 1"`.
- **Expected:**
  - "Generating audio overview" with the elapsed time ("typically 5–15 minutes"), then "Audio overview ready".
  - The episode row shows its date and "On <the concepts it targeted>", and plays in the page's audio player. Its Brief is the instructions NotebookLM was given.
  - **On disk:** `<stamp>-podcast.md` and `<stamp>-podcast.m4a` in `~/.brightlearn/courses/Fall-2026/CSE220/_generated/`, and one `podcasts` row.
  - Audio starts no NotebookLM conversation, so a podcast is never refused because a tutor session is open.
  - **Check by hand:** does the episode talk about the concepts the brief names?
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run
