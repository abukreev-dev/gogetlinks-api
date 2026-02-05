# Refinement: Gogetlinks Task Parser

## Edge Cases & Error Scenarios

### EC1: Captcha-Related Edge Cases

#### EC1.1: Captcha Not Present
**Scenario:** Login page loads without captcha  
**Cause:** Session cookie still valid OR site temporarily disabled captcha  
**Handling:**
```python
if captcha_element is None:
    logger.warning("No captcha found, attempting direct login")
    # Proceed with form submission without captcha token
```
**Test:** Clear cookies and check if captcha appears

#### EC1.2: Captcha Sitekey Changed
**Scenario:** Anti-captcha receives different sitekey format  
**Cause:** Site updated reCAPTCHA version  
**Handling:**
```python
if not is_valid_sitekey(sitekey):
    logger.error(f"Invalid sitekey format: {sitekey}")
    # Take screenshot for debugging
    driver.save_screenshot("invalid_sitekey.png")
    raise CaptchaError("Sitekey format changed")
```

#### EC1.3: Anti-Captcha API Rate Limit
**Scenario:** Too many requests to anti-captcha.com  
**Cause:** Running parser too frequently  
**Handling:**
```python
if response.status_code == 429:
    logger.warning("Rate limited by anti-captcha, waiting 60s")
    time.sleep(60)
    retry_solve_captcha()
```

#### EC1.4: Captcha Solved But Login Still Fails
**Scenario:** Captcha token valid, but login form rejects submission  
**Cause:** Incorrect credentials OR additional verification step  
**Handling:**
```python
if captcha_solved and not is_authenticated():
    logger.error("Captcha solved but login failed")
    # Check for error messages on page
    error_msg = driver.find_element(By.CSS_SELECTOR, ".error-message").text
    logger.error(f"Login error: {error_msg}")
    raise AuthenticationError("Credentials rejected")
```

### EC2: Parsing Edge Cases

#### EC2.1: Incomplete Task Rows
**Scenario:** Task row has missing <td> cells  
**Cause:** Malformed HTML OR different task type  
**Handling:**
```python
def parse_task_row_safe(row):
    try:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            logger.warning(f"Incomplete row (task_id unknown): {len(cells)} cells")
            return None  # Skip this task
        return parse_task_row(row)
    except Exception as e:
        logger.warning(f"Failed to parse row: {e}")
        return None
```

#### EC2.2: Price in Unexpected Format
**Scenario:** Price contains currency symbols, letters, or multiple decimals  
**Examples:**
- "$123.45 USD"
- "1,234.56"
- "FREE"
- "TBD"

**Handling:**
```python
def parse_price_robust(text):
    # Remove common currency symbols and whitespace
    text = re.sub(r'[^\d.,]', '', text)
    
    # Replace comma with dot
    text = text.replace(',', '.')
    
    # Handle multiple dots (take last segment)
    if text.count('.') > 1:
        parts = text.split('.')
        text = parts[-2] + '.' + parts[-1]
    
    try:
        return Decimal(text)
    except:
        logger.warning(f"Could not parse price: {text}")
        return Decimal('0.00')
```

#### EC2.3: Cyrillic Encoding Issues
**Scenario:** Task description contains malformed Cyrillic characters  
**Cause:** Incorrect encoding detection (not Windows-1251)  
**Handling:**
```python
def decode_robust(html_bytes):
    encodings = ['windows-1251', 'utf-8', 'cp1252']
    for enc in encodings:
        try:
            return html_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    logger.error("Failed to decode HTML with common encodings")
    return html_bytes.decode('utf-8', errors='replace')
```

