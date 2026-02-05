# Changelog

## 2026-02-05 - Initial Implementation

### Features
- ✅ Complete parser implementation (~900 LOC)
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

### Next Steps
- Run unit tests (when implemented)
- Test with real gogetlinks.net credentials
- Set up cron job for automated parsing
