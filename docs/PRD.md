# Product Requirements Document: Gogetlinks Task Parser

## Executive Summary

**Product Name:** Gogetlinks Task Parser  
**Version:** 1.0 MVP  
**Document Date:** 2026-02-05  
**Status:** Ready for Development

### Problem Statement
Freelance developers using gogetlinks.net must manually check the platform multiple times per day to discover new tasks, wasting valuable time and often missing opportunities due to delays.

### Solution
Automated task parser that runs hourly via cron, authenticates using anti-captcha service, extracts task data, and stores in MySQL database with deduplication, enabling developers to query new opportunities on demand.

### Success Metrics
- 95% parsing success rate
- < 5 minute average cycle time
- Zero duplicate entries
- 100% of new tasks captured within 1 hour of posting

## Product Vision & Goals

### Vision
Enable freelance developers to focus on their core work by automating the tedious task of monitoring gogetlinks.net for new opportunities.

### Primary Goals
1. **Automation:** Replace manual checking with scheduled automation
2. **Data Persistence:** Store historical task data for analysis
3. **Reliability:** Run unattended with minimal intervention
4. **Simplicity:** Single-script deployment on VPS

### Non-Goals (MVP)
- Real-time notifications
- Web UI for task browsing
- Task filtering/recommendation engine
- Multi-platform support (only gogetlinks.net)

## Target Users

### Primary Persona: Freelance Developer
- **Demographics:** 25-40 years old, intermediate-expert developer
- **Pain Points:** 
  - Manual checking interrupts workflow
  - Missing tasks due to delayed checking
  - No historical data for trend analysis
- **Tech Savvy:** Comfortable with VPS, cron, MySQL
- **Usage Pattern:** Query database 2-3 times per day for new tasks

### Secondary Persona: Development Agency
- **Use Case:** Monitor tasks for team allocation
- **Scale:** Managing multiple freelancers
- **Future Enhancement:** API for internal tools integration

## Core Features

### F1: Authentication & Captcha Handling
**Priority:** MUST HAVE  
**Description:** Automatic login to gogetlinks.net with anti-captcha.com integration  
**User Story:** As a user, I want the parser to authenticate automatically so I don't need to manually log in  
**Acceptance Criteria:**
- Successful authentication >95% of attempts
- Captcha solving within 120 seconds
- Session validation before re-auth

### F2: Task List Parsing
**Priority:** MUST HAVE  
**Description:** Extract task data from NEW tasks page  
**User Story:** As a user, I want all available tasks scraped so I can see every opportunity  
**Acceptance Criteria:**
- Parse task_id, domain, customer, price, time_passed
- Handle empty task lists gracefully
- Extract 100+ tasks in < 60 seconds

### F3: Database Storage & Deduplication
**Priority:** MUST HAVE  
**Description:** Store tasks in MySQL with automatic duplicate detection  
**User Story:** As a user, I want tasks stored without duplicates so I can track new vs existing  
**Acceptance Criteria:**
- UNIQUE constraint on task_id prevents duplicates
- `is_new` flag marks first-time tasks
- `updated_at` timestamp tracks changes

### F4: Configuration Management
**Priority:** MUST HAVE  
**Description:** INI-based config for credentials and settings  
**User Story:** As a user, I want to configure credentials easily without editing code  
**Acceptance Criteria:**
- config.ini with sections: gogetlinks, anticaptcha, database, output, logging
- Validation on startup with clear error messages
- Secure file permissions (chmod 600)

### F5: Logging & Output
**Priority:** MUST HAVE  
**Description:** Structured logging to file with optional console output  
**User Story:** As a user, I want detailed logs for troubleshooting  
**Acceptance Criteria:**
- Log levels: INFO, WARNING, ERROR
- Log rotation at 10 MB (keep 5 files)
- Console output toggle in config

### F6: Scheduled Execution
**Priority:** MUST HAVE  
**Description:** Cron-based hourly execution  
**User Story:** As a user, I want the parser to run automatically so I don't need to remember  
**Acceptance Criteria:**
- Exit codes for monitoring (0=success, 1=auth fail, 2=captcha fail, etc.)
- Graceful handling of overlapping runs
- Email on cron failure (system level)

