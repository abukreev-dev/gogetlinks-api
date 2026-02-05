#!/usr/bin/env python3
"""Gogetlinks Task Parser

Automated parser for gogetlinks.net tasks with authentication (including
reCAPTCHA solving), task list parsing, and MySQL storage with automatic
deduplication.

Usage:
    python gogetlinks_parser.py

Exit Codes:
    0  - Success
    1  - Authentication failed
    2  - Captcha solving failed
    3  - Configuration error
    4  - Database error
    5  - WebDriver error
    99 - Unexpected error
"""

import configparser
import html
import logging
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import mysql.connector
import requests
from mysql.connector import MySQLConnection
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# =============================================================================
# CONSTANTS
# =============================================================================

# URLs
HOME_URL = "https://gogetlinks.net"
LOGIN_URL = "https://gogetlinks.net/user/signIn"
TASK_LIST_URL = "https://gogetlinks.net/webTask/index"
TASK_DETAIL_URL = "https://gogetlinks.net/template/view_task.php?curr_id={}"

# Timeouts
CAPTCHA_TIMEOUT = 120
CAPTCHA_POLL_INTERVAL = 5
MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 10
IMPLICIT_WAIT = 5

# Exit codes
EXIT_SUCCESS = 0
EXIT_AUTH_FAILED = 1
EXIT_CAPTCHA_FAILED = 2
EXIT_CONFIG_ERROR = 3
EXIT_DATABASE_ERROR = 4
EXIT_WEBDRIVER_ERROR = 5
EXIT_UNEXPECTED = 99

# CSS Selectors
SELECTOR_TASK_ROWS = "tr[id^='col_row_']"
SELECTOR_CAPTCHA = "[data-sitekey]"
SELECTOR_LOGIN_BUTTON = "a[href='/user/signIn'][rel='modal:open']"
SELECTOR_LOGIN_EMAIL = "input.js-email[name='e_mail']"
SELECTOR_LOGIN_PASSWORD = "input.js-password[name='password']"
SELECTOR_LOGIN_SUBMIT = "button.js-send-sign-in[type='submit']"
SELECTOR_PROFILE_LINK = "a[href='/profile']"

# Anti-Captcha API
ANTICAPTCHA_CREATE_TASK_URL = "https://api.anti-captcha.com/createTask"
ANTICAPTCHA_GET_RESULT_URL = "https://api.anti-captcha.com/getTaskResult"

# =============================================================================
# CONFIGURATION
# =============================================================================


def load_config(config_path: str = "config.ini") -> Dict[str, Any]:
    """Load and validate configuration from INI file.

    Args:
        config_path: Path to config.ini file

    Returns:
        Configuration dictionary with nested structure

    Raises:
        FileNotFoundError: If config file doesn't exist
        configparser.Error: If config file is malformed
    """
    parser = configparser.ConfigParser()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            parser.read_file(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config = {
        "gogetlinks": {
            "username": parser.get("gogetlinks", "username"),
            "password": parser.get("gogetlinks", "password"),
        },
        "anticaptcha": {
            "api_key": parser.get("anticaptcha", "api_key"),
        },
        "database": {
            "host": parser.get("database", "host"),
            "port": parser.getint("database", "port"),
            "user": parser.get("database", "user"),
            "password": parser.get("database", "password"),
            "database": parser.get("database", "database"),
        },
        "output": {
            "print_to_console": parser.getboolean("output", "print_to_console"),
        },
        "logging": {
            "log_file": parser.get("logging", "log_file"),
            "log_level": parser.get("logging", "log_level"),
        },
    }

    return config


def validate_config(config: Dict[str, Any]) -> None:
    """Validate required configuration fields.

    Args:
        config: Configuration dictionary

    Raises:
        ValueError: If config is invalid
    """
    # Validate email format
    email = config["gogetlinks"]["username"]
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email):
        raise ValueError(f"Invalid email format: {email}")

    # Validate API key format (32 hex characters)
    api_key = config["anticaptcha"]["api_key"]
    if not re.match(r"^[a-f0-9]{32}$", api_key, re.IGNORECASE):
        raise ValueError("Invalid API key format (expected 32 hex characters)")

    # Validate database port
    port = config["database"]["port"]
    if not (1 <= port <= 65535):
        raise ValueError(f"Invalid database port: {port}")


