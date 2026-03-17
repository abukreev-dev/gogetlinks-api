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
import argparse
import html
import json
import logging
import os
import pickle
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import csv
import io

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
from selenium.webdriver.support.ui import Select, WebDriverWait

# =============================================================================
# CONSTANTS
# =============================================================================

# URLs
HOME_URL = "https://gogetlinks.net"
LOGIN_URL = "https://gogetlinks.net/user/signIn"
TASK_LIST_URL = "https://gogetlinks.net/webTask/index"
TASK_DETAIL_URL = "https://gogetlinks.net/template/view_task.php?curr_id={}"
MY_SITES_URL = "https://gogetlinks.net/mySites"
MY_SITES_CHANGE_COUNT_URL = "https://gogetlinks.net/mySites/changeCountInPage"

# Links export URLs
PAID_LINKS_URL = "https://gogetlinks.net/webTask/index/action/viewPaid"
WAIT_INDEXATION_URL = "https://gogetlinks.net/webTask/index/action/viewWaitIndexation"
CSV_DOWNLOAD_PAID_URL = (
    "https://gogetlinks.net/template/download_csv_file.php?action=web_paid"
)
CSV_DOWNLOAD_WAIT_URL = (
    "https://gogetlinks.net/template/download_csv_file.php?action=web_wait_indexation"
)
DEFAULT_FALLBACK_PROXY = os.getenv("GGL_FALLBACK_PROXY", "127.0.0.1:3128").strip()
SITES_LOCK_FILE = os.getenv(
    "GGL_SITES_LOCK_FILE", "/tmp/gogetlinks_mysites.lock"
).strip()
SITES_LOCK_TTL_SECONDS = 3 * 60 * 60  # 3 hours

# Database objects
DB_SCHEMA = "ddl"
DB_TABLE = "ggl_tasks"
DB_FULL_TABLE = f"{DB_SCHEMA}.{DB_TABLE}"
DB_LINKS_TABLE = "ggl_links"
DB_FULL_LINKS_TABLE = f"{DB_SCHEMA}.{DB_LINKS_TABLE}"

# Timeouts
CAPTCHA_TIMEOUT = 120
CAPTCHA_POLL_INTERVAL = 5
MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 10
IMPLICIT_WAIT = 5
LINK_CHECK_TIMEOUT = 10

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

# Detail modal selectors
SELECTOR_DETAIL_LINK = "a[rel='modal:open']"
SELECTOR_MODAL = ".jquery-modal.blocker"
SELECTOR_MODAL_CONTENT = ".modal"
SELECTOR_MODAL_CLOSE = "a[rel='modal:close']"

# Rate limiting for detail parsing
DETAIL_REQUEST_DELAY = 1.5

# Stale tasks alert
NO_NEW_TASKS_THRESHOLD_DAYS = 5

