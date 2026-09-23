# Spike C results — notebooklm-py on the Android backend

**Status: not run yet.** Paste the output of `scripts/spike_c.py` under "Run output" below.

## What the library source says (notebooklm-py 0.8.2, read Sept 23, 2026)

These signatures come from reading the 0.8.2 wheel, not from a live run. The run should confirm or correct them.

### Client and auth
- The library is async only. There is no sync client.
- Open a client with `async with NotebookLMClient.from_storage(path=None, *, backend="android"|"web") as client:`. Don't `await` `from_storage`; that form is deprecated.
- **Backend:**
  - Resolution order: the explicit `backend=` argument, then `$NOTEBOOKLM_BACKEND`, then `"web"`.
  - `client.backends` shows what was installed.
  - Android replaces every namespace. `rpc_call` stays on web.
- **Files:**
  - Credentials live in `$NOTEBOOKLM_HOME` (default `~/.notebooklm`).
  - Web cookies: `profiles/<profile>/storage_state.json`.
  - Master token: `master_token.json` in the same folder.
  - Web cookies are loaded even in Android mode. They are re-minted from the master token when expired.
- **Missing master token:** Android open raises `ConfigurationError`. A failed mint raises `AuthError`.
- **`notebooklm login --master-token --account <gmail>`:**
  1. Opens a browser at `accounts.google.com/EmbeddedSetup` and captures `oauth_token`.
  2. Exchanges it for a master token.
  3. Writes both files and verifies by listing notebooks.
- **There is no `notebooklm auth status`.** The nearest command is `notebooklm auth check [--test] [--json]`. It exits 0 when every check passes. It validates web cookies only, not the Android bearer.

### Calls used by the provider
| Need | Call |
| --- | --- |
| list / create notebook | `notebooks.list() -> list[Notebook]`, `notebooks.create(title) -> Notebook` (`id`, `title`, `created_at`, `sources_count`). There's no find-by-title. |
| add file | `sources.add_file(notebook_id, file_path, mime_type=None, *, wait=False, wait_timeout=120.0, title=None) -> Source` |
| list sources | `sources.list(notebook_id) -> list[Source]` (`id`, `title`, `kind`, `status`, `created_at`) |
| remove source | `sources.delete(notebook_id, source_id)`. Needs the notebook id. Idempotent. |
| refresh source | `sources.refresh(notebook_id, source_id)` |
| full text | `sources.get_fulltext(notebook_id, source_id) -> SourceFulltext` (`.content`) |
| ask | `chat.ask(notebook_id, question, source_ids=None, conversation_id=None) -> AskResult` (`answer`, `references[ChatReference(source_id, cited_text, citation_number, …)]`) |
| audio | `artifacts.generate_audio(notebook_id, source_ids=None, language="en", instructions=None, audio_format=AudioFormat.BRIEF, audio_length=AudioLength.SHORT) -> GenerationStatus` |
| wait | `artifacts.wait_for_completion(notebook_id, task_id, timeout=300.0)` raises `ArtifactTimeoutError` |
| download | `download_audio`, `download_quiz(output_format="json")`, `download_flashcards(output_format="json")`, `download_report` (Markdown), `download_slide_deck(output_format="pdf")`, `download_mind_map` (JSON). Each has the signature `(notebook_id, output_path, artifact_id=None)`; `None` means the latest completed artifact. |
| quiz / flashcards | `generate_quiz` / `generate_flashcards(notebook_id, source_ids=None, instructions=None, quantity=QuizQuantity.*, difficulty=QuizDifficulty.*)` |
| report / slides / mind map | `generate_report(notebook_id, report_format=ReportFormat.*, …, custom_prompt=None)`, `generate_slide_deck(…, instructions=None)`, `generate_mind_map(…, instructions=None)` (synchronous) |

### Quirks known from the source
- **Audio format:** the download is **AAC in an MP4 container (`.m4a`), not MP3**. On Android, a WAV payload is also accepted.
- **Follow-up questions:** `chat.ask` without `conversation_id` continues the most recent conversation. Every BrightLearn question becomes a follow-up of the previous one.
- **File types:**
  - Supported upload extensions: `.csv .docx .epub .md .markdown .pdf .pptx .txt`.
  - Android stages `.csv .docx .pptx` through Drive. That path always waits and creates a Drive-backed source.
  - Other extensions (`.c`, `.s`, …) are not supported.
- **Rate limits:**
  - Android maps `RESOURCE_EXHAUSTED` to `RateLimitError` and never retries it.
  - Web retries HTTP 429 up to 3 times.
- **Exceptions:** all of them derive from `NotebookLMError`, except `MasterTokenError`, which is a plain `Exception`.

## Run output

```
(paste here)
```

## Questions the run should answer
- Did every step succeed on `--backend android`? Which fell back to web, if any?
- How long after `add_file(wait=True)` returns can the source be queried?
- How long did the audio take to generate, and what was the downloaded file's format and extension?
- Does a re-added file get a new source id? Does the old id still show up in citations?
- Did any rate-limit errors appear?