def mask_email(email: str) -> str:
    """Mask email for safe logging.

    Args:
        email: Email address to mask

    Returns:
        Masked email (e.g., u***@example.com)

    Example:
        >>> mask_email("user@example.com")
        'u***@example.com'
    """
    if "@" not in email:
        return "***"

    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 1)

    return f"{masked_local}@{domain}"


# =============================================================================
# LOGGING
# =============================================================================


def setup_logger(
    log_file: str = "gogetlinks_parser.log", log_level: str = "INFO"
) -> logging.Logger:
    """Initialize logger with rotation.

    Args:
        log_file: Path to log file
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("gogetlinks_parser")
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers
    logger.handlers = []

    # Format
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # File handler with rotation (5MB, 3 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# =============================================================================
# DATABASE
# =============================================================================


def connect_to_database(config: Dict[str, Any], logger: logging.Logger) -> MySQLConnection:
    """Establish MySQL connection with retry logic.

    Args:
        config: Database configuration
        logger: Logger instance

    Returns:
        MySQL connection object

    Raises:
        mysql.connector.Error: If connection fails after retries
    """
    db_config = config["database"]
    max_attempts = MAX_RETRIES

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                f"Connecting to database on {db_config['host']}:{db_config['port']} "
                f"(attempt {attempt}/{max_attempts})"
            )

            conn = mysql.connector.connect(
                host=db_config["host"],
                port=db_config["port"],
                user=db_config["user"],
                password=db_config["password"],
                database=db_config["database"],
                charset="utf8mb4",
                collation="utf8mb4_unicode_ci",
            )

            logger.info("Database connection established")
            return conn

        except mysql.connector.Error as e:
            logger.warning(
                f"Database connection failed (attempt {attempt}/{max_attempts}): {e}"
            )

            if attempt < max_attempts:
                wait_time = 2**attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error("All database connection attempts failed")
                raise


def task_exists(conn: MySQLConnection, task_id: int) -> bool:
    """Check if task_id exists in database.

    Args:
        conn: MySQL connection
        task_id: Task ID to check

    Returns:
        True if task exists, False otherwise
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM tasks WHERE task_id = %s LIMIT 1", (task_id,))
        result = cursor.fetchone()
        return result is not None
    finally:
        cursor.close()


