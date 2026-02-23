# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Gogetlinks Task Parser — automated scraper for gogetlinks.net task marketplace. Authenticates (with reCAPTCHA solving via anti-captcha.com), parses task listings and detail modals via Selenium, sends Telegram notifications for new tasks, stores in MySQL with deduplication. Runs unattended via cron.

## Commands

```bash
make install          # Create venv + install deps
make install-dev      # Install dev deps (pytest, black, flake8, mypy)
make setup-config     # Create config.ini from template (chmod 600)
make setup-db         # Init MySQL database from schema.sql

make run              # Run parser
make run-debug        # Run with DEBUG logging

make test             # Run all tests
make test-cov         # Tests + coverage (requires >=80%)
make lint             # flake8
make format           # black (88 char lines)
make type-check       # mypy

make logs             # Last 50 log lines
make logs-errors      # Errors only
make db-tasks         # Query new tasks from DB
make backup-db        # Timestamped MySQL dump
```

## Architecture

Single-file monolith `gogetlinks_parser.py` (~1200 LOC) with logical modules:

1. **Config** — `load_config()`, `validate_config()` from INI file; includes `[telegram]` section with `mention` for tagging team members
2. **Database** — `connect_to_database()` (retry with backoff), `insert_or_update_task()` (upsert via ON DUPLICATE KEY UPDATE, returns is_new status)
3. **Auth** — `initialize_driver()` (headless Chrome), `authenticate()` with modal login form, `solve_captcha()` via anti-captcha.com API
4. **Parser** — `parse_task_list()` → `parse_task_row()` extracts fields from list; `parse_task_details()` opens AJAX modal per task and extracts description/url/requirements; `parse_price()` handles FREE/N/A/currency formats
5. **Telegram** — `format_telegram_message(tasks, mention)` formats compact HTML (type|price|domains), `send_telegram_notification()` sends via Bot API with configurable mention tags
6. **Main** — `main()` orchestrates: config → DB → driver → auth → parse list → parse details → save → notify → cleanup

Exit codes: 0=ok, 1=auth, 2=captcha, 3=config, 4=db, 5=webdriver, 99=unexpected.

Single MySQL table `tasks` with `task_id` UNIQUE constraint for deduplication. Schema in `schema.sql`.

## Key Conventions

Detailed rules live in `.claude/rules/` (coding-style, git-workflow, testing, security). The critical ones:

- **Formatting**: Black, 88 chars, 4 spaces. Type hints mandatory. Google-style docstrings.
- **Commits**: `type(scope): description` — types: feat, fix, refactor, test, docs, chore, style, perf
- **Security**: Never log credentials — use `mask_email()`. Parameterized SQL only (`%s` placeholders). `config.ini` is gitignored (chmod 600).
- **Testing**: pytest, AAA pattern, >=80% coverage. Mark slow/integration tests with `@pytest.mark`.

## Gotchas

- Auth uses **modal-based login form** (`rel='modal:open'`), not a standalone page
- Captcha solving is **optional** — parser continues if no captcha detected
- Site returns **Windows-1251** encoding
- Detail modal opened via `$.get(TASK_DETAIL_URL)` + jQuery `.modal()` — old modals must be removed before opening new ones
- Detail modal DOM: `.tv_params_block` blocks with `.block_title` headers; URL in `#copy_url` input; params in `.param .block_name/.block_value` pairs
- Title in list view is task type from `.site-link__campaign` (e.g. "Заметка", "Контекстная ссылка"), not a descriptive title
- `insert_or_update_task()` returns `Optional[bool]`: `True`=new, `False`=updated, `None`=error
- Telegram section in config is optional (fallback defaults if missing)
- Session persistence (cookie save/load) is **not yet implemented**
- Tests: 58 tests with real assertions (parser, details, telegram, html cleaning)
