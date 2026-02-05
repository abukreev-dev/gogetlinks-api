# Specification: Gogetlinks Task Parser

## Functional Requirements

### FR1: Authentication & Captcha Handling

#### FR1.1: User Login
**Priority:** MUST HAVE  
**Description:** Автоматическая авторизация на gogetlinks.net с использованием credentials из конфига.

**Acceptance Criteria:**
```gherkin
Feature: User Authentication
  As a parser script
  I want to authenticate on gogetlinks.net
  So that I can access task listings

  Scenario: Successful login with valid credentials
    Given the config contains valid email and password
    And the anti-captcha service is available
    When the parser starts authentication
    Then it should navigate to https://gogetlinks.net/user/signIn
    And it should fill in the email field
    And it should fill in the password field
    And it should solve the reCAPTCHA challenge
    And it should submit the login form
    And it should verify authentication by checking for "href='/profile'" in HTML
    And it should log "Successfully authenticated" message

  Scenario: Login with invalid credentials
    Given the config contains invalid credentials
    When the parser attempts authentication
    Then it should log "Authentication failed" error
    And it should exit with code 1

  Scenario: Captcha solving failure
    Given the anti-captcha API key is invalid
    When the parser attempts to solve captcha
    Then it should log "Captcha solving failed" error
    And it should retry up to 3 times
    And if all retries fail, it should exit with code 2
```

#### FR1.2: Captcha Solving
**Priority:** MUST HAVE  
**Description:** Интеграция с anti-captcha.org для автоматического решения reCAPTCHA v2.

**Acceptance Criteria:**
```gherkin
Feature: Captcha Solving
  Scenario: Extract captcha sitekey
    Given the login page is loaded
    When the parser searches for captcha element
    Then it should find element with attribute "data-sitekey"
    And it should extract the sitekey value
    And it should log "Captcha sitekey: [value]"

  Scenario: Submit captcha for solving
    Given the sitekey is extracted
    And the anti-captcha API key is valid
    When the parser submits captcha task
    Then it should receive a task ID from anti-captcha
    And it should poll for solution with 5-second intervals
    And it should wait up to 120 seconds for solution
    And it should inject the solution token into g-recaptcha-response field

  Scenario: Captcha already solved (session valid)
    Given the user has a valid session cookie
    When the parser checks the login page
    Then it should detect "href='/profile'" in HTML
    And it should skip captcha solving
    And it should log "Session already valid, skipping auth"
```

### FR2: Task Parsing

#### FR2.1: Parse Task List
**Priority:** MUST HAVE  
**Description:** Парсинг списка новых задач (NEW) с базовыми полями.

**Acceptance Criteria:**
```gherkin
Feature: Task List Parsing
  Scenario: Parse tasks from list view
    Given the user is authenticated
    When the parser navigates to https://gogetlinks.net/webTask/index
    Then it should wait for table to load (CSS selector: "tr[id^='col_row_']")
    And it should extract each task row
    And for each task it should extract:
      | Field           | Extraction Method                                    |
      | task_id         | From "id='col_row_{id}'" attribute                  |
      | domain          | First <td> → <a> text                               |
      | customer        | Second <td> → <a> text                              |
      | customer_url    | Second <td> → <a href> attribute                    |
      | external_links  | Third <td> text (stripped)                          |
      | time_passed     | Fifth <td> text (stripped)                          |
      | price           | Sixth <td> text (stripped, decoded HTML entities)   |
    And it should return a list of task dictionaries

  Scenario: No tasks available
    Given the user is authenticated
    And there are no new tasks
    When the parser checks for tasks
    Then it should log "No tasks found"
    And it should return an empty list
    And it should exit gracefully with code 0

  Scenario: Parse tasks with extended details
    Given the parser has a list of task_ids
    When the parser requests details for each task
    Then for each task_id it should navigate to:
         https://gogetlinks.net/template/view_task.php?curr_id={task_id}
    And it should extract:
      | Field        | Extraction Method                                           |
      | title        | From task detail page (primary heading or meta)            |
      | description  | Text block with "Текст задания" label                      |
      | requirements | Text block with requirements section                       |
      | url          | Input field with id="copy_url" value attribute             |
      | anchor       | Input field with id="copy_unhor" value attribute           |
      | source       | Input field with id="copy_source" value attribute          |
      | contacts     | Contact information block (if present)                     |
```

#### FR2.2: Data Cleaning & Validation
**Priority:** MUST HAVE

**Acceptance Criteria:**
```gherkin
Feature: Data Validation
  Scenario: Validate extracted data
    Given a task dictionary is extracted
    Then task_id must be a positive integer
    And price must be convertible to decimal
    And customer and domain must not be empty strings
    And if validation fails, it should log "Invalid task data: {task_id}" and skip

  Scenario: Handle Windows-1251 encoding
    Given HTML response is in Windows-1251
    When the parser reads the response
    Then it should decode to UTF-8
    And it should handle Cyrillic characters correctly
```

