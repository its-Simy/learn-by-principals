# Validation log: running BrightLearn against real accounts

Every piece so far was built against fakes. This log records each manual step the first time it runs against real Brightspace, NotebookLM, Claude Code and Codex. Fill in an entry as you go, and don't tidy up failures: a failed step with a clear output summary is the most useful entry here.

Run the entries in order: each one depends on the ones before it.

## How to fill in an entry

- **Command:** exactly what you ran, including flags.
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
  uv pip install "notebooklm-py[android,browser]"
  brightlearn dev nlm-login --account <gmail>
  brightlearn doctor
  ```
- **Expected:**
  - Credentials land in `~/.brightlearn/notebooklm/`, not `~/.notebooklm/` (P20).
  - Doctor's NotebookLM row is green.
  - Brightspace is green (`whoami 200`).
  - Chromium, Config, Storage root and Temp dir are green.
  - DB schema is green at v12, or yellow saying it migrates on the next run.
  - Claude Code and Codex stay yellow until step 4.
  - Ollama is an optional yellow warning.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 2. Sync CSE220 twice
- **Date:**
- **Command:**
  ```
  brightlearn sync --course CSE220
  brightlearn sync --course CSE220
  brightlearn doctor
  ```
  Use `--course`, not `--all`: past terms would be filed under Fall-2026 (P15).
- **Expected:**
  - **First run:** files land in `~/.brightlearn/courses/Fall-2026/CSE220/{bucket}/`. `Link` topics are counted, not downloaded. The NotebookLM table shows sources added, with `code` and `other` deferred.
  - **Second run:** every file is skipped, and NotebookLM adds or replaces nothing (P16).
  - **Doctor afterwards:** Temp dir is green, so `/tmp/brightlearn` was left empty.
  - **Check by hand:** if a file landed in the wrong bucket, note which one. P32 covers file types NotebookLM rejects.
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
- **Expected:**
  - The spike creates or finds `BrightLearn-spike`, adds the syllabus, answers "What is the grading breakdown?" with citations, and generates audio from the prompt file on the Android backend.
  - `nlm-test` does the same through `GeminiNotebookProvider` and removes its source afterwards (P18, P22).
  - Paste the spike's output into `docs/spike_c_results.md`, and note anything that disagrees with what that file says the library does.
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 4. BL-039: capture the model CLI outputs, then model-test
- **Date:**
- **Command:** Install the `claude` CLI on PATH (P49) and Codex (P52), check `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are unset, then capture exactly what the providers will parse:
  ```
  claude -p "Say hi" --output-format json --tools "" --no-session-persistence > claude_hi.json
  codex --help > codex_help.txt
  codex exec --skip-git-repo-check --sandbox read-only --color never "Say hi" > codex_hi.txt 2>&1
  ```
  Paste the three files into the chat (they become `tests/fixtures/cli/`). After BL-039 lands:
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
- **Status:** not run (blocked until the three outputs are pasted)

### 5. Seed and apply CSE220's concepts
- **Date:**
- **Command:**
  ```
  brightlearn concepts seed --course CSE220
  # edit the newest ~/.brightlearn/vault/courses/CSE220/concepts.draft.*.yaml:
  #   fix names, modules and weeks; add `aliases:` for any renames; set `reviewed: true`
  brightlearn concepts apply --course CSE220
  brightlearn concepts apply --course CSE220
  ```
- **Expected:**
  - **Seed:** writes a new timestamped draft and never overwrites an earlier one (P65). It refuses if a tutor session is open on CSE220.
  - **First apply:** prints "N added, 0 updated, 0 retired".
  - **Second apply:** prints "0 added, 0 updated, 0 retired (N unchanged)".
  - Every concept has a week, because exam specs select concepts by week (P74).
  - **Check by hand:** whether the concept list reads like the syllabus (P47).
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 6. First tutor session
- **Date:**
- **Command:**
  ```
  brightlearn tutor --course CSE220 --persona simplifier
  #   five turns on pointers, one /ask, one /rate 1-5, then /end
  brightlearn sessions list
  brightlearn dashboard
  ```
- **Expected:**
  - **Each turn:** the answer is grounded in course sources and routed to Claude (or Codex on fallback).
  - **`/ask`:** answers with citations inside the same NotebookLM conversation.
  - **`/end`:** prints the Analyzer's summary from the *other* provider. It may also queue challenges.
  - **Vault:** the transcript and `.summary.md` land in `~/.brightlearn/vault/sessions/`.
  - **`sessions list`:** shows the session as ended.
  - **Dashboard:** shows the runs, provider health and the rating (P61).
  - **Check by hand:** do the evidence excerpts quote your own words?
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run

### 7. First exam
- **Date:**
- **Command:** Write a spec outside the repo, e.g. `~/.brightlearn/exams/cse220-midterm1.yaml`:
  ```yaml
  course: CSE220
  exam: Midterm 1
  weeks: [1, 2, 3, 4, 5]
  sources: [syllabus, study-guides, lectures]
  formats: {multiple_choice: 6, short_answer: 3, coding: 1}
  difficulty: {easy: 30, medium: 50, hard: 20}
  mode: realistic
  ```
  Then run:
  ```
  brightlearn exam create --spec ~/.brightlearn/exams/cse220-midterm1.yaml
  brightlearn exam take ~/.brightlearn/vault/courses/CSE220/exams/<exam>.json
  brightlearn exam grade ~/.brightlearn/vault/courses/CSE220/exams/<exam>.json
  brightlearn exam grade ~/.brightlearn/vault/courses/CSE220/exams/<exam>.json
  ```
- **Expected:**
  - **`create`:** reports "10 of 10 questions", or lists any it dropped. It's generated on one provider and critiqued on the other. The exam JSON says `"review": "critiqued"`.
  - **The `.md`:** has the answer key at the end.
  - **`take`:** can be stopped with `/quit` and resumed.
  - **First `grade`:** prints a score per concept and writes one evidence row per answered question.
  - **Second `grade`:** writes no new evidence.
  - **Check by hand:** are the questions grounded, and is the answer key right?
- **Output summary:**
- **Problems opened:**
- **Tickets created:**
- **Status:** not run