def insert_or_update_task(
    conn: MySQLConnection, task: Dict[str, Any], logger: logging.Logger
) -> bool:
    """Insert task or update if duplicate.

    Uses INSERT ... ON DUPLICATE KEY UPDATE pattern.
    Sets is_new=1 for new tasks, is_new=0 for updates.

    Args:
        conn: MySQL connection
        task: Task dictionary with all fields
        logger: Logger instance

    Returns:
        True if operation succeeded, False otherwise
    """
    cursor = conn.cursor()

    try:
        query = """
            INSERT INTO tasks (
                task_id, domain, customer, customer_url,
                external_links, title, time_passed, price, is_new
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                domain = VALUES(domain),
                customer = VALUES(customer),
                customer_url = VALUES(customer_url),
                external_links = VALUES(external_links),
                title = VALUES(title),
                time_passed = VALUES(time_passed),
                price = VALUES(price),
                is_new = 0,
                updated_at = CURRENT_TIMESTAMP
        """

        cursor.execute(
            query,
            (
                task["task_id"],
                task["domain"],
                task["customer"],
                task["customer_url"],
                task["external_links"],
                task["title"],
                task["time_passed"],
                task["price"],
            ),
        )

        conn.commit()

        if cursor.rowcount == 1:
            logger.debug(f"Inserted new task {task['task_id']}")
        else:
            logger.debug(f"Updated existing task {task['task_id']}")

        return True

    except mysql.connector.Error as e:
        logger.error(f"Failed to insert/update task {task['task_id']}: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()


def close_database(conn: MySQLConnection, logger: logging.Logger) -> None:
    """Close database connection safely.

    Args:
        conn: MySQL connection
        logger: Logger instance
    """
    if conn and conn.is_connected():
        conn.close()
        logger.info("Database connection closed")


# =============================================================================
# AUTHENTICATION
# =============================================================================


def initialize_driver(logger: logging.Logger) -> webdriver.Chrome:
    """Initialize headless Chrome driver.

    Args:
        logger: Logger instance

    Returns:
        Chrome WebDriver instance

    Raises:
        WebDriverException: If driver initialization fails
    """
    logger.info("Initializing Chrome WebDriver")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")

    # User-Agent spoofing
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(IMPLICIT_WAIT)
        logger.info("WebDriver initialized successfully")
        return driver

    except WebDriverException as e:
        logger.error(f"Failed to initialize WebDriver: {e}")
        raise


def is_authenticated(driver: webdriver.Chrome) -> bool:
    """Check if authenticated by page markup.

    Args:
        driver: Chrome WebDriver

    Returns:
        True if authenticated, False otherwise
    """
    try:
        driver.find_element(By.CSS_SELECTOR, SELECTOR_PROFILE_LINK)
        return True
    except NoSuchElementException:
        return False


def extract_captcha_sitekey(driver: webdriver.Chrome, logger: logging.Logger) -> Optional[str]:
    """Extract reCAPTCHA sitekey from page.

    Args:
        driver: Chrome WebDriver
        logger: Logger instance

    Returns:
        Sitekey string or None if not found
    """
    try:
        captcha_element = driver.find_element(By.CSS_SELECTOR, SELECTOR_CAPTCHA)
        sitekey = captcha_element.get_attribute("data-sitekey")
        logger.debug(f"Extracted captcha sitekey: {sitekey[:20]}...")
        return sitekey
    except NoSuchElementException:
        logger.warning("Captcha sitekey element not found")
        return None


def solve_captcha(
    api_key: str,
    website_url: str,
    sitekey: str,
    logger: logging.Logger,
    timeout: int = CAPTCHA_TIMEOUT,
) -> Optional[str]:
    """Solve reCAPTCHA using anti-captcha.com API.

    API Flow:
    1. POST /createTask to get taskId
    2. Poll /getTaskResult every 5s for up to timeout seconds
    3. Return gRecaptchaResponse token

    Args:
        api_key: Anti-captcha.com API key
        website_url: URL where captcha is located
        sitekey: reCAPTCHA site key
        logger: Logger instance
        timeout: Maximum seconds to wait for solution

    Returns:
        Captcha solution token or None if solving failed

    Raises:
        requests.RequestException: On network errors after retries
    """
    logger.info("Solving captcha via anti-captcha.com API")

    # Step 1: Create task
    create_payload = {
        "clientKey": api_key,
        "task": {
            "type": "NoCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": sitekey,
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"Creating captcha task (attempt {attempt}/{MAX_RETRIES})")

            response = requests.post(
                ANTICAPTCHA_CREATE_TASK_URL, json=create_payload, timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get("errorId", 0) != 0:
                logger.error(f"Anti-captcha API error: {result.get('errorDescription')}")
                return None

            task_id = result.get("taskId")
            if not task_id:
                logger.error("No taskId received from anti-captcha API")
                return None

            logger.info(f"Captcha task created: {task_id}")
            break

        except requests.RequestException as e:
            logger.warning(f"Failed to create captcha task (attempt {attempt}): {e}")

            if attempt < MAX_RETRIES:
                wait_time = 10
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error("All captcha task creation attempts failed")
                raise

    # Step 2: Poll for result
    get_payload = {"clientKey": api_key, "taskId": task_id}

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            time.sleep(CAPTCHA_POLL_INTERVAL)

            response = requests.post(
                ANTICAPTCHA_GET_RESULT_URL, json=get_payload, timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get("errorId", 0) != 0:
                logger.error(f"Anti-captcha API error: {result.get('errorDescription')}")
                return None

            status = result.get("status")
            if status == "ready":
                solution = result.get("solution", {}).get("gRecaptchaResponse")
                if solution:
                    logger.info("Captcha solved successfully")
                    return solution
                else:
                    logger.error("No solution in response")
                    return None

            elapsed = int(time.time() - start_time)
            logger.debug(f"Captcha status: {status} (elapsed: {elapsed}s)")

        except requests.RequestException as e:
            logger.warning(f"Failed to get captcha result: {e}")
            time.sleep(CAPTCHA_POLL_INTERVAL)

    logger.error(f"Captcha solving timed out after {timeout}s")
    return None


def authenticate(
    driver: webdriver.Chrome,
    credentials: Dict[str, str],
    anticaptcha_config: Dict[str, str],
    logger: logging.Logger,
) -> bool:
    """Authenticate on gogetlinks.net.

    Args:
        driver: Chrome WebDriver
        credentials: Username and password
        anticaptcha_config: Anti-captcha API configuration
        logger: Logger instance

    Returns:
        True if authentication succeeded, False otherwise
    """
    logger.info(f"Authenticating as {mask_email(credentials['username'])}")

    try:
        # Navigate to home page first
        logger.debug(f"Navigating to {HOME_URL}")
        driver.get(HOME_URL)

        # Wait for page to fully load
        time.sleep(2)

        # Check if already authenticated
        if is_authenticated(driver):
            logger.info("Already authenticated")
            return True

        # Click on "Войти" link to open login modal
        logger.debug(f"Looking for login button: {SELECTOR_LOGIN_BUTTON}")
        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)

        login_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTOR_LOGIN_BUTTON))
        )
        logger.debug("Login button found, clicking to open modal")
        login_button.click()

        # Wait for modal to appear and form fields to be visible
        logger.debug("Waiting for login modal to appear")
        time.sleep(2)

        # Extract captcha sitekey (optional - may not be present)
        sitekey = extract_captcha_sitekey(driver, logger)
        captcha_token = None

        if sitekey:
            # Solve captcha if present
            logger.info("Captcha detected, solving...")
            captcha_token = solve_captcha(
                api_key=anticaptcha_config["api_key"],
                website_url=LOGIN_URL,
                sitekey=sitekey,
                logger=logger,
            )

            if not captcha_token:
                logger.error("Failed to solve captcha")
                return False
        else:
            logger.info("No captcha detected on login page")

        # Fill login form in modal
        logger.debug("Filling login form in modal")

        logger.debug(f"Waiting for email field: {SELECTOR_LOGIN_EMAIL}")
        email_field = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTOR_LOGIN_EMAIL))
        )
        logger.debug("Email field found, filling...")
        email_field.clear()
        email_field.send_keys(credentials["username"])

        # Wait for password field
        logger.debug(f"Waiting for password field: {SELECTOR_LOGIN_PASSWORD}")
        password_field = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTOR_LOGIN_PASSWORD))
        )
        logger.debug("Password field found, filling...")
        password_field.clear()
        password_field.send_keys(credentials["password"])

        # Inject captcha token if present
        if captcha_token:
            logger.debug("Injecting captcha token")
            driver.execute_script(
                f"document.getElementById('g-recaptcha-response').innerHTML = '{captcha_token}';"
            )

        # Submit form - find button (it may be disabled initially)
        logger.debug(f"Waiting for submit button: {SELECTOR_LOGIN_SUBMIT}")
        submit_button = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SELECTOR_LOGIN_SUBMIT))
        )
        logger.debug("Submit button found")

        # Remove disabled attribute if present
        logger.debug("Enabling submit button")
        driver.execute_script("arguments[0].removeAttribute('disabled');", submit_button)

        # Scroll to button to ensure it's in viewport
        logger.debug("Scrolling to submit button")
        driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
        time.sleep(0.5)

        # Submit using JavaScript (more reliable than click)
        logger.debug("Submitting form via JavaScript")
        driver.execute_script("arguments[0].click();", submit_button)

        logger.debug("Form submitted successfully")

        # Wait for page load and verify authentication
        time.sleep(3)

        if is_authenticated(driver):
            logger.info("Authentication successful")
            return True
        else:
            logger.error("Authentication failed - credentials may be incorrect")
            return False

    except TimeoutException as e:
        logger.error(f"Timeout waiting for element during authentication: {e}")
        logger.debug("Page source length: %d", len(driver.page_source))
        return False
    except NoSuchElementException as e:
        logger.error(f"Element not found during authentication: {e}")
        return False
    except WebDriverException as e:
        logger.error(f"WebDriver error during authentication: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected authentication error: {type(e).__name__}: {e}")
        return False