### FR3: Database Operations

#### FR3.1: Task Storage
**Priority:** MUST HAVE

**Acceptance Criteria:**
```gherkin
Feature: Task Storage
  Scenario: Insert new task
    Given a validated task dictionary
    And the task_id does not exist in database
    When the parser inserts the task
    Then it should execute:
         INSERT INTO tasks (task_id, title, ..., is_new, created_at)
         VALUES (?, ?, ..., 1, NOW())
    And it should log "Inserted new task: {task_id}"

  Scenario: Update existing task
    Given a validated task dictionary
    And the task_id already exists in database
    When the parser updates the task
    Then it should execute:
         UPDATE tasks SET price = ?, updated_at = NOW(), is_new = 0
         WHERE task_id = ?
    And it should log "Updated task: {task_id}"

  Scenario: Deduplication check
    Given multiple runs of the parser
    When the same task_id is encountered
    Then it should not create duplicate entries
    And the UNIQUE INDEX on task_id should prevent duplicates
```

#### FR3.2: Database Schema
**Priority:** MUST HAVE

```sql
CREATE DATABASE IF NOT EXISTS gogetlinks
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE gogetlinks;

CREATE TABLE IF NOT EXISTS tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT UNIQUE NOT NULL COMMENT 'Gogetlinks task ID',
    title VARCHAR(500) DEFAULT NULL,
    description TEXT DEFAULT NULL,
    price DECIMAL(10,2) DEFAULT NULL,
    deadline DATETIME DEFAULT NULL,
    customer VARCHAR(255) DEFAULT NULL,
    customer_url VARCHAR(500) DEFAULT NULL,
    domain VARCHAR(255) DEFAULT NULL,
    url VARCHAR(500) DEFAULT NULL,
    requirements TEXT DEFAULT NULL,
    contacts TEXT DEFAULT NULL,
    external_links INT DEFAULT NULL,
    time_passed VARCHAR(100) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_new BOOLEAN DEFAULT 1 COMMENT 'Flag for new tasks',
    
    INDEX idx_task_id (task_id),
    INDEX idx_created_at (created_at),
    INDEX idx_is_new (is_new),
    INDEX idx_price (price)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### FR4: Configuration Management

#### FR4.1: Config File
**Priority:** MUST HAVE

**config.ini structure:**
```ini
[gogetlinks]
username = user@example.com
password = secure_password

[anticaptcha]
api_key = your_anticaptcha_api_key

[database]
host = localhost
port = 3306
database = gogetlinks
user = root
password = db_password

[output]
print_tasks = true  # false for cron

[logging]
level = INFO
file = gogetlinks_parser.log
```

**Acceptance Criteria:**
```gherkin
Feature: Configuration Loading
  Scenario: Load valid config
    Given a config.ini file exists in the script directory
    When the parser starts
    Then it should load all sections
    And it should validate required fields
    And it should log "Configuration loaded successfully"

  Scenario: Missing config file
    Given no config.ini file exists
    When the parser starts
    Then it should log "config.ini not found"
    And it should exit with code 3

  Scenario: Invalid config format
    Given config.ini has syntax errors
    When the parser attempts to load config
    Then it should log "Invalid config format: {error}"
    And it should exit with code 3
```

### FR5: Output & Logging

#### FR5.1: Console Output
**Priority:** MUST HAVE

**Acceptance Criteria:**
```gherkin
Feature: Task Output
  Scenario: Print tasks to console (when enabled)
    Given output.print_tasks = true in config
    And there are tasks to display
    When the parser completes parsing
    Then it should print a formatted table:
         | Task ID | Title           | Price | Customer | Deadline |
         |---------|-----------------|-------|----------|----------|
         | 123456  | Blog post task  | $50   | Client A | 2026-02-10 |
    And each task should be on a separate line

  Scenario: Suppress output (cron mode)
    Given output.print_tasks = false in config
    When the parser runs
    Then it should not print tasks to stdout
    And all output should go to the log file only
```

#### FR5.2: Logging
**Priority:** MUST HAVE

**Acceptance Criteria:**
```gherkin
Feature: Logging
  Scenario: Log levels
    Given logging.level = INFO in config
    Then INFO, WARNING, ERROR, and CRITICAL messages should be logged
    And DEBUG messages should be suppressed

  Scenario: Log format
    Given any log message is written
    Then it should follow the format:
         2026-02-05 14:30:22 - gogetlinks_parser - INFO - Message text
    And it should include timestamp, logger name, level, and message

  Scenario: Log rotation
    Given the log file exceeds 10 MB
    Then it should automatically rotate to gogetlinks_parser.log.1
    And keep the last 5 rotated files

  Scenario: Log critical errors
    Given any exception occurs
    When the exception is caught
    Then it should log the full traceback
    And it should include context (task_id if applicable)