# Session persistence
COOKIE_FILE = "session_cookies.pkl"

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
        "telegram": {
            "enabled": parser.getboolean("telegram", "enabled", fallback=False),
            "bot_token": parser.get("telegram", "bot_token", fallback=""),
            "chat_id": parser.get("telegram", "chat_id", fallback=""),
            "mention": parser.get("telegram", "mention", fallback=""),
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


def is_pid_alive(pid: int) -> bool:
    """Return True if process with PID exists, False otherwise."""
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_sites_lock(
    logger: logging.Logger,
    lock_file: str = SITES_LOCK_FILE,
    ttl_seconds: int = SITES_LOCK_TTL_SECONDS,
) -> tuple[bool, str]:
    """Acquire lock for mySites stage.

    Returns:
        (acquired, reason)
    """
    current_pid = os.getpid()
    now = time.time()
    payload = {
        "pid": current_pid,
        "started_at": now,
        "mode": "sites",
    }

    for _ in range(2):
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            return True, "acquired"
        except FileExistsError:
            pass

        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue

        owner_pid = int(existing.get("pid", 0) or 0)
        started_at = float(existing.get("started_at", 0.0) or 0.0)
        if started_at <= 0:
            try:
                started_at = os.path.getmtime(lock_file)
            except OSError:
                started_at = now

        age_seconds = max(0.0, now - started_at)
        owner_alive = is_pid_alive(owner_pid)

        if owner_alive:
            return False, (
                f"active lock held by pid={owner_pid} "
                f"(age={int(age_seconds)}s)"
            )

        if age_seconds > ttl_seconds:
            logger.warning(
                "Found stale mySites lock: "
                f"pid={owner_pid}, age={int(age_seconds)}s; removing"
            )
            try:
                os.remove(lock_file)
            except FileNotFoundError:
                pass
            except OSError as e:
                return False, f"failed to remove stale lock: {e}"
            continue

        return False, (
            f"dead lock owner pid={owner_pid}, age={int(age_seconds)}s "
            f"(ttl={ttl_seconds}s)"
        )

    return False, "lock exists and could not be acquired"


def release_sites_lock(
    logger: logging.Logger,
    lock_file: str = SITES_LOCK_FILE,
) -> None:
    """Release mySites lock if owned by current process."""
    current_pid = os.getpid()

    try:
        with open(lock_file, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        return
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read mySites lock for release: {e}")
        return

    owner_pid = int(existing.get("pid", 0) or 0)
    if owner_pid != current_pid:
        logger.warning(
            "Skip releasing mySites lock owned by another pid: "
            f"{owner_pid}"
        )
        return

    try:
        os.remove(lock_file)
    except FileNotFoundError:
        return
    except OSError as e:
        logger.warning(f"Failed to remove mySites lock: {e}")


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
        cursor.execute(
            f"SELECT 1 FROM {DB_FULL_TABLE} WHERE task_id = %s LIMIT 1",
            (task_id,),
        )
        result = cursor.fetchone()
        return result is not None
    finally:
        cursor.close()


def task_has_details(conn: MySQLConnection, task_id: int) -> bool:
    """Check if task already has details parsed in database.

    Used to skip re-fetching detail modals for tasks that were
    already fully parsed in a previous run.

    Args:
        conn: MySQL connection
        task_id: Task ID to check

    Returns:
        True if task exists and has non-empty description
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT 1 FROM {DB_FULL_TABLE} WHERE task_id = %s"
            " AND description IS NOT NULL AND description != '' LIMIT 1",
            (task_id,),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def insert_or_update_task(
    conn: MySQLConnection, task: Dict[str, Any], logger: logging.Logger
) -> Optional[bool]:
    """Insert task or update if duplicate.

    Uses INSERT ... ON DUPLICATE KEY UPDATE pattern.
    Sets is_new=1 for new tasks, is_new=0 for updates.

    Args:
        conn: MySQL connection
        task: Task dictionary with all fields
        logger: Logger instance

    Returns:
        True if task is new (inserted), False if updated, None if failed
    """
    cursor = conn.cursor()

    try:
        query = f"""
            INSERT INTO {DB_FULL_TABLE} (
                task_id, domain, customer, customer_url,
                external_links, title, time_passed, price,
                description, url, requirements, contacts, deadline,
                is_new
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                domain = VALUES(domain),
                customer = VALUES(customer),
                customer_url = VALUES(customer_url),
                external_links = VALUES(external_links),
                title = VALUES(title),
                time_passed = VALUES(time_passed),
                price = VALUES(price),
                description = VALUES(description),
                url = VALUES(url),
                requirements = VALUES(requirements),
                contacts = VALUES(contacts),
                deadline = VALUES(deadline),
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
                task.get("description"),
                task.get("url"),
                task.get("requirements"),
                task.get("contacts"),
                task.get("deadline"),
            ),
        )

        conn.commit()

        is_new = cursor.rowcount == 1
        if is_new:
            logger.debug(f"Inserted new task {task['task_id']}")
        else:
            logger.debug(f"Updated existing task {task['task_id']}")

        return is_new

    except mysql.connector.Error as e:
        logger.error(f"Failed to insert/update task {task['task_id']}: {e}")
        conn.rollback()
        return None

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


def get_days_since_last_new_task(
    conn: MySQLConnection, logger: logging.Logger
) -> Optional[int]:
    """Return number of whole days since the last new task was inserted.

    Args:
        conn: MySQL connection
        logger: Logger instance

    Returns:
        Number of days since last new task, or None if table is empty or query fails
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT DATEDIFF(NOW(), MAX(created_at)) FROM {DB_FULL_TABLE}"
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
    except mysql.connector.Error as e:
        logger.error(f"Failed to check last new task age: {e}")
        return None
    finally:
        cursor.close()


# =============================================================================
# AUTHENTICATION
# =============================================================================


def initialize_driver(
    logger: logging.Logger,
    proxy_server: Optional[str] = None,
) -> webdriver.Chrome:
    """Initialize headless Chrome driver.

    Args:
        logger: Logger instance

    Returns:
        Chrome WebDriver instance

    Raises:
        WebDriverException: If driver initialization fails
    """
    if proxy_server:
        logger.info(f"Initializing Chrome WebDriver (proxy: {proxy_server})")
    else:
        logger.info("Initializing Chrome WebDriver")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    if proxy_server:
        options.add_argument(f"--proxy-server=http://{proxy_server}")

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


def is_anti_bot_blocked(driver: webdriver.Chrome) -> bool:
    """Detect anti-bot/forbidden pages that block login flow."""
    try:
        current_url = (driver.current_url or "").lower()
    except Exception:
        current_url = ""

    if "/403.php" in current_url:
        return True

    try:
        source = (driver.page_source or "").lower()
    except Exception:
        source = ""

    block_markers = (
        "qrator",
        "/403.php",
        "403 forbidden",
        "access denied",
    )
    return any(marker in source for marker in block_markers)


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


def save_cookies(driver: webdriver.Chrome, logger: logging.Logger) -> None:
    """Save browser cookies to file for session persistence.

    Args:
        driver: Chrome WebDriver with active session
        logger: Logger instance
    """
    try:
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
        os.chmod(COOKIE_FILE, 0o600)
        logger.info(f"Saved {len(cookies)} cookies to {COOKIE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save cookies: {e}")


def load_cookies(driver: webdriver.Chrome, logger: logging.Logger) -> bool:
    """Load cookies from file and verify authentication.

    Args:
        driver: Chrome WebDriver
        logger: Logger instance

    Returns:
        True if cached session is valid, False otherwise
    """
    if not os.path.exists(COOKIE_FILE):
        logger.debug("No cookie file found")
        return False

    # Verify file permissions (not wider than 0o600)
    stat = os.stat(COOKIE_FILE)
    if stat.st_mode & 0o077:
        logger.warning("Cookie file has insecure permissions, skipping")
        return False

    try:
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
    except Exception as e:
        logger.warning(f"Failed to load cookies: {e}")
        return False

    # Navigate to domain first (required for adding cookies)
    driver.get(HOME_URL)
    time.sleep(2)

    for cookie in cookies:
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            logger.debug(f"Skipping cookie {cookie.get('name', '?')}: {e}")

    # Refresh page with cookies applied
    driver.get(HOME_URL)
    time.sleep(2)

    if is_authenticated(driver):
        logger.info("Using cached session (cookies loaded successfully)")
        return True

    logger.info("Cached session expired, need fresh authentication")
    # Remove stale cookie file
    try:
        os.remove(COOKIE_FILE)
    except OSError:
        pass
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
                """
                var textarea = document.getElementById('g-recaptcha-response');
                if (textarea) {
                    textarea.value = arguments[0];
                    textarea.innerHTML = arguments[0];
                }
                // Call reCAPTCHA callback if defined
                var recaptchaEl = document.querySelector('.g-recaptcha[data-callback]');
                if (recaptchaEl) {
                    var cbName = recaptchaEl.getAttribute('data-callback');
                    if (cbName && typeof window[cbName] === 'function') {
                        window[cbName](arguments[0]);
                    }
                }
                """,
                captcha_token,
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

        # Wait for page to change after form submission (up to 15s)
        auth_timeout = 15
        logger.debug(f"Waiting up to {auth_timeout}s for auth redirect")
        try:
            WebDriverWait(driver, auth_timeout).until(
                lambda d: is_authenticated(d)
                or SELECTOR_LOGIN_BUTTON not in d.page_source
            )
        except TimeoutException:
            logger.debug("Auth redirect wait timed out")

        if is_authenticated(driver):
            logger.info("Authentication successful")
            return True
        else:
            current_url = driver.current_url
            page_title = driver.title
            logger.error(
                f"Authentication failed - credentials may be incorrect "
                f"(url={current_url}, title={page_title})"
            )
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

    # Remove currency symbols and whitespace (case-insensitive for Cyrillic: Р/р, У/у, Б/б)
    cleaned = re.sub(r"[$€£¥₽руб\s]", "", text, flags=re.IGNORECASE)

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

        # Cell 0: Domain + task type (e.g. "stroimdacha.ru\nЗаметка")
        try:
            domain_link = cells[0].find_element(By.TAG_NAME, "a")
            domain = sanitize_text(domain_link.text)
        except NoSuchElementException:
            domain = sanitize_text(cells[0].text)

        # Extract task type from campaign div under domain
        try:
            campaign_div = cells[0].find_element(
                By.CSS_SELECTOR, ".site-link__campaign"
            )
            title = sanitize_text(campaign_div.text)
        except NoSuchElementException:
            title = ""

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

        # Cell 4: Time passed
        time_passed = sanitize_text(cells[4].text)

        # Cell 5: Price
        price_text = sanitize_text(cells[5].text)
        logger.debug(f"Task {task_id} price_text raw: {repr(price_text)}")
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


def parse_task_details(
    driver: webdriver.Chrome, task_id: int, logger: logging.Logger
) -> Dict[str, Any]:
    """Parse task details from AJAX modal.

    Opens the detail modal for a task via JavaScript, extracts additional
    fields from the modal's .tv_params_block structure:
    - description: "Текст задания" + "Комментарий оптимизатора"
    - url: from #copy_url input or .param.link_to a
    - requirements: "Требования к странице" block params
    - contacts: not present in current modal format
    - deadline: not present in current modal format

    Args:
        driver: Chrome WebDriver
        task_id: Task ID to fetch details for
        logger: Logger instance

    Returns:
        Dictionary with detail fields (may be partially empty)
    """
    details: Dict[str, Any] = {
        "description": None,
        "url": None,
        "requirements": None,
        "contacts": None,
        "deadline": None,
    }

    try:
        detail_url = TASK_DETAIL_URL.format(task_id)
        logger.debug(f"Opening detail modal for task {task_id}: {detail_url}")

        # Remove any leftover modals from previous iterations
        driver.execute_script(
            "$('.jquery-modal').remove(); $('.modal').remove();"
        )
        time.sleep(0.3)

        driver.execute_script(
            f"$.get('{detail_url}', function(data) {{"
            f"  $('<div>').html(data).appendTo('body').modal();"
            f"}});"
        )

        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTOR_MODAL)))
        time.sleep(0.5)

        modal = driver.find_element(By.CSS_SELECTOR, SELECTOR_MODAL_CONTENT)

        # Extract URL from hidden #copy_url input
        try:
            copy_url_input = modal.find_element(By.CSS_SELECTOR, "#copy_url")
            url_value = copy_url_input.get_attribute("value")
            if url_value:
                details["url"] = url_value.strip()
        except NoSuchElementException:
            # Fallback: extract from .param.link_to a
            try:
                link_elem = modal.find_element(
                    By.CSS_SELECTOR, ".param.link_to .block_value a"
                )
                href = link_elem.get_attribute("href") or ""
                parsed = urlparse(href)
                if parsed.netloc and "gogetlinks.net" not in parsed.netloc:
                    details["url"] = href
            except NoSuchElementException:
                pass

        # Extract structured data from .tv_params_block sections
        blocks = modal.find_elements(By.CSS_SELECTOR, ".tv_params_block")
        description_parts = []

        for block in blocks:
            try:
                title_elem = block.find_element(By.CSS_SELECTOR, ".block_title")
                block_title = sanitize_text(title_elem.text).lower()
            except NoSuchElementException:
                continue

            if "требовани" in block_title:
                # Requirements block: collect all param name-value pairs
                params = block.find_elements(By.CSS_SELECTOR, ".param")
                req_parts = []
                for param in params:
                    try:
                        name = sanitize_text(
                            param.find_element(
                                By.CSS_SELECTOR, ".block_name"
                            ).text
                        )
                        value = sanitize_text(
                            param.find_element(
                                By.CSS_SELECTOR, ".block_value"
                            ).text
                        )
                        if name and value:
                            req_parts.append(f"{name}: {value}")
                    except NoSuchElementException:
                        continue
                if len(req_parts) > 0:
                    details["requirements"] = "; ".join(req_parts)

            elif "текст задани" in block_title:
                # Task description text
                try:
                    value_elem = block.find_element(
                        By.CSS_SELECTOR, ".params .block_value"
                    )
                    text = sanitize_text(value_elem.text)
                    if len(text) > 0:
                        description_parts.append(text)
                except NoSuchElementException:
                    pass

            elif "комментарий" in block_title:
                # Optimizer's comment — append to description
                try:
                    value_elem = block.find_element(
                        By.CSS_SELECTOR, ".params .block_value"
                    )
                    text = sanitize_text(value_elem.text)
                    if len(text) > 0:
                        description_parts.append(f"[Комментарий] {text}")
                except NoSuchElementException:
                    pass

            elif "ссылк" in block_title:
                # Link block: extract anchor text
                try:
                    anchor_elem = block.find_element(
                        By.CSS_SELECTOR, ".param.unchor .block_value"
                    )
                    anchor_text = sanitize_text(anchor_elem.text)
                    if anchor_text and len(anchor_text) > 0:
                        description_parts.append(f"[Анкор] {anchor_text}")
                except NoSuchElementException:
                    pass

        if len(description_parts) > 0:
            details["description"] = "\n".join(description_parts)

        logger.debug(
            f"Task {task_id} details: "
            f"desc={'yes' if details['description'] else 'no'}, "
            f"url={'yes' if details['url'] else 'no'}, "
            f"req={'yes' if details['requirements'] else 'no'}"
        )

    except TimeoutException:
        logger.warning(f"Timeout opening detail modal for task {task_id}")

    except Exception as e:
        logger.warning(f"Failed to parse details for task {task_id}: {e}")

    finally:
        # Close modal
        try:
            close_buttons = driver.find_elements(
                By.CSS_SELECTOR, SELECTOR_MODAL_CLOSE
            )
            for btn in close_buttons:
                try:
                    btn.click()
                except Exception:
                    pass
            driver.execute_script("$.modal.close();")
        except Exception:
            pass

        # Rate limiting
        time.sleep(DETAIL_REQUEST_DELAY)

    return details


def parse_task_list(
    driver: webdriver.Chrome,
    logger: logging.Logger,
    conn: Optional[MySQLConnection] = None,
) -> List[Dict[str, Any]]:
    """Parse all tasks from task list page.

    Args:
        driver: Chrome WebDriver
        logger: Logger instance
        conn: Optional MySQL connection. When provided, detail modals are
            skipped for tasks that already have a description in the database.

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

        logger.info(f"Successfully parsed {len(tasks)} tasks from list")

        # Parse details for each task (skip tasks already in DB with details)
        if len(tasks) > 0:
            tasks_to_fetch = [
                t for t in tasks
                if conn is None or not task_has_details(conn, t["task_id"])
            ]
            skipped = len(tasks) - len(tasks_to_fetch)
            if skipped > 0:
                logger.info(
                    f"Skipping detail fetch for {skipped} already-parsed tasks"
                )
            if len(tasks_to_fetch) > 0:
                logger.info(f"Parsing details for {len(tasks_to_fetch)} tasks")
                for task in tasks_to_fetch:
                    details = parse_task_details(driver, task["task_id"], logger)
                    task.update(details)

            logger.info("Detail parsing completed")

        return tasks

    except TimeoutException:
        logger.error("Timeout waiting for task rows to load")
        return []

    except Exception as e:
        logger.error(f"Failed to parse task list: {e}")
        return []


def extract_digits_only(text: str) -> Optional[int]:
    """Extract digits from text and return as int.

    Examples:
        "123" -> 123
        "CF 20 / TF 11" -> 2011
        "N/A" -> None
    """
    if not text:
        return None

    digits = "".join(re.findall(r"\d+", text))
    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def set_my_sites_count_in_page(driver: webdriver.Chrome, logger: logging.Logger) -> None:
    """Try to set mySites page size to maximum value."""
    select_candidates = [
        "select[name='count_in_page']",
        "select#count_in_page",
        "select.js-count-in-page",
    ]

    for selector in select_candidates:
        try:
            select_elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(select_elements) == 0:
                continue

            select = Select(select_elements[0])
            values: List[int] = []
            for option in select.options:
                option_value = option.get_attribute("value") or option.text
                value_num = extract_digits_only(option_value)
                if value_num is not None:
                    values.append(value_num)

            if len(values) == 0:
                continue

            max_value = max(values)
            try:
                select.select_by_value(str(max_value))
            except NoSuchElementException:
                select.select_by_visible_text(str(max_value))

            logger.info(f"mySites page size changed via selector to {max_value}")
            time.sleep(1.5)
            return

        except Exception as e:
            logger.debug(
                f"Failed to set page size using selector {selector}: {type(e).__name__}: {e}"
            )

    try:
        # Fallback for new frontend: same-origin POST to change count in page.
        result = driver.execute_async_script(
            """
            const callback = arguments[arguments.length - 1];
            const url = arguments[0];
            fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
                },
                body: 'count_in_page=2000'
            }).then((response) => {
                callback({ok: response.ok, status: response.status});
            }).catch((error) => {
                callback({ok: false, error: String(error)});
            });
            """,
            MY_SITES_CHANGE_COUNT_URL,
        )

        if isinstance(result, dict) and result.get("ok"):
            logger.info("mySites page size changed via POST to 2000")
            time.sleep(1.0)
            return

        logger.warning(f"mySites page size POST returned unexpected result: {result}")

    except Exception as e:
        logger.warning(f"Failed to set mySites page size via POST: {e}")


def parse_site_row(
    row: WebElement,
) -> Optional[Dict[str, Any]]:
    """Parse one row from /mySites table."""
    cells = row.find_elements(By.TAG_NAME, "td")
    if len(cells) < 10:
        return None

    site = ""
    try:
        site_link = row.find_element(By.CSS_SELECTOR, ".site-link__info")
        site = sanitize_text(site_link.text)
    except NoSuchElementException:
        try:
            site = sanitize_text(cells[0].text)
        except Exception:
            site = ""

    if not site:
        return None

    status = sanitize_text(cells[1].text)
    sqi = extract_digits_only(sanitize_text(cells[2].text))
    cf_tf = extract_digits_only(sanitize_text(cells[3].text))
    traffic = extract_digits_only(sanitize_text(cells[5].text))
    trust = extract_digits_only(sanitize_text(cells[9].text))

    # Reject reason parsing is intentionally disabled: keep status only.
    description = None

    return {
        "site": site.lower(),
        "status": status,
        "sqi": sqi,
        "cf_tf": cf_tf,
        "traffic": traffic,
        "trust": trust,
        "description": description,
    }


def get_my_sites_rows(driver: webdriver.Chrome) -> List[WebElement]:
    """Return rows from mySites table that look like data rows."""
    return [
        row
        for row in driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        if len(row.find_elements(By.TAG_NAME, "td")) >= 10
    ]


def get_page_marker(rows: List[WebElement]) -> str:
    """Build a simple marker to detect page change."""
    if len(rows) == 0:
        return ""

    try:
        first_text = sanitize_text(rows[0].text)
        last_text = sanitize_text(rows[-1].text)
        return f"{first_text}|{last_text}|{len(rows)}"
    except Exception:
        return str(len(rows))


def go_to_next_my_sites_page(driver: webdriver.Chrome, logger: logging.Logger) -> bool:
    """Click next page button on mySites if available."""
    current_rows = get_my_sites_rows(driver)
    current_marker = get_page_marker(current_rows)
    next_button: Optional[WebElement] = None
    next_page = None

    # New GGL pagination: .pagination__item_current + links with onclick="mySites.load(N)".
    current_page = None
    try:
        current_page_el = driver.find_element(
            By.CSS_SELECTOR, ".pagination .pagination__item_current"
        )
        current_page_text = sanitize_text(current_page_el.text)
        if current_page_text.isdigit():
            current_page = int(current_page_text)
    except Exception:
        pass

    try:
        load_links = driver.find_elements(
            By.CSS_SELECTOR, ".pagination a[onclick*='mySites.load(']"
        )
        page_to_link: Dict[int, WebElement] = {}
        for link in load_links:
            onclick = link.get_attribute("onclick") or ""
            match = re.search(r"mySites\.load\((\d+)\)", onclick)
            if match:
                page_no = int(match.group(1))
                page_to_link[page_no] = link

        if current_page is not None:
            next_page = current_page + 1
            next_button = page_to_link.get(next_page)
        elif len(page_to_link) > 0:
            next_button = page_to_link[sorted(page_to_link.keys())[0]]
    except Exception:
        pass

    if next_button is None:
        # Fallback to common next controls.
        next_selectors = [
            ".pagination .next:not(.disabled) a",
            "a[rel='next']",
            "li.next:not(.disabled) a",
        ]
        for selector in next_selectors:
            try:
                candidates = driver.find_elements(By.CSS_SELECTOR, selector)
                for candidate in candidates:
                    if candidate.is_displayed():
                        next_button = candidate
                        break
                if next_button is not None:
                    break
            except Exception:
                continue

    if next_button is None:
        return False

    try:
        # GGL pagination often works via JS callback mySites.load(page).
        onclick = next_button.get_attribute("onclick") or ""
        if next_page is not None and "mySites.load(" in onclick:
            driver.execute_script("if (window.mySites) { window.mySites.load(arguments[0]); }", next_page)
        elif "mySites.load(" in onclick:
            match = re.search(r"mySites\.load\((\d+)\)", onclick)
            if match:
                driver.execute_script(
                    "if (window.mySites) { window.mySites.load(arguments[0]); }",
                    int(match.group(1)),
                )
            else:
                driver.execute_script("arguments[0].click();", next_button)
        else:
            driver.execute_script("arguments[0].click();", next_button)

        current_page_text = str(current_page) if current_page is not None else None
        deadline = time.time() + (PAGE_LOAD_TIMEOUT * 3)

        while time.time() < deadline:
            try:
                new_marker = get_page_marker(get_my_sites_rows(driver))
                new_page_text = driver.execute_script(
                    "const el = document.querySelector('.pagination .pagination__item_current');"
                    "return el ? (el.textContent || '').trim() : '';"
                ) or ""

                if new_marker and new_marker != current_marker:
                    return True
                if current_page_text and new_page_text and new_page_text != current_page_text:
                    return True
                if next_page is not None and new_page_text == str(next_page):
                    return True
            except Exception:
                pass

            time.sleep(0.25)

        logger.debug("mySites next page action did not change marker/current page")
        return False
    except Exception as e:
        logger.debug(f"Failed to navigate mySites pagination: {type(e).__name__}: {e}")
        return False


def parse_my_sites(
    driver: webdriver.Chrome,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    """Parse /mySites table and return normalized site metrics."""
    logger.info("Parsing mySites page")

    try:
        driver.get(MY_SITES_URL)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        set_my_sites_count_in_page(driver, logger)

        # Reload page to apply count-in-page state and wait for rows.
        driver.get(MY_SITES_URL)
        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
        wait.until(
            lambda d: len(
                [
                    row
                    for row in d.find_elements(By.CSS_SELECTOR, "table tbody tr")
                    if len(row.find_elements(By.TAG_NAME, "td")) >= 10
                ]
            )
            > 0
            or "нет сайтов" in d.page_source.lower()
        )

        rows = get_my_sites_rows(driver)
        if len(rows) == 0:
            logger.warning("No rows found on mySites page")
            return []

        sites_by_host: Dict[str, Dict[str, Any]] = {}
        page_num = 1

        while True:
            page_rows = get_my_sites_rows(driver)
            for row in page_rows:
                site_data = parse_site_row(row)
                if site_data:
                    sites_by_host[site_data["site"]] = site_data

            logger.info(
                f"mySites page {page_num}: rows={len(page_rows)}, "
                f"accumulated={len(sites_by_host)}"
            )

            if not go_to_next_my_sites_page(driver, logger):
                break

            page_num += 1

        sites = list(sites_by_host.values())
        logger.info(f"mySites parsed: {len(sites)} sites across {page_num} page(s)")
        return sites

    except TimeoutException:
        logger.error("Timeout waiting for mySites table rows")
        return []

    except Exception as e:
        logger.error(f"Failed to parse mySites page: {e}")
        return []


def save_sites_to_db(
    conn: MySQLConnection,
    sites: List[Dict[str, Any]],
    logger: logging.Logger,
) -> tuple[int, List[Dict[str, str]]]:
    """Update ddl.domain rows by host with metrics parsed from /mySites."""
    if len(sites) == 0:
        logger.info("No mySites data to save")
        return 0, []

    query = """
        UPDATE domain SET
            ggl_status = %s,
            ggl_description = %s,
            ggl_traffic = %s,
            ggl_sqi = %s,
            ggl_cf_tf = %s,
            ggl_trust = %s,
            ggl_update_at = NOW()
        WHERE host = %s
    """

    updated_count = 0
    status_changes: List[Dict[str, str]] = []
    cursor = conn.cursor()

    try:
        hosts = [site.get("site") for site in sites if site.get("site")]
        existing_status_map: Dict[str, Optional[str]] = {}
        if len(hosts) > 0:
            placeholders = ", ".join(["%s"] * len(hosts))
            cursor.execute(
                f"SELECT host, ggl_status FROM domain WHERE host IN ({placeholders})",
                tuple(hosts),
            )
            for host, ggl_status in cursor.fetchall():
                if host:
                    existing_status_map[str(host).lower()] = ggl_status

        for site in sites:
            host = site.get("site")
            new_status_raw = site.get("status")
            new_status = sanitize_text(new_status_raw) if new_status_raw else ""
            old_status_raw = existing_status_map.get(host, "")
            old_status = sanitize_text(old_status_raw) if old_status_raw else ""

            if host and host in existing_status_map and old_status != new_status:
                status_changes.append(
                    {
                        "site": host,
                        "old_status": old_status or "—",
                        "new_status": new_status or "—",
                    }
                )

            cursor.execute(
                query,
                (
                    new_status_raw,
                    site.get("description"),
                    site.get("traffic"),
                    site.get("sqi"),
                    site.get("cf_tf"),
                    site.get("trust"),
                    host,
                ),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                updated_count += cursor.rowcount

        conn.commit()

        logger.info(
            "mySites DB update completed: "
            f"parsed={len(sites)}, updated={updated_count}, "
            f"status_changed={len(status_changes)}"
        )
        return updated_count, status_changes

    except mysql.connector.Error as e:
        conn.rollback()
        logger.error(f"Failed to update domain metrics: {e}")
        return 0, []

    finally:
        cursor.close()


# =============================================================================
# LINKS SYNC & CHECK
# =============================================================================


def get_selenium_cookies_session(
    driver: webdriver.Chrome,
    logger: logging.Logger,
    proxy_server: Optional[str] = None,
) -> requests.Session:
    """Create requests.Session with cookies transferred from Selenium."""
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(
            cookie["name"], cookie["value"], domain=cookie.get("domain")
        )
    ua = driver.execute_script("return navigator.userAgent")
    session.headers["User-Agent"] = ua
    if proxy_server:
        session.proxies = {
            "http": f"http://{proxy_server}",
            "https": f"http://{proxy_server}",
        }
        logger.debug("Using proxy %s for requests session", proxy_server)
    logger.debug("Transferred %d cookies to requests session", len(driver.get_cookies()))
    return session


def download_csv_export(
    session: requests.Session,
    download_url: str,
    post_data: Dict[str, str],
    logger: logging.Logger,
    referer: Optional[str] = None,
) -> Optional[str]:
    """Download CSV export via POST and return decoded text.

    Args:
        session: requests session with auth cookies
        download_url: URL of the CSV download endpoint
        post_data: form fields to send (checkbox names)
        logger: Logger instance
        referer: Referer header value (page the export was initiated from)

    Returns:
        CSV text (decoded from windows-1251) or None on error
    """
    try:
        headers = {}
        if referer:
            headers["Referer"] = referer
        resp = session.post(
            download_url, data=post_data, timeout=30, headers=headers
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type and len(resp.content) > 10000:
            logger.error(
                "Got HTML instead of CSV from %s (possibly not authenticated)",
                download_url,
            )
            return None

        csv_text = resp.content.decode("windows-1251")
        logger.info(
            "Downloaded CSV from %s: %d bytes, %d lines",
            download_url,
            len(resp.content),
            csv_text.count("\n"),
        )
        return csv_text

    except requests.RequestException as e:
        logger.error("Failed to download CSV from %s: %s", download_url, e)
        return None


def parse_links_csv(
    csv_text: str, status: str, logger: logging.Logger
) -> List[Dict[str, Any]]:
    """Parse CSV export of paid/wait_indexation links.

    Args:
        csv_text: CSV content (already decoded)
        status: 'paid' or 'wait_indexation'
        logger: Logger instance

    Returns:
        List of dicts with keys: url, date_paid (str or None), status
    """
    links: List[Dict[str, Any]] = []
    reader = csv.reader(io.StringIO(csv_text), delimiter=";", quotechar='"')

    header = next(reader, None)
    if header is None:
        logger.warning("Empty CSV for status=%s", status)
        return links

    logger.debug("CSV header for %s: %s", status, header)

    for row in reader:
        if not row or not row[0].strip():
            continue

        url = row[0].strip().strip('"')
        if not url.startswith("http"):
            continue

        date_paid = None
        if status == "paid" and len(row) > 1:
            raw_date = row[1].strip().strip('"')
            # Format: dd.mm.yyyy → yyyy-mm-dd
            try:
                parts = raw_date.split(".")
                if len(parts) == 3:
                    date_paid = f"{parts[2]}-{parts[1]}-{parts[0]}"
            except (IndexError, ValueError):
                logger.debug("Could not parse date: %s", raw_date)

        links.append({"url": url, "date_paid": date_paid, "status": status})

    logger.info("Parsed %d links with status=%s", len(links), status)
    return links


def sync_links_to_db(
    conn: MySQLConnection,
    links: List[Dict[str, Any]],
    logger: logging.Logger,
) -> Tuple[int, int, int]:
    """Sync links to ggl_links table.

    Inserts new, updates existing, deletes removed links.

    Returns:
        Tuple of (inserted, updated, deleted) counts
    """
    if not links:
        logger.warning("No links to sync")
        return 0, 0, 0

    cursor = conn.cursor()
    inserted = 0
    updated = 0

    try:
        for link in links:
            cursor.execute(
                f"""INSERT INTO {DB_FULL_LINKS_TABLE}
                    (url, date_paid, status)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        date_paid = VALUES(date_paid),
                        status = VALUES(status)
                """,
                (link["url"], link["date_paid"], link["status"]),
            )
            if cursor.rowcount == 1:
                inserted += 1
            elif cursor.rowcount == 2:
                updated += 1

        # Delete links that are no longer in either list
        all_urls = [link["url"] for link in links]
        if all_urls:
            placeholders = ", ".join(["%s"] * len(all_urls))
            cursor.execute(
                f"DELETE FROM {DB_FULL_LINKS_TABLE} WHERE url NOT IN ({placeholders})",
                tuple(all_urls),
            )
            deleted = cursor.rowcount
        else:
            deleted = 0

        conn.commit()
        logger.info(
            "Links sync: inserted=%d, updated=%d, deleted=%d",
            inserted,
            updated,
            deleted,
        )
        return inserted, updated, deleted

    except mysql.connector.Error as e:
        conn.rollback()
        logger.error("Failed to sync links: %s", e)
        return 0, 0, 0

    finally:
        cursor.close()


def sync_links(
    driver: webdriver.Chrome,
    conn: MySQLConnection,
    logger: logging.Logger,
    proxy_server: Optional[str] = None,
) -> bool:
    """Download paid + wait_indexation CSVs and sync to ggl_links table."""
    session = get_selenium_cookies_session(driver, logger, proxy_server)

    all_links: List[Dict[str, Any]] = []

    # Navigate to paid page first (establishes session context),
    # then download CSV with Referer header
    logger.info("Navigating to paid links page")
    driver.get(PAID_LINKS_URL)
    time.sleep(2)

    paid_csv = download_csv_export(
        session,
        CSV_DOWNLOAD_PAID_URL,
        {"url": "true", "date_paid": "true"},
        logger,
        referer=PAID_LINKS_URL,
    )
    if paid_csv:
        all_links.extend(parse_links_csv(paid_csv, "paid", logger))
    else:
        logger.error("Failed to download paid links CSV")
        return False

    # Navigate to wait_indexation page, then download CSV
    logger.info("Navigating to wait_indexation links page")
    driver.get(WAIT_INDEXATION_URL)
    time.sleep(2)

    wait_csv = download_csv_export(
        session,
        CSV_DOWNLOAD_WAIT_URL,
        {"url": "true"},
        logger,
        referer=WAIT_INDEXATION_URL,
    )
    if wait_csv:
        all_links.extend(parse_links_csv(wait_csv, "wait_indexation", logger))
    else:
        logger.error("Failed to download wait_indexation links CSV")
        return False

    if not all_links:
        logger.warning("No links found in CSVs")
        return True

    sync_links_to_db(conn, all_links, logger)
    return True


def check_links(
    conn: MySQLConnection,
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Check HTTP availability of all links in ggl_links table.

    Performs HEAD request for each URL, updates last_check_at/last_check_code,
    and sends Telegram alert for non-200 responses.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT id, url FROM {DB_FULL_LINKS_TABLE}"
            " WHERE date_paid >= '2025-01-01' OR date_paid IS NULL"
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()

    if not rows:
        logger.info("No links to check")
        return True

    logger.info("Checking %d links", len(rows))
    errors: List[Dict[str, Any]] = []

    update_cursor = conn.cursor()
    try:
        for row in rows:
            url = row["url"]
            try:
                resp = requests.head(url, timeout=LINK_CHECK_TIMEOUT, allow_redirects=True)
                code = resp.status_code
            except requests.RequestException:
                code = 0

            update_cursor.execute(
                f"""UPDATE {DB_FULL_LINKS_TABLE}
                    SET last_check_at = NOW(), last_check_code = %s
                    WHERE id = %s
                """,
                (code, row["id"]),
            )

            if code != 200:
                errors.append({"url": url, "code": code})
                logger.warning("Link check failed: %s → %d", url, code)

        conn.commit()
    except mysql.connector.Error as e:
        conn.rollback()
        logger.error("Failed to update link check results: %s", e)
        return False
    finally:
        update_cursor.close()

    logger.info(
        "Link check complete: %d total, %d errors", len(rows), len(errors)
    )

    if errors:
        send_links_check_notification(errors, config, logger)

    return True


def format_links_check_message(errors: List[Dict[str, Any]]) -> str:
    """Format link check errors as Telegram message."""
    lines = [f"<b>Проблемы с доступом оплаченных ссылок ({len(errors)})</b>"]

    for err in errors:
        url = html.escape(err["url"])
        code = err["code"]
        lines.append(f"{url} {code}")

    message = "\n".join(lines)

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - 30]
        message += "\n<i>...обрезано</i>"

    return message


def send_links_check_notification(
    errors: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Send Telegram notification about link check errors."""
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled")
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured")
        return False

    if not errors:
        return False

    message = format_links_check_message(errors)
    url = TELEGRAM_API_URL.format(bot_token)

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get("ok"):
            logger.info(
                "Telegram link-check notification sent: %d errors", len(errors)
            )
            return True

        logger.error("Telegram API error: %s", result.get("description"))
        return False
    except requests.RequestException as e:
        logger.error("Failed to send link-check notification: %s", e)
        return False


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
# TELEGRAM NOTIFICATIONS
# =============================================================================

TELEGRAM_API_URL = "https://api.telegram.org/bot{}/sendMessage"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def format_telegram_message(
    tasks: List[Dict[str, Any]], mention: str = ""
) -> str:
    """Format list of new tasks as Telegram HTML message.

    Args:
        tasks: List of new task dictionaries
        mention: Telegram usernames to mention (e.g. "@user1 @user2")

    Returns:
        HTML-formatted message string
    """
    lines = [f"<b>Новые задачи GoGetLinks ({len(tasks)})</b>"]

    for task in tasks:
        price = task.get("price")
        price_str = f"{price:.0f} ₽" if price and price > 0 else "бесплатно"
        title = html.escape(task.get("title", "—"))
        domain = html.escape(task.get("domain", "—"))
        customer = html.escape(task.get("customer", "—"))

        task_line = f"• {title} | {price_str} | {domain} → {customer}"
        lines.append(task_line)

    lines.append("")
    lines.append('<a href="https://gogetlinks.net/webTask">Открыть задачи</a>')

    if mention:
        lines.append(mention)

    message = "\n".join(lines)

    # Truncate if too long
    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        footer = '\n\n<a href="https://gogetlinks.net/webTask">Открыть задачи</a>'
        if mention:
            footer += f"\n{mention}"
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - len(footer) - 20]
        message += "\n<i>...обрезано</i>" + footer

    return message


def format_status_changes_message(changes: List[Dict[str, str]]) -> str:
    """Format status change list as Telegram HTML message."""
    lines = [f"<b>Изменения статусов GoGetLinks ({len(changes)})</b>"]

    for change in changes:
        site = html.escape(change.get("site", "—"))
        old_status = html.escape(change.get("old_status", "—"))
        new_status = html.escape(change.get("new_status", "—"))
        lines.append(f"• {site}: {old_status} → <b>{new_status}</b>")

    lines.append("")
    lines.append('<a href="https://gogetlinks.net/mySites">Открыть Мои сайты</a>')

    message = "\n".join(lines)

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        footer = '\n\n<a href="https://gogetlinks.net/mySites">Открыть Мои сайты</a>'
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - len(footer) - 20]
        message += "\n<i>...обрезано</i>" + footer

    return message


def send_telegram_notification(
    tasks: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Send Telegram notification about new tasks.

    Args:
        tasks: List of new task dictionaries
        config: Telegram configuration (bot_token, chat_id)
        logger: Logger instance

    Returns:
        True if message sent successfully, False otherwise
    """
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled")
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured")
        return False

    if len(tasks) == 0:
        logger.debug("No new tasks to notify about")
        return False

    mention = telegram_config.get("mention", "")
    message = format_telegram_message(tasks, mention)
    url = TELEGRAM_API_URL.format(bot_token)

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        if result.get("ok"):
            logger.info(f"Telegram notification sent: {len(tasks)} new tasks")
            return True
        else:
            logger.error(f"Telegram API error: {result.get('description')}")
            return False

    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False


def send_status_changes_notification(
    changes: List[Dict[str, str]],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Send Telegram notification about changed ggl_status values."""
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled")
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured")
        return False

    if len(changes) == 0:
        logger.debug("No status changes to notify about")
        return False

    message = format_status_changes_message(changes)
    url = TELEGRAM_API_URL.format(bot_token)

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get("ok"):
            logger.info(
                "Telegram status-change notification sent: "
                f"{len(changes)} site(s)"
            )
            return True

        logger.error(f"Telegram API error: {result.get('description')}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to send status-change notification: {e}")
        return False


def format_no_new_tasks_message(days: int, mention: str = "") -> str:
    """Format alert about no new tasks for a long time.

    Args:
        days: Number of days since last new task
        mention: Telegram usernames to mention

    Returns:
        HTML-formatted message string
    """
    lines = [
        f"<b>Нет новых задач уже {days} дней</b>",
        "",
        "Последняя новая задача на GoGetLinks появилась "
        f"{days} дней назад. Возможно, стоит проверить вручную.",
        "",
        '<a href="https://gogetlinks.net/webTask">Открыть задачи</a>',
    ]

    if mention:
        lines.append(mention)

    return "\n".join(lines)


def send_no_new_tasks_notification(
    days: int,
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Send Telegram alert when no new tasks for too long.

    Args:
        days: Number of days since last new task
        config: Application configuration
        logger: Logger instance

    Returns:
        True if message sent successfully, False otherwise
    """
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled")
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured")
        return False

    mention = telegram_config.get("mention", "")
    message = format_no_new_tasks_message(days, mention)
    url = TELEGRAM_API_URL.format(bot_token)

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get("ok"):
            logger.info(
                f"Telegram no-new-tasks alert sent ({days} days)"
            )
            return True

        logger.error(f"Telegram API error: {result.get('description')}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to send no-new-tasks notification: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================


def parse_cli_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Gogetlinks Task Parser")
    parser.add_argument(
        "--skip-tasks",
        action="store_true",
        help="Skip parsing tasks and notifications from /webTask",
    )
    parser.add_argument(
        "--skip-sites",
        action="store_true",
        help="Skip parsing /mySites and updating ddl.domain metrics",
    )
    parser.add_argument(
        "--sync-links",
        action="store_true",
        help="Sync paid/wait_indexation links from CSV export to ggl_links table",
    )
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="Check HTTP availability of all links in ggl_links table",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point.

    Returns:
        Exit code (0-99)
    """
    logger = None
    conn = None
    driver = None
    sites_lock_acquired = False

    try:
        args = parse_cli_args(argv)

        needs_tasks = not args.skip_tasks
        needs_sites = not args.skip_sites
        needs_sync_links = args.sync_links
        needs_check_links = args.check_links
        needs_selenium = needs_tasks or needs_sites or needs_sync_links

        if not needs_tasks and not needs_sites and not needs_sync_links and not needs_check_links:
            logger = setup_logger()
            logger.warning("Nothing to do (all stages skipped)")
            return EXIT_SUCCESS

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

        # Acquire mySites lock only for runs that include /mySites stage.
        if needs_sites:
            sites_lock_acquired, lock_reason = acquire_sites_lock(logger)
            if not sites_lock_acquired:
                logger.warning(
                    "Skipping run because mySites lock is active: "
                    f"{lock_reason}"
                )
                return EXIT_SUCCESS

        # 3. Connect to database
        try:
            conn = connect_to_database(config, logger)
        except mysql.connector.Error as e:
            logger.error(f"Database error: {e}")
            return EXIT_DATABASE_ERROR

        # --check-links: no Selenium needed, just DB + HTTP
        if needs_check_links:
            logger.info("Checking link availability (--check-links)")
            check_links(conn, config, logger)

        if not needs_selenium:
            logger.info("Parsing completed successfully")
            return EXIT_SUCCESS

        # 4-5. Initialize browser and authenticate.
        # Skip direct connection attempt — go straight to proxy if configured.
        auth_ok = False
        proxy_attempts: List[Optional[str]] = []
        if DEFAULT_FALLBACK_PROXY:
            proxy_attempts.append(DEFAULT_FALLBACK_PROXY)
        if not proxy_attempts:
            proxy_attempts.append(None)  # fallback: direct only if no proxy set

        for proxy in proxy_attempts:
            if proxy:
                logger.info(f"Connecting via proxy {proxy}")

            # Recreate browser for each auth attempt to avoid stale state.
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None

            try:
                driver = initialize_driver(logger, proxy_server=proxy)
            except WebDriverException as e:
                logger.error(f"WebDriver error: {e}")
                return EXIT_WEBDRIVER_ERROR

            if not load_cookies(driver, logger):
                max_auth_retries = 2
                auth_success = False
                for auth_try in range(1, max_auth_retries + 1):
                    auth_success = authenticate(
                        driver=driver,
                        credentials=config["gogetlinks"],
                        anticaptcha_config=config["anticaptcha"],
                        logger=logger,
                    )
                    if auth_success:
                        break

                    if auth_try < max_auth_retries:
                        logger.warning(
                            f"Auth attempt {auth_try}/{max_auth_retries} failed, "
                            "retrying with fresh browser..."
                        )
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = initialize_driver(logger, proxy_server=proxy)
                        continue

                if not auth_success:
                    logger.error("Authentication failed")
                    return EXIT_AUTH_FAILED

                save_cookies(driver, logger)

            if is_anti_bot_blocked(driver):
                logger.error("Access blocked by anti-bot page")
                return EXIT_AUTH_FAILED

            auth_ok = True
            break

        if not auth_ok:
            logger.error("Authentication failed")
            return EXIT_AUTH_FAILED

        # Sync paid links (--sync-links)
        if needs_sync_links:
            logger.info("Syncing paid links (--sync-links)")
            sync_links(driver, conn, logger, proxy_server=proxy)

        if not needs_tasks:
            logger.info("Skipping task parsing (--skip-tasks)")
        else:
            # 6. Parse task list
            tasks = parse_task_list(driver, logger, conn)

            if not tasks:
                logger.warning("No tasks parsed")
            else:
                # 7. Save tasks to database
                logger.info(f"Saving {len(tasks)} tasks to database")
                success_count = 0
                new_tasks = []
                for task in tasks:
                    result = insert_or_update_task(conn, task, logger)
                    if result is not None:
                        success_count += 1
                        if result is True:
                            new_tasks.append(task)

                logger.info(
                    f"Successfully saved {success_count}/{len(tasks)} tasks "
                    f"({len(new_tasks)} new)"
                )

                # 8. Send Telegram notification for new tasks
                if len(new_tasks) > 0:
                    send_telegram_notification(new_tasks, config, logger)

                # 9. Print output (if enabled)
                print_tasks(tasks, config["output"]["print_to_console"])

        # 10. Parse and save mySites metrics
        if not needs_sites:
            logger.info("Skipping mySites parsing (--skip-sites)")
        else:
            sites = parse_my_sites(driver, logger)
            updated_sites, status_changes = save_sites_to_db(conn, sites, logger)
            if len(status_changes) > 0:
                send_status_changes_notification(status_changes, config, logger)
            logger.info(
                "mySites summary: "
                f"parsed={len(sites)}, updated={updated_sites}, "
                f"status_changed={len(status_changes)}"
            )

            # 11. Check if no new tasks for too long
            days = get_days_since_last_new_task(conn, logger)
            if days is not None and days >= NO_NEW_TASKS_THRESHOLD_DAYS:
                logger.warning(f"No new tasks for {days} days")
                send_no_new_tasks_notification(days, config, logger)
            elif days is not None:
                logger.debug(f"Last new task was {days} day(s) ago")

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

        if logger and sites_lock_acquired:
            release_sites_lock(logger)


if __name__ == "__main__":
    sys.exit(main())