# =============================================================================
# PARSER
# =============================================================================


def parse_price(text: str) -> Decimal:
    """Parse price from various formats.

    Handles: $123.45, 1,234.56, FREE, empty string -> 0.00

    Args:
        text: Price text to parse

    Returns:
        Decimal price value (0.00 if parsing fails)

    Example:
        >>> parse_price("$123.45")
        Decimal('123.45')
        >>> parse_price("FREE")
        Decimal('0.00')
    """
    if not text or text.strip().upper() in ("FREE", "N/A", ""):
        return Decimal("0.00")

    # Remove currency symbols and whitespace
    cleaned = re.sub(r"[$€£¥₽руб\s]", "", text)

    # Remove commas (thousand separators)
    cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def extract_task_id(row_id: str) -> int:
    """Extract task ID from row attribute.

    Args:
        row_id: Row ID string (e.g., "col_row_123456")

    Returns:
        Task ID as integer

    Raises:
        ValueError: If task_id cannot be extracted

    Example:
        >>> extract_task_id("col_row_123456")
        123456
    """
    parts = row_id.split("_")
    if len(parts) < 3:
        raise ValueError(f"Invalid row ID format: {row_id}")

    try:
        return int(parts[-1])
    except ValueError:
        raise ValueError(f"Could not parse task_id from: {row_id}")