```

## Non-Functional Requirements

### NFR1: Performance
- **Requirement:** Full parsing cycle should complete within 5 minutes for up to 100 tasks
- **Measurement:** Total execution time from start to finish
- **Rationale:** Allows hourly cron schedule without overlap

### NFR2: Reliability
- **Requirement:** 95% success rate for parsing sessions (excluding site downtime)
- **Measurement:** Successful runs / total runs over 30 days
- **Rationale:** Acceptable failure rate for occasional captcha issues

### NFR3: Maintainability
- **Requirement:** Modular code structure with clear separation of concerns
- **Measurement:** Code review checklist (see below)
- **Rationale:** Easy debugging and feature additions

### NFR4: Security
- **Requirement:** Credentials never logged or exposed in error messages
- **Measurement:** Code audit + log review
- **Rationale:** Protect user credentials and API keys

### NFR5: Scalability
- **Requirement:** Support parsing up to 1000 tasks without performance degradation
- **Measurement:** Execution time for 1000 tasks < 30 minutes
- **Rationale:** Future-proof for increased task volume

## User Stories

### Story 1: Automated Task Discovery
**As a** freelance developer  
**I want** to automatically check for new tasks every hour  
**So that** I don't miss opportunities while I'm working on other projects

**Acceptance Criteria:**
- Parser runs every hour via cron
- New tasks are flagged with `is_new = 1`
- I can query the database for new tasks at any time

### Story 2: Task Details for Decision Making
**As a** freelance developer  
**I want** to see full task details including description and requirements  
**So that** I can quickly decide if a task is suitable for me

**Acceptance Criteria:**
- Description, requirements, and contacts are stored in database
- I can query by price range: `SELECT * FROM tasks WHERE price > 50 AND is_new = 1`
- I can query by customer: `SELECT * FROM tasks WHERE customer = 'Client A'`

### Story 3: Historical Tracking
**As a** freelance developer  
**I want** to track which tasks I've already reviewed  
**So that** I don't waste time looking at the same tasks repeatedly

**Acceptance Criteria:**
- Tasks update `is_new` flag to 0 after first parsing
- I can mark tasks as "reviewed" manually (future feature)
- Timestamp tracking shows when task was first seen and last updated

## Dependencies

### External Services
- **gogetlinks.net** - source of data (no SLA)
- **anti-captcha.com** - captcha solving (99% uptime SLA)
- **MySQL server** - database (self-hosted)

### Python Libraries
```
selenium>=4.10.0        # Browser automation
mysql-connector-python  # MySQL driver
configparser           # INI config parsing
logging                # Standard logging
```

### System Requirements
- Python 3.8+
- Chrome/Chromium browser (headless)
- MySQL 8.0+
- Ubuntu 20.04+ or similar Linux distro (VPS)
- Minimum 1GB RAM, 10GB disk space

## Test Scenarios

### Integration Tests

#### Test 1: End-to-End Happy Path
```python
def test_full_parsing_cycle():
    """
    Test complete parsing from auth to database insertion
    """
    # Given: Valid config with real credentials
    # When: Parser runs full cycle
    # Then: At least 1 task should be inserted into database
    # And: Log should contain "Successfully authenticated"
    # And: Exit code should be 0
```

#### Test 2: Captcha Failure Handling
```python
def test_captcha_failure_retry():
    """
    Test retry logic when captcha solving fails
    """
    # Given: Anti-captcha service is temporarily unavailable
    # When: Parser attempts authentication
    # Then: It should retry 3 times with 5-second delays
    # And: Log should contain "Retry attempt 1/3"
    # And: Exit code should be 2 after 3 failures
```

#### Test 3: Duplicate Detection
```python
def test_duplicate_task_handling():
    """
    Test that duplicate tasks are updated, not inserted
    """
    # Given: Database already contains task_id 123456
    # When: Parser encounters same task_id again
    # Then: Database should have only 1 row with that task_id
    # And: updated_at should be current timestamp
    # And: is_new should be 0
```

---

## Constraints Summary

| Constraint | Value |
|------------|-------|
| Programming Language | Python 3.8+ |
| Browser Automation | Selenium WebDriver |
| Database | MySQL 8.0+ |
| Deployment | VPS (no Docker) |
| Scheduler | Cron |
| Captcha Solver | Anti-Captcha.org |

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-05  
**Confidence Level:** High (95%)