#### EC2.4: Empty Task List (No NEW Tasks)
**Scenario:** /webTask/index returns empty table  
**Cause:** No new tasks available OR wrong page loaded  
**Handling:**
```python
task_rows = driver.find_elements(By.CSS_SELECTOR, "tr[id^='col_row_']")
if len(task_rows) == 0:
    # Check if we're on the right page
    if "Новые" not in driver.page_source:
        logger.error("Not on NEW tasks page, possible navigation error")
        raise NavigationError("Wrong page loaded")
    logger.info("No new tasks available")
    return []
```

#### EC2.5: Task Details Page 404
**Scenario:** Task detail URL returns 404  
**Cause:** Task was deleted OR URL format changed  
**Handling:**
```python
driver.get(f"https://gogetlinks.net/template/view_task.php?curr_id={task_id}")
if "404" in driver.title or "Not Found" in driver.page_source:
    logger.warning(f"Task {task_id} not found (deleted?)")
    return None  # Skip this task
```

### EC3: Database Edge Cases

#### EC3.1: Database Connection Lost Mid-Operation
**Scenario:** MySQL connection drops during batch insert  
**Cause:** Network issue OR MySQL timeout  
**Handling:**
```python
def execute_with_reconnect(cursor, query, values, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            cursor.execute(query, values)
            return True
        except mysql.connector.errors.OperationalError as e:
            if "MySQL server has gone away" in str(e):
                logger.warning(f"Connection lost, reconnecting (attempt {attempt})")
                db.reconnect()
                cursor = db.cursor()
            else:
                raise
    raise DatabaseError("Failed to execute after reconnection attempts")
```

#### EC3.2: Duplicate Key on Concurrent Inserts
**Scenario:** Two parser instances try to insert same task_id  
**Cause:** Overlapping cron schedules OR manual execution  
**Handling:**
```python
INSERT INTO tasks (...) VALUES (...)
ON DUPLICATE KEY UPDATE
    updated_at = NOW(),
    is_new = IF(is_new = 1, 1, 0)  -- Preserve new flag
```

#### EC3.3: Database Disk Full
**Scenario:** INSERT fails due to disk space  
**Cause:** Log table growth OR tmp files  
**Handling:**
```python
except mysql.connector.errors.DatabaseError as e:
    if "disk full" in str(e).lower():
        logger.critical("Database disk full! Manual intervention required")
        send_alert_email()  # Future feature
        sys.exit(4)
```

### EC4: Network & Timeout Edge Cases

#### EC4.1: gogetlinks.net Temporarily Down
**Scenario:** Site returns 503 or connection refused  
**Cause:** Maintenance OR overload  
**Handling:**
```python
try:
    driver.get("https://gogetlinks.net/user/signIn")
except WebDriverException as e:
    if "connection refused" in str(e).lower():
        logger.warning("gogetlinks.net unreachable, will retry next cron cycle")
        sys.exit(0)  # Exit gracefully, not an error
```

#### EC4.2: Page Load Timeout
**Scenario:** Task list takes > 30 seconds to load  
**Cause:** Site slowness OR network congestion  
**Handling:**
```python
driver.set_page_load_timeout(30)
try:
    driver.get("https://gogetlinks.net/webTask/index")
except TimeoutException:
    logger.warning("Page load timeout, retrying once")
    driver.refresh()
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "tr[id^='col_row_']"))
    )
```

#### EC4.3: Element Stale After Page Update
**Scenario:** Parsing element becomes stale mid-extraction  
**Cause:** JavaScript updated DOM dynamically  
**Handling:**
```python
from selenium.common.exceptions import StaleElementReferenceException

def get_text_safe(element, retries=2):
    for i in range(retries):
        try:
            return element.text
        except StaleElementReferenceException:
            logger.debug(f"Stale element, refinding (attempt {i+1})")
            time.sleep(0.5)
    raise Exception("Element remained stale after retries")
```

## Testing Strategy

### Unit Tests

#### Test 1: Config Validation
```python
def test_config_validation():
    # Invalid config (missing section)
    config = configparser.ConfigParser()
    config.read_string("[database]\nhost=localhost")
    with pytest.raises(ConfigError):
        validate_config(config)
    
    # Valid config
    config = load_test_config()
    assert validate_config(config) == True
```