def sanitize_text(text: str) -> str:
    """Clean HTML entities and whitespace.

    Args:
        text: Text to sanitize

    Returns:
        Cleaned text
    """
    # Unescape HTML entities
    text = html.unescape(text)

    # Normalize whitespace
    text = " ".join(text.split())

    return text.strip()


def parse_task_row(row: WebElement, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """Extract all fields from task row.

    Fields: task_id, title, domain, customer, customer_url,
            external_links, time_passed, price

    Args:
        row: Selenium WebElement for task row
        logger: Logger instance

    Returns:
        Task dictionary or None if parsing fails
    """
    try:
        # Extract task_id from row ID
        row_id = row.get_attribute("id")
        if not row_id:
            logger.warning("Row has no ID attribute")
            return None

        task_id = extract_task_id(row_id)

        # Find all cells
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            logger.warning(f"Task {task_id}: Expected 6+ cells, found {len(cells)}")
            return None

        # Cell 0: Domain
        try:
            domain_link = cells[0].find_element(By.TAG_NAME, "a")
            domain = sanitize_text(domain_link.text)
        except NoSuchElementException:
            domain = sanitize_text(cells[0].text)

        # Cell 1: Customer + customer_url
        try:
            customer_link = cells[1].find_element(By.TAG_NAME, "a")
            customer = sanitize_text(customer_link.text)
            customer_url = customer_link.get_attribute("href") or ""
        except NoSuchElementException:
            customer = sanitize_text(cells[1].text)
            customer_url = ""

        # Cell 2: External links
        external_links_text = sanitize_text(cells[2].text)
        try:
            external_links = int(external_links_text) if external_links_text else 0
        except ValueError:
            external_links = 0

        # Cell 3: Title
        try:
            title_link = cells[3].find_element(By.TAG_NAME, "a")
            title = sanitize_text(title_link.text)
        except NoSuchElementException:
            title = sanitize_text(cells[3].text)

        # Cell 4: Time passed
        time_passed = sanitize_text(cells[4].text)

        # Cell 5: Price
        price_text = sanitize_text(cells[5].text)
        price = parse_price(price_text)

        task = {
            "task_id": task_id,
            "domain": domain,
            "customer": customer,
            "customer_url": customer_url,
            "external_links": external_links,
            "title": title,
            "time_passed": time_passed,
            "price": price,
        }

        logger.debug(f"Parsed task {task_id}: {title[:50]}...")
        return task

    except Exception as e:
        logger.warning(f"Failed to parse task row: {e}")
        return None


def parse_task_list(driver: webdriver.Chrome, logger: logging.Logger) -> List[Dict[str, Any]]:
    """Parse all tasks from task list page.

    Args:
        driver: Chrome WebDriver
        logger: Logger instance

    Returns:
        List of task dictionaries
    """
    logger.info("Parsing task list")

    try:
        # Navigate to task list page
        logger.debug(f"Navigating to {TASK_LIST_URL}")
        driver.get(TASK_LIST_URL)

        # Wait for task rows to load
        logger.debug("Waiting for task rows")
        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTOR_TASK_ROWS)))

        # Find all task rows
        rows = driver.find_elements(By.CSS_SELECTOR, SELECTOR_TASK_ROWS)
        logger.info(f"Found {len(rows)} task rows")

        # Parse each row
        tasks = []
        for row in rows:
            task = parse_task_row(row, logger)
            if task:
                tasks.append(task)

        logger.info(f"Successfully parsed {len(tasks)} tasks")
        return tasks

    except TimeoutException:
        logger.error("Timeout waiting for task rows to load")
        return []

    except Exception as e:
        logger.error(f"Failed to parse task list: {e}")
        return []


