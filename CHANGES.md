# Changelog

## 2026-03-05 - v1.2.2: mySites Run Lock (Anti-Overlap)

### Features
- ✅ Added lock for `/mySites` stage to avoid parallel runs
- ✅ Added stale-lock auto cleanup (TTL 3 hours + dead PID check)
- ✅ Added environment override for lock path: `GGL_SITES_LOCK_FILE`

### Changes
- Runs that include `/mySites` now acquire a lock file (`/tmp/gogetlinks_mysites.lock`)
- If lock is active, run is skipped gracefully with exit code `0`
- `--skip-sites` runs do not acquire the lock

### Tests
- ✅ Added `tests/test_locking.py`
- ✅ 84 passed, 1 skipped

---

## 2026-03-05 - v1.2.1: mySites Metrics + Status Alerts + Split Schedule

### Features
- ✅ Parsing `/mySites` and updating `ddl.domain` metrics by `host`
- ✅ Telegram notifications when `ggl_status` changes (same bot/chat, no mentions)
- ✅ New CLI flag `--skip-tasks` for sites-only runs
- ✅ Full pagination handling for `/mySites` (all pages)

### Changes
- Table renamed from `gogetlinks.tasks` to `ddl.ggl_tasks`
- `schema.sql` no longer creates database; expects existing `ddl`
- Cron strategy split:
  - hourly tasks run: `--skip-sites`
  - morning sites run: `--skip-tasks`

### Bug Fixes
- Added auth fallback: direct connection first, then local proxy `127.0.0.1:3128` on anti-bot block
- Removed slow reject-reason scraping from `/mySites` (status only)

### Tests
- ✅ Updated DB/integration tests for new `save_sites_to_db` return contract
- ✅ 77 passed, 1 skipped

---

## 2026-02-23 - v1.1: Detail Parsing + Telegram Notifications

### Features
- ✅ Task detail parsing via AJAX modal (description, URL, requirements, anchor)
- ✅ Telegram notifications for new tasks (Bot API, HTML formatting)
- ✅ Real test implementations (58 tests with assertions, 0 stubs)
- ✅ Detail fields stored in DB (description, url, requirements, contacts, deadline)

### Changes
- `parse_task_row()` extracts task type from `.site-link__campaign` as title
- `parse_task_list()` calls `parse_task_details()` for each task
- `insert_or_update_task()` returns `True` (new) / `False` (updated) / `None` (error)
- `main()` tracks new tasks and sends Telegram notifications
- `config.ini.example` includes `[telegram]` section

### Bug Fixes
- Modal cleanup between tasks (old modals removed before opening new one)
- CSS selectors matched to real site DOM structure

### DOM Selectors (verified on live site)
- Modal: `.tv_params_block`, `.block_title`, `.param .block_name/.block_value`
- URL: `#copy_url` input
- Task type: `.site-link__campaign` in list row cell[0]

---

## 2026-02-05 - v1.0: Initial Implementation

### Features
- ✅ Complete parser implementation (~1091 LOC)
- ✅ Authentication with optional reCAPTCHA support
- ✅ Task list parsing with 7 fields extraction
- ✅ MySQL storage with automatic deduplication
- ✅ Comprehensive error handling with specific exit codes
- ✅ Structured logging with rotation

### Bug Fixes
- Fixed captcha handling - now optional (script continues if no captcha present)
- Config parameters aligned with config.ini.example (log_file, log_level)

### Key Features
1. **Optional CAPTCHA**: Script detects if captcha is present and only solves it when needed
2. **Graceful degradation**: Individual task parsing errors don't stop entire process
3. **Secure logging**: Credentials are masked (e.g., u***@example.com)
4. **SQL injection safe**: All queries use parameterized statements
5. **Deduplication**: UNIQUE INDEX on task_id ensures no duplicates

### Exit Codes
- 0: Success
- 1: Authentication failed
- 2: Captcha solving failed
- 3: Configuration error
- 4: Database error
- 5: WebDriver error
- 99: Unexpected error
