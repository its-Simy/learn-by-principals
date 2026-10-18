## Ticket

BL-0XX: <ticket title>

## What changed

-

## How it was checked

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `pnpm --dir web typecheck && pnpm --dir web build` (a web change)
- [ ] `uv run pytest -m e2e tests/e2e` (a promotion from `dev` to `main`)

## Decision log

- [ ] A principle was bent or a provider choice changed: a row is added to `CLAUDE.md`'s decision log
- [ ] Not needed