# =============================================================================
# OUTPUT
# =============================================================================


def format_tasks_table(tasks: List[Dict[str, Any]]) -> str:
    """Format tasks as ASCII table.

    Args:
        tasks: List of task dictionaries

    Returns:
        Formatted table string
    """
    if not tasks:
        return "No tasks found."

    # Build table
    lines = []
    lines.append("=" * 100)
    lines.append(
        f"{'ID':<10} {'Domain':<20} {'Customer':<20} {'Price':<10} {'Time':<15}"
    )
    lines.append("-" * 100)

    for task in tasks:
        lines.append(
            f"{task['task_id']:<10} "
            f"{task['domain'][:20]:<20} "
            f"{task['customer'][:20]:<20} "
            f"${task['price']:<9.2f} "
            f"{task['time_passed'][:15]:<15}"
        )

    lines.append("=" * 100)
    lines.append(f"Total: {len(tasks)} tasks")

    return "\n".join(lines)


def print_tasks(tasks: List[Dict[str, Any]], enabled: bool) -> None:
    """Print tasks to console if enabled.

    Args:
        tasks: List of task dictionaries
        enabled: Whether to print output
    """
    if enabled:
        print("\n" + format_tasks_table(tasks) + "\n")


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0-99)
    """
    logger = None
    conn = None
    driver = None

    try:
        # 1. Setup logger (minimal config before loading config.ini)
        logger = setup_logger()
        logger.info("Starting Gogetlinks Task Parser")

        # 2. Load and validate config
        logger.info("Loading configuration")
        try:
            config = load_config()
            validate_config(config)
        except (FileNotFoundError, ValueError, configparser.Error) as e:
            if logger:
                logger.error(f"Configuration error: {e}")
            else:
                print(f"Configuration error: {e}", file=sys.stderr)
            return EXIT_CONFIG_ERROR

        # Reconfigure logger with settings from config
        logger = setup_logger(
            log_file=config["logging"]["log_file"],
            log_level=config["logging"]["log_level"],
        )

        # 3. Connect to database
        try:
            conn = connect_to_database(config, logger)
        except mysql.connector.Error as e:
            logger.error(f"Database error: {e}")
            return EXIT_DATABASE_ERROR

        # 4. Initialize browser
        try:
            driver = initialize_driver(logger)
        except WebDriverException as e:
            logger.error(f"WebDriver error: {e}")
            return EXIT_WEBDRIVER_ERROR

        # 5. Authenticate
        auth_success = authenticate(
            driver=driver,
            credentials=config["gogetlinks"],
            anticaptcha_config=config["anticaptcha"],
            logger=logger,
        )

        if not auth_success:
            logger.error("Authentication failed")
            return EXIT_AUTH_FAILED

        # 6. Parse task list
        tasks = parse_task_list(driver, logger)

        if not tasks:
            logger.warning("No tasks parsed")
            return EXIT_SUCCESS

        # 7. Save tasks to database
        logger.info(f"Saving {len(tasks)} tasks to database")
        success_count = 0
        for task in tasks:
            if insert_or_update_task(conn, task, logger):
                success_count += 1

        logger.info(f"Successfully saved {success_count}/{len(tasks)} tasks")

        # 8. Print output (if enabled)
        print_tasks(tasks, config["output"]["print_to_console"])

        logger.info("Parsing completed successfully")
        return EXIT_SUCCESS

    except KeyboardInterrupt:
        if logger:
            logger.info("Interrupted by user")
        return EXIT_UNEXPECTED

    except Exception as e:
        if logger:
            logger.critical(f"Unexpected error: {e}", exc_info=True)
        else:
            print(f"Unexpected error: {e}", file=sys.stderr)
        return EXIT_UNEXPECTED

    finally:
        # 9. Cleanup resources
        if driver:
            try:
                driver.quit()
                if logger:
                    logger.info("WebDriver closed")
            except Exception as e:
                if logger:
                    logger.warning(f"Error closing WebDriver: {e}")

        if conn:
            close_database(conn, logger)


if __name__ == "__main__":
    sys.exit(main())