## Future Enhancements (Post-MVP)

### v1.1 Features
- Detail parsing (description, requirements, contacts)
- Session cookie persistence (skip auth if valid)
- Retry logic with exponential backoff
- Email/Telegram notifications for new tasks

### v2.0 Features
- Web dashboard (Flask + Bootstrap)
- Task filtering by price, deadline, customer
- Historical analytics (trends, avg prices)
- Export to CSV/Excel

### v3.0 Features
- Multi-user support (team accounts)
- API for third-party integrations
- Machine learning recommendation engine
- Docker containerization + Coolify deployment

## Technical Requirements

### Technology Stack
| Component | Technology | Version | Justification |
|-----------|-----------|---------|---------------|
| Language | Python | 3.8+ | Mature ecosystem for scraping |
| Browser | Selenium + Chrome | 4.10+ | Headless automation standard |
| Database | MySQL | 8.0+ | Reliable ACID compliance |
| Scheduler | Cron | System | Native Linux scheduling |
| Captcha | Anti-Captcha API | Latest | Human-powered solving |

### Infrastructure
- **Environment:** VPS (Ubuntu 20.04+)
- **Deployment:** Git clone + venv + cron
- **No Docker:** Simplified MVP deployment

### Performance Requirements
- Parsing cycle: < 5 minutes for 100 tasks
- Database query: < 100ms for "new tasks" query
- Memory usage: < 500 MB during execution
- Disk usage: < 1 GB for 6 months of data

### Security Requirements
- Credentials never logged
- config.ini permissions: 600 (owner read/write only)
- MySQL user with minimal privileges (SELECT, INSERT, UPDATE only)
- No secrets in code or version control

## User Interface

**MVP:** Command-line only  
**Output Format (when enabled):**
```
╔═══════════════════════════════════════════════════════════╗
║          Gogetlinks Parser - Task Report                  ║
╠═══════════╤════════════════╤══════════╤═══════════════════╣
║ Task ID   │ Domain         │ Price    │ Customer          ║
╠═══════════╪════════════════╪══════════╪═══════════════════╣
║ 123456    │ example.com    │ $50.00   │ Client A          ║
║ 123457    │ testsite.org   │ $75.00   │ Client B          ║
╚═══════════╧════════════════╧══════════╧═══════════════════╝
Total: 2 new tasks found
```

## Dependencies & Integrations

### External Services
- **gogetlinks.net:** Data source (no SLA)
- **anti-captcha.com:** Captcha solving (99% uptime, $1/1000 captchas)

### Python Libraries
```
selenium>=4.10.0
mysql-connector-python>=8.0.0
```

## Success Criteria & KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Parsing success rate | >95% | Exit code 0 / total runs |
| Avg cycle time | 2-3 min | Log analysis |
| Captcha success rate | >90% | Successful auths / attempts |
| Zero duplicates | 100% | DB constraint enforcement |
| Uptime | >99% | Cron execution history |

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Site layout changes | Medium | High | Flexible selectors, HTML dumps on error |
| Captcha failure | Low | Critical | Retry logic, API key validation |
| IP blocking | Low | High | Rate limiting (max 1/hour), user-agent rotation |
| Database full | Low | Medium | Log rotation, monthly archiving |

## Release Plan

### Phase 1: MVP (Week 1-2)
- Core authentication + parsing + storage
- Basic logging and cron setup
- Manual deployment guide

### Phase 2: Enhancements (Week 3-4)
- Detail parsing
- Session persistence
- Improved error handling

### Phase 3: Productization (Month 2+)
- Web dashboard
- Notifications
- Docker packaging

## Appendices

### Appendix A: Database Schema
See `Architecture.md` for full DDL

### Appendix B: Config File Format
See `Specification.md` for full structure

### Appendix C: Exit Codes
- 0: Success
- 1: Authentication failed
- 2: Captcha solving failed
- 3: Config error
- 4: Database error
- 5: WebDriver error
- 99: Unexpected error

---

**PRD Version:** 1.0  
**Document Owner:** Project Lead  
**Approved By:** [Pending]  
**Next Review:** After MVP deployment
