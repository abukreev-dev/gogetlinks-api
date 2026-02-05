# Gogetlinks Task Parser - Claude Code Guide

## Project Overview

**Gogetlinks Task Parser** — automated task scraper for gogetlinks.net freelance platform. Runs hourly via cron, authenticates (with anti-captcha), parses task listings, stores in MySQL with deduplication.

**Status:** MVP Ready  
**Language:** Python 3.8+  
**Deployment:** VPS (no Docker)

## Quick Start

```bash
# Setup
git clone <repo>
cd gogetlinks-parser
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config.ini.example config.ini
nano config.ini  # Fill credentials
chmod 600 config.ini

# Initialize DB
mysql -u root -p < schema.sql

# Run
python gogetlinks_parser.py

# Deploy cron
crontab -e
# Add: 0 * * * * cd ~/gogetlinks-parser && venv/bin/python gogetlinks_parser.py
```

## Architecture Summary

```
Cron → Python Script
       ├─ Selenium (headless Chrome)
       │  └─ gogetlinks.net
       ├─ Anti-Captcha API (captcha solving)
       └─ MySQL (task storage)
```

**Key Components:**
- **Auth Module:** Login + captcha solving (anti-captcha.com)
- **Parser Module:** HTML extraction (list + detail views)
- **Database Module:** MySQL CRUD with UNIQUE INDEX deduplication
- **Config Module:** INI parsing + validation
- **Logging:** Structured logging to file

## Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `gogetlinks_parser.py` | Main script (orchestrator) | ~500 |
| `config.ini` | Credentials (gitignored) | ~20 |
| `schema.sql` | MySQL DDL | ~30 |
| `requirements.txt` | Python deps | 2 |
| `README.md` | User documentation | ~100 |

## Common Tasks

### Add New Feature
1. Read `Specification.md` for requirements
2. Check `Pseudocode.md` for data flow
3. Implement in modular function
4. Add unit tests (pytest)
5. Update `CHANGELOG.md`

### Fix Bug
1. Check logs: `tail -f gogetlinks_parser.log`
2. Take screenshot on error (if Selenium)
3. Dump HTML for parsing failures
4. Fix + add regression test
5. Verify with manual run

### Update Selectors (if site changes)
1. Inspect gogetlinks.net HTML
2. Update CSS selectors in parser module
3. Test with dry run mode
4. Document in `CHANGELOG.md`

## Development Practices

### Parallel Execution Strategy
- Use `Task` tool for independent subtasks (e.g., parse multiple detail pages)
- Run tests, linting, type-checking in parallel
- For complex features: spawn specialized agents

**Example:**
```python
# Parallel detail fetching (future optimization)
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(parse_details, id) for id in task_ids]
    results = [f.result() for f in futures]
```

### Git Workflow
**Commit conventions:**
- `feat(scope): description` — new functionality
- `fix(scope): description` — bug fix
- `refactor(scope): description` — refactoring
- `test(scope): description` — tests
- `docs(scope): description` — documentation
- `chore(scope): description` — infrastructure

**Rule:** 1 logical change = 1 commit

**Example:**
```bash
git commit -m "feat(parser): add detail page extraction"
git commit -m "test(parser): add unit tests for detail parsing"
```

### Swarm Agents Hints
**When to use multiple agents:**
- **Large feature:** `@planner` to decompose + 2-3 implementation agents in parallel
- **Refactoring:** `@code-reviewer` + refactor agents
- **Bug-fix:** Single agent (no parallelism needed)

**Coordination:**
- Use `Task` tool for parallel execution
- Share context via file writes (e.g., `feature_plan.md`)
- Final merge by coordinating agent

## Conventions

### Code Style
- **PEP 8** compliance (checked by `black` formatter)
- **Type hints** for function signatures
- **Docstrings:** Google style
```python
def parse_task(row: WebElement) -> Task:
    """Extract task data from HTML row.
    
    Args:
        row: Selenium WebElement representing task row
        
    Returns:
        Task object with extracted fields
        
    Raises:
        ValueError: If row format is invalid
    """
```

### Error Handling
- **Specific exceptions** over bare `Exception`
- **Log context:** Include task_id, URL, operation
- **Exit codes:** 0=success, 1=auth, 2=captcha, 3=config, 4=db, 5=webdriver, 99=unexpected

### Security
- **Never log** passwords, API keys, tokens
- **Mask sensitive data:** `user***@example.com`
- **File permissions:** `config.ini` must be `chmod 600`

## Testing

### Run Tests
```bash
# All tests
pytest tests/

# Specific test
pytest tests/test_parser.py::test_price_parsing

# With coverage
pytest --cov=gogetlinks_parser tests/
```

### Test Structure
```
tests/
├── test_auth.py         # Authentication tests
├── test_parser.py       # Parsing tests
├── test_database.py     # Database tests
└── conftest.py          # Fixtures
```

### Coverage Requirements
- **Minimum:** 80% code coverage
- **Critical paths:** 100% (auth, parsing, db insert)

## Deployment

### Manual Deployment
```bash
# 1. Clone on VPS
ssh user@vps
cd ~
git clone <repo>

# 2. Setup (see Quick Start)

# 3. Test run
python gogetlinks_parser.py

# 4. Setup cron
crontab -e
```

### Monitoring
```bash
# Check last run status
tail -n 50 gogetlinks_parser.log | grep "Exit code"

# Count errors (last 24h)
grep -c "ERROR" gogetlinks_parser.log | tail -n 24

# View new tasks in DB
mysql -u gogetlinks_parser -p -e "SELECT * FROM gogetlinks.tasks WHERE is_new=1 ORDER BY created_at DESC LIMIT 10;"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Authentication failed" | Check credentials in config.ini, verify anti-captcha balance |
| "Captcha solving failed" | Check anti-captcha API key, verify balance >$5 |
| "Database error" | Check MySQL service: `sudo systemctl status mysql` |
| Parser returns empty list | Check if site layout changed (inspect HTML), update selectors |
| Cron not running | Check crontab: `crontab -l`, check logs: `/var/log/gogetlinks_cron.log` |

## Performance Benchmarks

| Metric | Expected | Actual |
|--------|----------|--------|
| Auth time | 20-30s | - |
| Parse 100 tasks | 60s | - |
| Parse 10 details | 30s | - |
| Total cycle | 2-3 min | - |

## Resources

- **Documentation:** `/docs/` directory (SPARC files)
- **Issue Tracker:** GitHub Issues
- **API Docs:** Anti-Captcha: https://anti-captcha.com/apidoc
- **Selenium Docs:** https://www.selenium.dev/documentation/

## Future Enhancements

### v1.1 (Week 3-4)
- Detail parsing (description, requirements, contacts)
- Session cookie persistence
- Retry logic with exponential backoff

### v2.0 (Month 2+)
- Web dashboard (Flask)
- Email/Telegram notifications
- Task filtering engine

### v3.0 (Month 6+)
- Docker + Coolify deployment
- Multi-user support
- API for integrations

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-05  
**For Questions:** See README.md or GitHub Issues