#### Test 2: Price Parsing
```python
@pytest.mark.parametrize("input,expected", [
    ("$123.45", Decimal("123.45")),
    ("1,234.56 руб", Decimal("1234.56")),
    ("FREE", Decimal("0.00")),
    ("", Decimal("0.00")),
    ("abc", Decimal("0.00")),
])
def test_price_parsing(input, expected):
    assert parse_price_robust(input) == expected
```

#### Test 3: Task ID Extraction
```python
def test_task_id_extraction():
    # Valid ID
    row = Mock()
    row.get_attribute.return_value = "col_row_123456"
    assert extract_task_id(row) == 123456
    
    # Invalid format
    row.get_attribute.return_value = "invalid"
    with pytest.raises(ValueError):
        extract_task_id(row)
```

### Integration Tests

#### Test 4: Full Auth Flow (Using Test Account)
```python
def test_authentication_flow():
    """Requires test credentials in config_test.ini"""
    config = load_test_config()
    driver = webdriver.Chrome(options=get_headless_options())
    
    try:
        authenticator = Authenticator(driver, config)
        result = authenticator.authenticate()
        assert result == True
        
        # Verify we're on authenticated page
        assert "/profile" in driver.current_url or "Выйти" in driver.page_source
    finally:
        driver.quit()
```

#### Test 5: Parse Empty Task List
```python
def test_parse_empty_task_list(mock_driver):
    mock_driver.find_elements.return_value = []
    parser = TaskParser(mock_driver)
    tasks = parser.parse_task_list()
    assert tasks == []
```

#### Test 6: Database Deduplication
```python
def test_database_deduplication():
    db = get_test_database()
    task = Task(task_id=999, domain="test.com", price=100)
    
    # First insert
    insert_task(db, task)
    count1 = db.cursor().execute("SELECT COUNT(*) FROM tasks WHERE task_id=999").fetchone()[0]
    assert count1 == 1
    
    # Second insert (should update, not duplicate)
    task.price = 200
    insert_task(db, task)
    count2 = db.cursor().execute("SELECT COUNT(*) FROM tasks WHERE task_id=999").fetchone()[0]
    assert count2 == 1  # Still only 1 row
    
    # Verify price was updated
    price = db.cursor().execute("SELECT price FROM tasks WHERE task_id=999").fetchone()[0]
    assert price == Decimal("200.00")
```

### End-to-End Tests

#### Test 7: Full Parsing Cycle (Staging)
```python
@pytest.mark.slow
def test_full_parsing_cycle():
    """
    End-to-end test using real credentials (staging environment)
    WARNING: Uses real anti-captcha credits
    """
    # Run full script
    result = subprocess.run(
        ["python", "gogetlinks_parser.py"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0
    assert "Successfully authenticated" in result.stdout
    assert "Parsing completed" in result.stdout
    
    # Verify database has entries
    db = connect_to_database()
    count = db.cursor().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count > 0
```

### Load Tests

#### Test 8: Parse 1000 Tasks Performance
```python
def test_parse_performance():
    """
    Mock test to verify parsing speed
    """
    start = time.time()
    
    # Mock 1000 task rows
    mock_rows = [create_mock_task_row(i) for i in range(1000)]
    parser = TaskParser(None)
    
    tasks = []
    for row in mock_rows:
        tasks.append(parser._extract_task_row(row))
    
    elapsed = time.time() - start
    assert elapsed < 10  # Should parse 1000 in < 10 seconds
    assert len(tasks) == 1000
```

## Performance Optimizations

### Optimization 1: Batch Database Inserts

**Current (MVP):**
```python
for task in tasks:
    insert_task(db, task)
```

**Optimized:**
```python
def batch_insert_tasks(db, tasks, batch_size=100):
    query = """
        INSERT INTO tasks (...) VALUES
    """ + ",".join(["(%s, %s, ...)"] * batch_size) + """
        ON DUPLICATE KEY UPDATE ...
    """
    
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        values = []
        for task in batch:
            values.extend([task.task_id, task.title, ...])
        cursor.execute(query, values)
```

**Benefit:** 10x faster for 100+ tasks

### Optimization 2: Parallel Detail Fetching

**Current (MVP):**
```python
for task_id in new_task_ids:
    details = parse_task_details(driver, task_id)
```

**Optimized:**
```python
from concurrent.futures import ThreadPoolExecutor

def fetch_details_parallel(task_ids, max_workers=5):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(parse_task_details, task_id)
            for task_id in task_ids
        ]
        return [f.result() for f in futures]
```

**Benefit:** 5x faster for detail fetching

### Optimization 3: Session Cookie Persistence

**Current (MVP):** Authenticate every run

**Optimized:**
```python
def load_session_cookies():
    if os.path.exists("session_cookies.pkl"):
        cookies = pickle.load(open("session_cookies.pkl", "rb"))
        for cookie in cookies:
            driver.add_cookie(cookie)
        return True
    return False

def save_session_cookies():
    cookies = driver.get_cookies()
    pickle.dump(cookies, open("session_cookies.pkl", "wb"))
```

**Benefit:** Skip auth if session valid (save 20-30s per run)

### Optimization 4: Incremental Parsing

**Current (MVP):** Parse all tasks every time

**Optimized:**
```python
def get_last_parsed_timestamp():
    cursor = db.cursor()
    cursor.execute("SELECT MAX(created_at) FROM tasks")
    return cursor.fetchone()[0] or datetime.min

def parse_only_new_tasks():
    # Compare time_passed field to detect new tasks
    last_timestamp = get_last_parsed_timestamp()
    # Only parse tasks newer than last_timestamp
```

**Benefit:** Reduce parsing time for frequent runs

## Debugging Tools

### Tool 1: Screenshot on Error

```python
def take_debug_screenshot(driver, prefix="error"):
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    driver.save_screenshot(filename)
    logger.info(f"Debug screenshot saved: {filename}")
```

### Tool 2: HTML Dump on Parsing Failure

```python
def dump_html_on_error(html, task_id=None):
    filename = f"html_dump_{task_id or 'unknown'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info(f"HTML dumped for debugging: {filename}")
```

### Tool 3: Dry Run Mode

```python
if config['debug']['dry_run']:
    logger.info("DRY RUN MODE: Not inserting into database")
    for task in tasks:
        logger.info(f"Would insert: {task}")
else:
    insert_task(db, task)
```

### Tool 4: Verbose Logging

```python
if config['debug']['verbose']:
    logger.setLevel(logging.DEBUG)
    logger.debug(f"Raw HTML: {driver.page_source[:500]}")
    logger.debug(f"Current URL: {driver.current_url}")
    logger.debug(f"Cookies: {driver.get_cookies()}")
```

## Maintenance Checklist

### Weekly Checks
- [ ] Review error logs for new patterns
- [ ] Verify captcha success rate > 90%
- [ ] Check database size growth (should be linear)
- [ ] Verify cron jobs are running on schedule

### Monthly Checks
- [ ] Update Selenium WebDriver if Chrome updated
- [ ] Review anti-captcha balance
- [ ] Rotate log files manually if needed
- [ ] Backup database (`mysqldump gogetlinks > backup.sql`)

### Quarterly Checks
- [ ] Check for gogetlinks.net layout changes (run debug mode)
- [ ] Update Python dependencies (`pip list --outdated`)
- [ ] Review and update CSS selectors if needed
- [ ] Audit security (config file permissions, user privileges)

---

**Refinement Version:** 1.0  
**Test Coverage Target:** 80%  
**Performance Benchmarks:** See Architecture.md
