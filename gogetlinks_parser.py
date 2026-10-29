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
    6  - Not found (--cancel-order: no such order or already cancelled)
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

from ggl_top import GGL_TOP_DOMAINS

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
# Карточка сайта («Настроить» в первом столбце /mySites): форма с ценами.
EDIT_SITE_PATH = "/editSiteInfo/index/site_id/{}"
EDIT_SITE_URL = HOME_URL + EDIT_SITE_PATH

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
DB_ORDERS_TABLE = "ggl_article_order"
DB_FULL_ORDERS_TABLE = f"{DB_SCHEMA}.{DB_ORDERS_TABLE}"
DB_PRICE_EXPERIMENT_TABLE = "ggl_price_experiment"
DB_FULL_PRICE_EXPERIMENT_TABLE = f"{DB_SCHEMA}.{DB_PRICE_EXPERIMENT_TABLE}"
DB_SITE_PRICES_TABLE = "ggl_site_prices"
DB_FULL_SITE_PRICES_TABLE = f"{DB_SCHEMA}.{DB_SITE_PRICES_TABLE}"

# Timeouts
CAPTCHA_TIMEOUT = 120
CAPTCHA_POLL_INTERVAL = 5
MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 10
IMPLICIT_WAIT = 5
PAGE_NAVIGATION_TIMEOUT = 45
NAVIGATION_RETRY_ATTEMPTS = 3
NAVIGATION_RETRY_DELAY = 5
LINK_CHECK_TIMEOUT = 10

# Exit codes
EXIT_SUCCESS = 0
EXIT_NOT_FOUND = 6
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

# Article orders (ddl.ggl_article_order): "Статья", "Заметка" and "Контекстная
# ссылка" tasks are taken (для нас все три — обычная статья).
ORDER_TASK_TITLES = ("Статья", "Заметка", "Контекстная ссылка")
# Задание, по которому готовый текст уже дал рекламодатель: в строке списка
# стоит иконка-подсказка, своего текста такому заданию не нужно.
ADVERTISER_TEXT_MARKER = "предоставлен рекламодателем"
# Та же иконка — ссылка на готовый текст: `/copyright/getResultText/taskId/<id>`.
ADVERTISER_TEXT_LINK = "/copyright/getresulttext/"
# Задание, возвращённое оптимизатором на доработку: в ячейке «Времени прошло»
# стоит иконка-подсказка `data-tooltip-head="Задание на доработку"`.
# Правки выполняются вручную, статью по такому заданию не заказываем.
REWORK_MARKER = "на доработку"
ORDER_MARKER_ANCHOR = "[Анкор]"
ORDER_STUCK_ATTEMPTS = 3
# How long an order must sit untouched before "заказ не выходит" is sent.
ORDER_STUCK_IDLE_MINUTES = 30
ORDER_STUCK_STATE_FILE = os.getenv(
    "GGL_ORDER_STUCK_STATE_FILE", "logs/order_stuck_notified.json"
).strip()

# Metric change alerts (/mySites): minimal delta worth a Telegram message.
# Values can be overridden via [metrics] section in config.ini.
METRIC_DEFAULT_THRESHOLDS = {
    "sqi": 10,
    "cf_tf": 2,
    "pr_cy": 1,
    "trust": 1,
    "indexation": 5,
}

# Traffic is noisy, so it is compared in percent, not in absolute units.
METRIC_TRAFFIC_DEFAULT_PERCENT = 30

# Human-readable labels for metric change messages.
METRIC_LABELS = {
    "sqi": "ИКС",
    "cf_tf": "TF/CF",
    "pr_cy": "PR-CY",
    "trust": "Траст",
    "indexation": "Индексация",
    "traffic": "Трафик",
    "referencing": "Ссылочность",
}

# Order of metrics inside one site block.
METRIC_ORDER = [
    "cf_tf",
    "sqi",
    "pr_cy",
    "trust",
    "indexation",
    "referencing",
    "traffic",
]

# Known values of the "Ссылочность" column.
REFERENCING_LABELS = ("Низкая", "Оптимальная", "Повышенная", "Высокая")

# Эксперимент с ценами: домены с трастом 9. Свои сайты (target = 'site') —
# контроль, цены не трогаем, только проверяем, что не ниже 900. Остальные
# делим на группы с одной ценой на статью, заметку и контекстную ссылку.
PRICE_EXPERIMENT_TRUST = 9
PRICE_CONTROL_TARGET = "site"
PRICE_CONTROL_GROUP = "control"
PRICE_CONTROL_MIN = Decimal("900")
PRICE_EXPERIMENT_GROUPS = (500, 450, 400)
# Группы выравниваем по продажам за этот период до эксперимента.
PRICE_BALANCE_DAYS = 90
# Поля карточки сайта: суффикс id (#price_<key>, #not_price_<key>) → тип.
PRICE_FIELDS = {"paper": "Статья", "post": "Заметка", "link": "Контекстная ссылка"}
SELECTOR_SITE_CARD_SUBMIT = ".js-siteCard__submit"
SELECTOR_SITE_CARD_ERROR = ".js-siteCard__error"
SITE_CARD_SAVE_TIMEOUT = 20
# Затраты на текст по заданию с заказом статьи (ORDER_TASK_TITLES).
ARTICLE_COST = Decimal("120")

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
            "proxy": parser.get("telegram", "proxy", fallback="").strip(),
        },
        "metrics": {
            # Off unless explicitly enabled: the first run after the DB
            # migration fills the new columns and would report them as changes.
            "enabled": parser.getboolean("metrics", "enabled", fallback=False),
            "thresholds": {
                key: parser.getint("metrics", key, fallback=default)
                for key, default in METRIC_DEFAULT_THRESHOLDS.items()
            },
            "traffic_percent": parser.getint(
                "metrics", "traffic_percent", fallback=METRIC_TRAFFIC_DEFAULT_PERCENT
            ),
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
                -- Detail fields are only fetched for tasks that lack them
                -- (see task_has_details), so on a run that skipped the modal
                -- they arrive as NULL. Keep the stored value in that case.
                description = COALESCE(VALUES(description), description),
                url = COALESCE(VALUES(url), url),
                requirements = COALESCE(VALUES(requirements), requirements),
                contacts = COALESCE(VALUES(contacts), contacts),
                deadline = COALESCE(VALUES(deadline), deadline),
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
    # Ждать DOMContentLoaded, а не полной загрузки всех подресурсов: один
    # зависший сторонний ресурс иначе держит driver.get() до таймаута и
    # отнимает слот крона. Нужные элементы всё равно ждём через
    # WebDriverWait.
    options.page_load_strategy = "eager"
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
        driver.set_page_load_timeout(PAGE_NAVIGATION_TIMEOUT)
        logger.info("WebDriver initialized successfully")
        return driver

    except WebDriverException as e:
        logger.error(f"Failed to initialize WebDriver: {e}")
        raise


def navigate_with_retry(
    driver: webdriver.Chrome,
    url: str,
    logger: logging.Logger,
    attempts: int = NAVIGATION_RETRY_ATTEMPTS,
) -> bool:
    """Open URL, retrying on hung page loads.

    Without a page load timeout Chrome can hang until Selenium's own 120s
    HTTP timeout fires and kills the whole run. A bounded timeout plus a
    few retries keeps a single stalled request from costing a cron slot.

    Args:
        driver: Chrome WebDriver
        url: Target URL
        logger: Logger instance
        attempts: How many times to try before giving up

    Returns:
        True if the page was opened, False if every attempt failed
    """
    for attempt in range(1, attempts + 1):
        try:
            driver.get(url)
            return True

        except (TimeoutException, WebDriverException) as e:
            logger.warning(
                f"Navigation to {url} failed "
                f"(attempt {attempt}/{attempts}): {type(e).__name__}"
            )
            if attempt < attempts:
                time.sleep(NAVIGATION_RETRY_DELAY)

    logger.error(f"Navigation to {url} failed after {attempts} attempts")
    return False


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
        if not navigate_with_retry(driver, HOME_URL, logger):
            logger.error("Failed to open home page")
            return False

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


def has_advertiser_text(row: WebElement, logger: logging.Logger) -> bool:
    """Check if the task comes with a ready text from the advertiser.

    The marker exists only on the list page: an icon in the actions cell that
    links to the prepared text and carries the tooltip "Текст предоставлен
    рекламодателем". Both the link and the tooltip are matched (the CSS class
    `icon-page icon_blue` is not — the site renames classes more often).

    Args:
        row: Task row element
        logger: Logger instance

    Returns:
        True if the advertiser-text icon is present.
    """
    try:
        candidates = row.find_elements(
            By.CSS_SELECTOR,
            f"a[href*='{ADVERTISER_TEXT_LINK}' i], "
            "[data-tooltip-head], [data-tooltip-body]",
        )
    except Exception as e:
        logger.debug(f"Failed to read advertiser-text markers: {e}")
        return False

    for el in candidates:
        href = (el.get_attribute("href") or "").lower()
        if ADVERTISER_TEXT_LINK in href:
            return True

        parts = (
            el.get_attribute("data-tooltip-head") or "",
            el.get_attribute("data-tooltip-body") or "",
        )
        if ADVERTISER_TEXT_MARKER in " ".join(parts).lower():
            return True

    return False


def has_rework_marker(row: WebElement, logger: logging.Logger) -> bool:
    """Check if the task was sent back by the optimizer for rework.

    The marker exists only on the list page: a red clock icon in the
    "Времени прошло" cell with the tooltip "Задание на доработку". Only the
    tooltip text is matched (the CSS class `icon_red tooltipster` is not — the
    site renames classes more often).

    Args:
        row: Task row element
        logger: Logger instance

    Returns:
        True if the rework tooltip is present.
    """
    try:
        candidates = row.find_elements(
            By.CSS_SELECTOR, "[data-tooltip-head], [data-tooltip-body]"
        )
    except Exception as e:
        logger.debug(f"Failed to read rework markers: {e}")
        return False

    for el in candidates:
        parts = (
            el.get_attribute("data-tooltip-head") or "",
            el.get_attribute("data-tooltip-body") or "",
        )
        if REWORK_MARKER in " ".join(parts).lower():
            return True

    return False


def parse_task_row(row: WebElement, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """Extract all fields from task row.

    Fields: task_id, title, domain, customer, customer_url,
            external_links, time_passed, price, advertiser_text, rework

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

        # Готовый текст от рекламодателя — иконка в ячейке действий
        advertiser_text = has_advertiser_text(row, logger)

        # Возврат оптимизатором на доработку — иконка в ячейке «Времени прошло»
        rework = has_rework_marker(row, logger)

        task = {
            "task_id": task_id,
            "domain": domain,
            "customer": customer,
            "customer_url": customer_url,
            "external_links": external_links,
            "title": title,
            "time_passed": time_passed,
            "price": price,
            "advertiser_text": advertiser_text,
            "rework": rework,
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
        if not navigate_with_retry(driver, TASK_LIST_URL, logger):
            logger.error("Failed to open task list page")
            return []

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

    # site_id нужен для карточки сайта, он есть только в ссылке «Настроить».
    site_id = None
    try:
        settings_link = cells[0].find_element(
            By.CSS_SELECTOR, "a[href*='/editSiteInfo/index/site_id/']"
        )
        match = re.search(r"/site_id/(\d+)", settings_link.get_attribute("href") or "")
        if match:
            site_id = int(match.group(1))
    except NoSuchElementException:
        pass

    status = sanitize_text(cells[1].text)
    sqi = extract_digits_only(sanitize_text(cells[2].text))
    cf_tf = extract_digits_only(sanitize_text(cells[3].text))
    pr_cy = extract_digits_only(sanitize_text(cells[4].text))
    traffic = extract_digits_only(sanitize_text(cells[5].text))
    # "Индексация" holds a percent or "N/A" when GGL has no data yet.
    indexation = extract_digits_only(sanitize_text(cells[6].text))
    referencing = extract_referencing_label(sanitize_text(cells[7].text))
    trust = extract_digits_only(sanitize_text(cells[9].text))

    # Reject reason parsing is intentionally disabled: keep status only.
    description = None

    return {
        "site": site.lower(),
        "site_id": site_id,
        "status": status,
        "sqi": sqi,
        "cf_tf": cf_tf,
        "pr_cy": pr_cy,
        "traffic": traffic,
        "indexation": indexation,
        "referencing": referencing,
        "trust": trust,
        "description": description,
    }


def extract_referencing_label(text: str) -> Optional[str]:
    """Return one of REFERENCING_LABELS found in the "Ссылочность" cell."""
    if not text:
        return None

    for label in REFERENCING_LABELS:
        if label.lower() in text.lower():
            return label

    return None


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


# Columns fetched before UPDATE to detect what actually changed.
SITE_METRIC_COLUMNS = [
    ("sqi", "ggl_sqi"),
    ("cf_tf", "ggl_cf_tf"),
    ("pr_cy", "ggl_pr_cy"),
    ("trust", "ggl_trust"),
    ("traffic", "ggl_traffic"),
    ("indexation", "ggl_indexation"),
    ("referencing", "ggl_referencing"),
]


def format_metric_value(value: Any) -> str:
    """Render a metric value for a Telegram message."""
    if value is None or value == "":
        return "—"
    return str(value)


def is_metric_change_significant(
    metric: str,
    old_value: Any,
    new_value: Any,
    thresholds: Dict[str, int],
    traffic_percent: int,
) -> bool:
    """Decide whether the delta of one metric is worth notifying about.

    A missing new value is treated as a parsing artifact, not as a change:
    GoGetLinks renders "N/A" and empty cells while data is being recalculated,
    and reporting those would flood the chat on every partial page load.
    """
    if new_value is None or new_value == "":
        return False

    if metric == "referencing":
        return format_metric_value(old_value) != format_metric_value(new_value)

    try:
        new_number = int(new_value)
    except (TypeError, ValueError):
        return False

    if old_value is None or old_value == "":
        # Metric appeared for the first time.
        return True

    try:
        old_number = int(old_value)
    except (TypeError, ValueError):
        return True

    delta = abs(new_number - old_number)
    if delta == 0:
        return False

    if metric == "cf_tf":
        # Always report reaching the goal, including gradual one-point growth.
        if old_number < 30 <= new_number:
            return True
        # Existing config.ini files may still contain the former threshold of 1.
        return delta >= max(2, thresholds.get(metric, 2))

    if metric == "traffic":
        if old_number == 0:
            return new_number > 0
        return (delta * 100 / old_number) >= traffic_percent

    return delta >= thresholds.get(metric, 1)


def get_metric_direction(
    metric: str, old_value: Any, new_value: Any
) -> Optional[str]:
    """Return "up"/"down" for a numeric metric improvement/decline, else None.

    "Referencing" is an ordinal label (Низкая/Оптимальная/...), not a scale
    where higher is better, so it is never marked. A missing old value means
    the metric just appeared and has no baseline to compare against.
    """
    if metric == "referencing":
        return None
    if old_value is None or old_value == "":
        return None
    try:
        old_number = int(old_value)
        new_number = int(new_value)
    except (TypeError, ValueError):
        return None
    if new_number > old_number:
        return "up"
    if new_number < old_number:
        return "down"
    return None


def detect_metric_changes(
    host: str,
    old_values: Dict[str, Any],
    site: Dict[str, Any],
    thresholds: Dict[str, int],
    traffic_percent: int,
) -> Optional[Dict[str, Any]]:
    """Build a per-site list of significant metric changes."""
    changes = []
    for metric in METRIC_ORDER:
        old_value = old_values.get(metric)
        new_value = site.get(metric)
        if is_metric_change_significant(
            metric, old_value, new_value, thresholds, traffic_percent
        ):
            changes.append(
                {
                    "metric": metric,
                    "label": METRIC_LABELS.get(metric, metric),
                    "old": format_metric_value(old_value),
                    "new": format_metric_value(new_value),
                    "direction": get_metric_direction(metric, old_value, new_value),
                }
            )

    if len(changes) == 0:
        return None

    return {"site": host, "changes": changes}


def save_sites_to_db(
    conn: MySQLConnection,
    sites: List[Dict[str, Any]],
    logger: logging.Logger,
    metrics_config: Optional[Dict[str, Any]] = None,
) -> tuple[int, List[Dict[str, str]], List[Dict[str, Any]]]:
    """Update ddl.domain rows by host with metrics parsed from /mySites."""
    if len(sites) == 0:
        logger.info("No mySites data to save")
        return 0, [], []

    metrics_config = metrics_config or {}
    thresholds = metrics_config.get("thresholds") or METRIC_DEFAULT_THRESHOLDS
    traffic_percent = metrics_config.get(
        "traffic_percent", METRIC_TRAFFIC_DEFAULT_PERCENT
    )

    query = """
        UPDATE domain SET
            ggl_status = %s,
            ggl_description = %s,
            ggl_traffic = %s,
            ggl_sqi = %s,
            ggl_cf_tf = %s,
            ggl_trust = %s,
            ggl_pr_cy = %s,
            ggl_indexation = %s,
            ggl_referencing = %s,
            ggl_update_at = NOW()
        WHERE host = %s
    """

    updated_count = 0
    status_changes: List[Dict[str, str]] = []
    metric_changes: List[Dict[str, Any]] = []
    cursor = conn.cursor()

    try:
        hosts = [site.get("site") for site in sites if site.get("site")]
        existing_status_map: Dict[str, Optional[str]] = {}
        existing_metrics_map: Dict[str, Dict[str, Any]] = {}
        if len(hosts) > 0:
            placeholders = ", ".join(["%s"] * len(hosts))
            columns = ", ".join(column for _, column in SITE_METRIC_COLUMNS)
            cursor.execute(
                f"SELECT host, ggl_status, {columns} "
                f"FROM domain WHERE host IN ({placeholders})",
                tuple(hosts),
            )
            for row in cursor.fetchall():
                host = row[0]
                if not host:
                    continue
                host_key = str(host).lower()
                existing_status_map[host_key] = row[1]
                existing_metrics_map[host_key] = {
                    metric: row[index + 2]
                    for index, (metric, _) in enumerate(SITE_METRIC_COLUMNS)
                }

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

            # Metrics of a host unknown to DDL have nothing to compare against.
            if host and host in existing_metrics_map:
                site_changes = detect_metric_changes(
                    host,
                    existing_metrics_map[host],
                    site,
                    thresholds,
                    traffic_percent,
                )
                if site_changes:
                    metric_changes.append(site_changes)

            cursor.execute(
                query,
                (
                    new_status_raw,
                    site.get("description"),
                    site.get("traffic"),
                    site.get("sqi"),
                    site.get("cf_tf"),
                    site.get("trust"),
                    site.get("pr_cy"),
                    site.get("indexation"),
                    site.get("referencing"),
                    host,
                ),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                updated_count += cursor.rowcount

        conn.commit()

        logger.info(
            "mySites DB update completed: "
            f"parsed={len(sites)}, updated={updated_count}, "
            f"status_changed={len(status_changes)}, "
            f"metrics_changed={len(metric_changes)}"
        )
        return updated_count, status_changes, metric_changes

    except mysql.connector.Error as e:
        conn.rollback()
        logger.error(f"Failed to update domain metrics: {e}")
        return 0, [], []

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


WARM_USER_AGENT = "DDL dashboard cron checker"
WARM_COOKIE = {"abukreev": "wpadmin"}
WARM_TIMEOUT = (10, 30)  # (connect, read)


def warm_links(
    conn: MySQLConnection,
    logger: logging.Logger,
) -> bool:
    """Warm links by sending GET request to each URL.

    Warms cache for paid links (date_paid >= 2025-01-01).
    Updates last_check_at and last_check_code in ggl_links.
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
        logger.info("No links to warm")
        return True

    logger.info("Warming %d links", len(rows))
    ok_count = 0
    err_count = 0

    update_cursor = conn.cursor()
    try:
        for i, row in enumerate(rows, 1):
            url = row["url"]
            start = time.time()
            try:
                resp = requests.get(
                    url,
                    timeout=WARM_TIMEOUT,
                    headers={"User-Agent": WARM_USER_AGENT},
                    cookies=WARM_COOKIE,
                    allow_redirects=True,
                )
                code = resp.status_code
                elapsed = time.time() - start
            except requests.RequestException as e:
                code = 0
                elapsed = time.time() - start
                logger.warning("Warm failed: %s → %s (%.1fs)", url, e, elapsed)

            update_cursor.execute(
                f"""UPDATE {DB_FULL_LINKS_TABLE}
                    SET last_check_at = NOW(), last_check_code = %s
                    WHERE id = %s
                """,
                (code, row["id"]),
            )

            if code == 200:
                ok_count += 1
                logger.debug("Warm OK: %s → %d (%.1fs)", url, code, elapsed)
            else:
                err_count += 1
                logger.warning("Warm error: %s → %d (%.1fs)", url, code, elapsed)

            if i % 50 == 0:
                logger.info("Warm progress: %d/%d", i, len(rows))

        conn.commit()
    except mysql.connector.Error as e:
        conn.rollback()
        logger.error("Failed to update warm results: %s", e)
        return False
    finally:
        update_cursor.close()

    logger.info(
        "Warm complete: %d total, %d ok, %d errors", len(rows), ok_count, err_count
    )
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
    proxies = get_telegram_proxies(telegram_config)

    try:
        request_kwargs = {"json": payload, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies

        response = requests.post(url, **request_kwargs)
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
# ARTICLE ORDERS (ddl.ggl_article_order)
# =============================================================================

# Trailing note in square brackets that ends the anchor line, e.g. "[Комментарий]".
ORDER_BRACKET_MARKER_RE = re.compile(r"\[[^\]\n]{1,40}\]")

# Trailing "(...)" note after the anchor: "(в любом падеже )",
# "(склонять анкор нельзя )".
ORDER_ANCHOR_NOTE_RE = re.compile(r"\(([^()]*)\)\s*$")


def parse_anchor(description: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse anchor and inflection flag out of a task description.

    The description starts with the "[Анкор] <anchor> (<note>)" line, followed
    by free-form buyer requirements. The note tells whether the anchor may be
    inflected; a trailing "(...)" that is not such a note stays part of the
    anchor (e.g. "Термокамеры (коптильные) для ... копчения").

    Args:
        description: Full `ggl_tasks.description` text.

    Returns:
        Dict with keys `anchor` (str), `anchor_inflect` (0/1) and `multiple`
        (True when the description contains more than one anchor marker), or
        None when no anchor could be parsed.
    """
    if not description:
        return None

    positions = [
        m.start() for m in re.finditer(re.escape(ORDER_MARKER_ANCHOR), description)
    ]
    if not positions:
        return None

    marker_end = positions[0] + len(ORDER_MARKER_ANCHOR)
    tail = description[marker_end:]

    # The anchor lives on a single line, possibly followed by another marker.
    cut = tail.find("\n")
    if cut == -1:
        cut = len(tail)
    marker = ORDER_BRACKET_MARKER_RE.search(tail[:cut])
    if marker:
        cut = marker.start()

    anchor = tail[:cut].strip()

    anchor_inflect = 0
    note = ORDER_ANCHOR_NOTE_RE.search(anchor)
    if note:
        note_text = note.group(1).strip().lower()
        if "падеж" in note_text:
            anchor_inflect = 1
            anchor = anchor[: note.start()].strip()
        elif "склонять" in note_text and "нельз" in note_text:
            anchor_inflect = 0
            anchor = anchor[: note.start()].strip()

    if not anchor:
        return None

    return {
        "anchor": anchor[:500],
        "anchor_inflect": anchor_inflect,
        "multiple": len(positions) > 1,
    }


def insert_article_order(
    conn: MySQLConnection,
    task: Dict[str, Any],
    parsed_anchor: Dict[str, Any],
    logger: logging.Logger,
) -> Optional[bool]:
    """Hand a new "Статья" task over to DDL via `ggl_article_order`.

    Args:
        conn: MySQL connection
        task: Task dictionary as parsed from gogetlinks
        parsed_anchor: Result of :func:`parse_anchor`
        logger: Logger instance

    Returns:
        True if the order was created, False if it already existed,
        None on database error.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            INSERT IGNORE INTO {DB_FULL_ORDERS_TABLE} (
                task_id, domain, target_url, anchor, anchor_inflect,
                requirements, price, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'new')
            """,
            (
                task["task_id"],
                task.get("domain"),
                task.get("url"),
                parsed_anchor["anchor"],
                parsed_anchor["anchor_inflect"],
                task.get("description"),
                task.get("price"),
            ),
        )
        conn.commit()

        created = cursor.rowcount == 1
        if created:
            logger.info(
                "Article order created: task=%s domain=%s anchor=%r inflect=%s",
                task["task_id"],
                task.get("domain"),
                parsed_anchor["anchor"],
                parsed_anchor["anchor_inflect"],
            )
        else:
            logger.debug("Article order already exists: task=%s", task["task_id"])
        return created

    except mysql.connector.Error as e:
        logger.error(
            "Failed to create article order for task %s: %s", task["task_id"], e
        )
        conn.rollback()
        return None
    finally:
        cursor.close()


def format_order_anchor_failed_message(task: Dict[str, Any]) -> str:
    """Format Telegram message for a "Статья" task with unparsed anchor."""
    task_id = task.get("task_id", "—")
    price = task.get("price")
    price_str = f"{price:.0f} ₽" if price and price > 0 else "бесплатно"

    lines = [
        "<b>Есть заказ, анкор не распознан</b>",
        f"Сайт: {html.escape(str(task.get('domain') or '—'))}",
        f"Цена: {price_str}",
        f'<a href="{TASK_DETAIL_URL.format(task_id)}">Задача {task_id}</a>',
        "",
        "<b>Полный текст задачи:</b>",
        f"<pre>{html.escape(str(task.get('description') or '—'))}</pre>",
    ]
    message = "\n".join(lines)

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - 30] + "\n<i>...обрезано</i>"

    return message


def format_order_multiple_anchors_message(
    task: Dict[str, Any], parsed_anchor: Dict[str, Any]
) -> str:
    """Format Telegram message for a task with several anchors."""
    task_id = task.get("task_id", "—")
    lines = [
        "<b>В заказе несколько анкоров, взят первый</b>",
        f"Сайт: {html.escape(str(task.get('domain') or '—'))}",
        f"Анкор: {html.escape(parsed_anchor['anchor'])}",
        f'<a href="{TASK_DETAIL_URL.format(task_id)}">Задача {task_id}</a>',
        "",
        f"<pre>{html.escape(str(task.get('description') or '—'))}</pre>",
    ]
    message = "\n".join(lines)

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - 30] + "\n<i>...обрезано</i>"

    return message


def format_order_ready_message(order: Dict[str, Any]) -> str:
    """Format "Заказ готов" Telegram message."""
    task_id = order.get("task_id", "—")
    price = order.get("price")
    price_str = f"{price:.0f} ₽" if price and price > 0 else "бесплатно"
    inflect = "можно склонять" if order.get("anchor_inflect") else "склонять нельзя"

    lines = [
        "<b>Заказ готов</b>",
        f"Сайт: {html.escape(str(order.get('domain') or '—'))}",
        f"Цена: {price_str}",
        f"Анкор: {html.escape(str(order.get('anchor') or '—'))} ({inflect})",
        f"Целевой URL: {html.escape(str(order.get('target_url') or '—'))}",
        "",
        f'<a href="{html.escape(str(order.get("article_url") or ""))}">Статья</a>'
        f' | <a href="{TASK_DETAIL_URL.format(task_id)}">Задача {task_id}</a>',
        "",
        "Сдать заказ на gogetlinks вручную.",
    ]
    return "\n".join(lines)


def format_order_cancelled_message(order: Dict[str, Any]) -> str:
    """Format "Заказ снят" Telegram message."""
    task_id = order.get("task_id", "—")
    lines = [
        "<b>Заказ снят</b>",
        f"Сайт: {html.escape(str(order.get('domain') or '—'))}",
        f"Анкор: {html.escape(str(order.get('anchor') or '—'))}",
        f'<a href="{TASK_DETAIL_URL.format(task_id)}">Задача {task_id}</a>',
    ]
    return "\n".join(lines)


def format_order_stuck_message(order: Dict[str, Any]) -> str:
    """Format "заказ не выходит" Telegram message."""
    task_id = order.get("task_id", "—")
    lines = [
        "<b>Заказ не выходит</b>",
        f"Сайт: {html.escape(str(order.get('domain') or '—'))}",
        f"Анкор: {html.escape(str(order.get('anchor') or '—'))}",
        f"Попыток: {order.get('attempts', 0)}",
        f"Ошибка: {html.escape(str(order.get('error') or '—'))}",
        f'<a href="{TASK_DETAIL_URL.format(task_id)}">Задача {task_id}</a>',
    ]
    message = "\n".join(lines)

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - 30] + "\n<i>...обрезано</i>"

    return message


def send_order_telegram_message(
    message: str,
    config: Dict[str, Any],
    logger: logging.Logger,
    context: str = "order",
) -> bool:
    """Send a single pre-formatted HTML message about an article order.

    Args:
        message: Ready HTML message text
        config: Full configuration dictionary
        logger: Logger instance
        context: Short label for log messages

    Returns:
        True if the message was accepted by Telegram, False otherwise.
    """
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled (%s)", context)
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured (%s)", context)
        return False

    mention = telegram_config.get("mention", "")
    if mention:
        message = f"{message}\n{mention}"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    request_kwargs: Dict[str, Any] = {"json": payload, "timeout": 30}
    proxies = get_telegram_proxies(telegram_config)
    if proxies:
        request_kwargs["proxies"] = proxies

    try:
        response = requests.post(TELEGRAM_API_URL.format(bot_token), **request_kwargs)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            logger.info("Telegram message sent (%s)", context)
            return True
        logger.error("Telegram API error (%s): %s", context, result.get("description"))
        return False
    except requests.RequestException as e:
        logger.error("Failed to send Telegram message (%s): %s", context, e)
        return False


def article_order_skip_reason(task: Dict[str, Any]) -> Optional[str]:
    """Tell whether an article order must NOT be created for the task.

    One place for the rule, used both when orders are created and when the
    Telegram notification is built — so the chat never promises a text that
    will not be ordered.

    Args:
        task: Parsed task dictionary

    Returns:
        Short reason (Russian, for logs) or None when the article is ordered.
    """
    if (task.get("title") or "").strip() not in ORDER_TASK_TITLES:
        return "тип задания без заказа статьи"

    # Бесплатные задания (в т.ч. на снятие ссылки) приходят с типом "Статья",
    # но платить за генерацию текста по ним незачем.
    price = task.get("price") or Decimal("0")
    if price <= 0:
        return "бесплатное задание"

    # Доработка: правки по комментарию оптимизатора делаются вручную.
    if task.get("rework"):
        return "задание на доработку"

    if task.get("advertiser_text"):
        return "текст предоставлен рекламодателем"

    return None


def process_new_article_orders(
    conn: MySQLConnection,
    new_tasks: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> int:
    """Create article orders for new "Статья" tasks.

    Args:
        conn: MySQL connection
        new_tasks: Tasks that were inserted on this run
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        Number of created orders.
    """
    created = 0

    for task in new_tasks:
        reason = article_order_skip_reason(task)
        if reason is not None:
            # Чужой тип задания — обычное дело, в лог не пишем.
            if (task.get("title") or "").strip() not in ORDER_TASK_TITLES:
                continue
            logger.info(
                "Task %s: article order skipped (%s)", task["task_id"], reason
            )
            continue

        parsed = parse_anchor(task.get("description"))
        if parsed is None:
            logger.warning(
                "Anchor not parsed for task %s, order not created", task["task_id"]
            )
            send_order_telegram_message(
                format_order_anchor_failed_message(task),
                config,
                logger,
                context="anchor not parsed",
            )
            continue

        result = insert_article_order(conn, task, parsed, logger)
        if result is True:
            created += 1
            if parsed["multiple"]:
                send_order_telegram_message(
                    format_order_multiple_anchors_message(task, parsed),
                    config,
                    logger,
                    context="multiple anchors",
                )

    if created:
        logger.info("Article orders created: %d", created)

    return created


def load_stuck_notified(logger: logging.Logger) -> Dict[str, Any]:
    """Load task ids already reported as stuck.

    The order table belongs to DDL, so the "already reported" flag is kept on
    the parser side in a small JSON file.
    """
    try:
        with open(ORDER_STUCK_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning("Unexpected stuck-state format, ignoring")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        logger.warning("Failed to read stuck-state file: %s", e)
    return {}


def save_stuck_notified(state: Dict[str, Any], logger: logging.Logger) -> None:
    """Persist task ids already reported as stuck."""
    try:
        directory = os.path.dirname(ORDER_STUCK_STATE_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(ORDER_STUCK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("Failed to write stuck-state file: %s", e)


def mark_order_notified(
    conn: MySQLConnection, order_id: int, logger: logging.Logger
) -> bool:
    """Set `notified_at` for an order after a successful Telegram message."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"UPDATE {DB_FULL_ORDERS_TABLE} SET notified_at = NOW() WHERE id = %s",
            (order_id,),
        )
        conn.commit()
        return True
    except mysql.connector.Error as e:
        logger.error("Failed to mark order %s as notified: %s", order_id, e)
        conn.rollback()
        return False
    finally:
        cursor.close()


def fetch_orders(
    conn: MySQLConnection, where: str, params: Tuple[Any, ...], logger: logging.Logger
) -> List[Dict[str, Any]]:
    """Select orders matching a WHERE clause."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT id, task_id, domain, target_url, anchor, anchor_inflect,
                   price, status, article_url, error, attempts
            FROM {DB_FULL_ORDERS_TABLE}
            WHERE {where}
            ORDER BY id
            """,
            params,
        )
        # Dictionary cursors are untyped in the connector stubs.
        rows: Any = cursor.fetchall()
        return list(rows)
    except mysql.connector.Error as e:
        logger.error("Failed to select article orders: %s", e)
        return []
    finally:
        cursor.close()


def process_orders(
    conn: MySQLConnection,
    config: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, int]:
    """Report finished, cancelled and stuck article orders to Telegram.

    Light mode without Selenium, meant to run by cron every 10-15 minutes.

    Args:
        conn: MySQL connection
        config: Full configuration dictionary
        logger: Logger instance

    Returns:
        Counters: how many messages of each kind were sent.
    """
    counters = {"ready": 0, "cancelled": 0, "stuck": 0}

    ready = fetch_orders(
        conn, "status = 'published' AND notified_at IS NULL", (), logger
    )
    for order in ready:
        if send_order_telegram_message(
            format_order_ready_message(order), config, logger, context="order ready"
        ):
            mark_order_notified(conn, order["id"], logger)
            counters["ready"] += 1

    cancelled = fetch_orders(
        conn, "status = 'cancelled' AND notified_at IS NULL", (), logger
    )
    for order in cancelled:
        if send_order_telegram_message(
            format_order_cancelled_message(order),
            config,
            logger,
            context="order cancelled",
        ):
            mark_order_notified(conn, order["id"], logger)
            counters["cancelled"] += 1

    # DDL spends up to three attempts on ordinary text rewrites (link count,
    # link placement), so `attempts` alone does not mean the order is stuck.
    # Report only orders that have also stopped moving.
    stuck = fetch_orders(
        conn,
        "status = 'working' AND attempts >= %s"
        " AND updated_at < NOW() - INTERVAL %s MINUTE",
        (ORDER_STUCK_ATTEMPTS, ORDER_STUCK_IDLE_MINUTES),
        logger,
    )
    if stuck:
        notified = load_stuck_notified(logger)
        changed = False
        for order in stuck:
            key = str(order["task_id"])
            if key in notified:
                continue
            if send_order_telegram_message(
                format_order_stuck_message(order),
                config,
                logger,
                context="order stuck",
            ):
                notified[key] = order.get("attempts", 0)
                changed = True
                counters["stuck"] += 1
        if changed:
            save_stuck_notified(notified, logger)

    logger.info(
        "Orders processed: ready=%d, cancelled=%d, stuck=%d",
        counters["ready"],
        counters["cancelled"],
        counters["stuck"],
    )
    return counters


def cancel_order(
    conn: MySQLConnection, task_id: int, logger: logging.Logger
) -> Optional[bool]:
    """Request cancellation of an article order.

    Args:
        conn: MySQL connection
        task_id: gogetlinks task id
        logger: Logger instance

    Returns:
        True if `status` was set to 'cancel', False if there is no such order
        or it is already cancelled, None on database error.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT id, status FROM {DB_FULL_ORDERS_TABLE} WHERE task_id = %s",
            (task_id,),
        )
        order: Any = cursor.fetchone()
    except mysql.connector.Error as e:
        logger.error("Failed to look up order %s: %s", task_id, e)
        return None
    finally:
        cursor.close()

    if order is None:
        logger.warning("No article order for task %s", task_id)
        return False

    if order["status"] in ("cancel", "cancelled"):
        logger.info(
            "Article order %s is already %s, nothing to do", task_id, order["status"]
        )
        return False

    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""UPDATE {DB_FULL_ORDERS_TABLE}
                SET status = 'cancel', notified_at = NULL
                WHERE id = %s AND status <> 'cancelled'
            """,
            (order["id"],),
        )
        conn.commit()
        if cursor.rowcount == 1:
            logger.info("Article order %s set to cancel", task_id)
            return True
        logger.warning("Article order %s was not updated", task_id)
        return False
    except mysql.connector.Error as e:
        logger.error("Failed to cancel order %s: %s", task_id, e)
        conn.rollback()
        return None
    finally:
        cursor.close()


# =============================================================================
# PRICE EXPERIMENT
# =============================================================================


def split_price_groups(domains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split experiment domains into the control and price groups.

    Domains with target 'site' form the control group. The rest are sorted
    by past sales and dealt "snake" style (A B C C B A ...), so every price
    group gets a comparable share of strong and weak domains.

    Args:
        domains: Dicts with host, target, sales, revenue, traffic

    Returns:
        The same dicts extended with `group` and `target_price`
    """
    assignment = [
        {**domain, "group": PRICE_CONTROL_GROUP, "target_price": None}
        for domain in domains
        if domain["target"] == PRICE_CONTROL_TARGET
    ]
    rest = sorted(
        (domain for domain in domains if domain["target"] != PRICE_CONTROL_TARGET),
        key=lambda d: (-d["sales"], -d["revenue"], -d["traffic"], d["host"]),
    )

    group_count = len(PRICE_EXPERIMENT_GROUPS)
    for index, domain in enumerate(rest):
        lap, position = divmod(index, group_count)
        slot = position if lap % 2 == 0 else group_count - 1 - position
        price = PRICE_EXPERIMENT_GROUPS[slot]
        assignment.append({**domain, "group": str(price), "target_price": price})

    return assignment


def assign_price_groups(
    conn: MySQLConnection, logger: logging.Logger
) -> Optional[List[Dict[str, Any]]]:
    """Pick trust-9 domains and store their experiment groups.

    Runs once: if the experiment table already has rows, nothing changes.

    Returns:
        Stored assignment, empty list if groups already exist, None on DB error
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {DB_FULL_PRICE_EXPERIMENT_TABLE}")
        existing: Any = cursor.fetchone()
        if existing["cnt"] > 0:
            logger.warning(
                "Price groups already assigned (%s domains), nothing to do",
                existing["cnt"],
            )
            return []

        cursor.execute(
            f"""SELECT d.host, d.target,
                       COALESCE(d.ggl_traffic, 0) AS traffic,
                       COUNT(t.id) AS sales,
                       COALESCE(SUM(t.price), 0) AS revenue
                FROM {DB_SCHEMA}.domain d
                LEFT JOIN {DB_FULL_TABLE} t
                    ON t.domain = d.host
                    AND t.price > 0
                    AND t.created_at >= NOW() - INTERVAL %s DAY
                WHERE d.ggl_trust = %s
                    AND d.deleted_at IS NULL
                    AND COALESCE(d.is_sold, 0) = 0
                GROUP BY d.host, d.target, d.ggl_traffic
            """,
            (PRICE_BALANCE_DAYS, PRICE_EXPERIMENT_TRUST),
        )
        domains: List[Any] = cursor.fetchall()
        if not domains:
            logger.warning("No domains with trust %s", PRICE_EXPERIMENT_TRUST)
            return []

        assignment = split_price_groups(domains)
        for row in assignment:
            cursor.execute(
                f"""INSERT INTO {DB_FULL_PRICE_EXPERIMENT_TABLE}
                    (host, grp, target_price, sales_before, revenue_before,
                     traffic, assigned_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    row["host"],
                    row["group"],
                    row["target_price"],
                    row["sales"],
                    row["revenue"],
                    row["traffic"],
                ),
            )
        conn.commit()
        logger.info("Price groups assigned for %s domains", len(assignment))
        return assignment

    except mysql.connector.Error as e:
        logger.error("Failed to assign price groups: %s", e)
        conn.rollback()
        return None
    finally:
        cursor.close()


def format_price_groups(assignment: List[Dict[str, Any]]) -> str:
    """Render group assignment with per-group sales totals."""
    lines = []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in assignment:
        groups.setdefault(row["group"], []).append(row)

    for group, rows in groups.items():
        sales = sum(int(r["sales"]) for r in rows)
        revenue = sum(Decimal(r["revenue"]) for r in rows)
        lines.append(
            f"[{group}] доменов: {len(rows)}, продаж за {PRICE_BALANCE_DAYS} дн.: "
            f"{sales}, выручка: {revenue:.0f} ₽"
        )
        for r in rows:
            lines.append(
                f"    {r['host']:<30} продаж {int(r['sales']):>3}, "
                f"трафик {int(r['traffic'])}"
            )
    return "\n".join(lines)


def load_price_experiment(
    conn: MySQLConnection, logger: logging.Logger
) -> List[Dict[str, Any]]:
    """Return experiment rows ordered by group and host."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""SELECT host, site_id, grp, target_price, applied_at
                FROM {DB_FULL_PRICE_EXPERIMENT_TABLE}
                ORDER BY grp, host
            """
        )
        rows: List[Any] = cursor.fetchall()
        return rows
    except mysql.connector.Error as e:
        logger.error("Failed to load price experiment: %s", e)
        return []
    finally:
        cursor.close()


def resolve_site_ids(
    driver: webdriver.Chrome,
    conn: MySQLConnection,
    experiment: List[Dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """Fill `site_id` of experiment rows from /mySites and persist it."""
    site_ids = {
        site["site"]: site.get("site_id") for site in parse_my_sites(driver, logger)
    }

    cursor = conn.cursor()
    try:
        for row in experiment:
            site_id = site_ids.get(row["host"])
            if site_id is None:
                logger.warning("No site_id on /mySites for %s", row["host"])
                continue
            if site_id != row["site_id"]:
                cursor.execute(
                    f"UPDATE {DB_FULL_PRICE_EXPERIMENT_TABLE} "
                    "SET site_id = %s WHERE host = %s",
                    (site_id, row["host"]),
                )
            row["site_id"] = site_id
        conn.commit()
    except mysql.connector.Error as e:
        logger.error("Failed to save site_id: %s", e)
        conn.rollback()
    finally:
        cursor.close()


def read_site_prices(
    driver: webdriver.Chrome, site_id: int, logger: logging.Logger
) -> Optional[Dict[str, Any]]:
    """Read article/note/context prices from the site card.

    Returns:
        {"paper": Decimal, "not_paper": bool, ...} or None on failure
    """
    if not navigate_with_retry(driver, EDIT_SITE_URL.format(site_id), logger):
        return None

    try:
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "price_paper"))
        )
        prices: Dict[str, Any] = {}
        for key in PRICE_FIELDS:
            value = driver.find_element(By.ID, f"price_{key}").get_attribute("value")
            prices[key] = parse_price(value or "")
            prices[f"not_{key}"] = driver.find_element(
                By.ID, f"not_price_{key}"
            ).is_selected()
        return prices

    except (TimeoutException, NoSuchElementException) as e:
        logger.error("Failed to read prices of site %s: %s", site_id, type(e).__name__)
        return None


def save_site_prices(
    conn: MySQLConnection,
    host: str,
    site_id: int,
    prices: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    """Store a price snapshot (history of reads)."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""INSERT INTO {DB_FULL_SITE_PRICES_TABLE}
                (host, site_id, price_paper, price_post, price_link,
                 not_paper, not_post, not_link, read_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                host,
                site_id,
                prices["paper"],
                prices["post"],
                prices["link"],
                int(prices["not_paper"]),
                int(prices["not_post"]),
                int(prices["not_link"]),
            ),
        )
        conn.commit()
    except mysql.connector.Error as e:
        logger.error("Failed to save prices of %s: %s", host, e)
        conn.rollback()
    finally:
        cursor.close()


def price_problems(row: Dict[str, Any], prices: Dict[str, Any]) -> List[str]:
    """List price fields that break the experiment rule for this domain.

    Control: every offered type must cost at least PRICE_CONTROL_MIN.
    Price group: all three fields must equal the group price.
    """
    problems = []
    for key, label in PRICE_FIELDS.items():
        price = prices[key]
        if row["target_price"] is None:
            if not prices[f"not_{key}"] and price < PRICE_CONTROL_MIN:
                problems.append(f"{label} {price:.0f} ₽")
        elif price != Decimal(row["target_price"]):
            problems.append(f"{label} {price:.0f} ₽ (нужно {row['target_price']})")
    return problems


def format_site_prices(row: Dict[str, Any], prices: Dict[str, Any]) -> str:
    """One line: host, group and the three prices ("выкл" = не размещаю)."""
    parts = []
    for key in PRICE_FIELDS:
        value = f"{prices[key]:.0f}"
        if prices[f"not_{key}"]:
            value += " (выкл)"
        parts.append(value)
    return f"{row['host']:<30} [{row['grp']}] статья/заметка/контекст: " + " / ".join(
        parts
    )


def read_experiment_prices(
    driver: webdriver.Chrome, conn: MySQLConnection, logger: logging.Logger
) -> None:
    """--prices-read: read and store prices of every experiment domain."""
    experiment = load_price_experiment(conn, logger)
    if not experiment:
        logger.warning("Price experiment is empty, run --prices-assign first")
        return

    resolve_site_ids(driver, conn, experiment, logger)

    lines = []
    problems = []
    for row in experiment:
        if row["site_id"] is None:
            lines.append(f"{row['host']:<30} [{row['grp']}] нет на /mySites")
            continue

        prices = read_site_prices(driver, row["site_id"], logger)
        time.sleep(DETAIL_REQUEST_DELAY)
        if prices is None:
            lines.append(f"{row['host']:<30} [{row['grp']}] не прочитать карточку")
            continue

        save_site_prices(conn, row["host"], row["site_id"], prices, logger)
        lines.append(format_site_prices(row, prices))
        for problem in price_problems(row, prices):
            problems.append(f"{row['host']} [{row['grp']}]: {problem}")

    print("\n".join(lines))
    if problems:
        print("\nНе по правилам эксперимента:")
        print("\n".join(problems))
    logger.info(
        "Prices read for %s domains, problems: %s", len(experiment), len(problems)
    )


def apply_site_price(
    driver: webdriver.Chrome, site_id: int, price: int, logger: logging.Logger
) -> bool:
    """Set one price to all PRICE_FIELDS in the site card and save it.

    The card is opened from /mySites the same way the "Настроить" link does,
    so the site's own script sends every other field unchanged.

    Returns:
        True if the card closed after saving (GGL accepted the form)
    """
    try:
        driver.execute_script("$('.jquery-modal').remove(); $('.modal').remove();")
        driver.execute_script(
            "$('<a>', {href: arguments[0], rel: 'modal:open'})"
            ".appendTo('body')[0].click();",
            EDIT_SITE_PATH.format(site_id),
        )
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, SELECTOR_SITE_CARD_SUBMIT)
            )
        )

        driver.execute_script(
            "var price = arguments[0];"
            "arguments[1].forEach(function (key) {"
            "  $('#price_' + key).val(price).trigger('change');"
            "});"
            "$(arguments[2]).click();",
            str(price),
            list(PRICE_FIELDS),
            SELECTOR_SITE_CARD_SUBMIT,
        )

        # Успех: скрипт GGL закрывает окно. Ошибка: текст в поле ошибок.
        WebDriverWait(driver, SITE_CARD_SAVE_TIMEOUT).until(
            lambda d: not any(
                e.is_displayed()
                for e in d.find_elements(By.CSS_SELECTOR, SELECTOR_SITE_CARD_SUBMIT)
            )
            or any(
                e.text.strip()
                for e in d.find_elements(By.CSS_SELECTOR, SELECTOR_SITE_CARD_ERROR)
            )
        )
        errors = [
            sanitize_text(e.text)
            for e in driver.find_elements(By.CSS_SELECTOR, SELECTOR_SITE_CARD_ERROR)
            if e.text.strip()
        ]
        if errors:
            logger.error(
                "GGL rejected prices of site %s: %s", site_id, "; ".join(errors)
            )
            return False
        return True

    except (TimeoutException, WebDriverException) as e:
        logger.error("Failed to save prices of site %s: %s", site_id, type(e).__name__)
        return False


def apply_experiment_prices(
    driver: webdriver.Chrome,
    conn: MySQLConnection,
    logger: logging.Logger,
    confirm: bool,
) -> None:
    """--prices-apply: set group prices; without --confirm only show the plan."""
    experiment = load_price_experiment(conn, logger)
    if not experiment:
        logger.warning("Price experiment is empty, run --prices-assign first")
        return

    resolve_site_ids(driver, conn, experiment, logger)

    plan = []
    for row in experiment:
        if row["target_price"] is None or row["site_id"] is None:
            continue
        prices = read_site_prices(driver, row["site_id"], logger)
        time.sleep(DETAIL_REQUEST_DELAY)
        if prices is None:
            print(f"{row['host']:<30} не прочитать карточку, пропускаю")
            continue
        if not price_problems(row, prices):
            print(f"{row['host']:<30} уже {row['target_price']} ₽")
            continue
        print(f"{format_site_prices(row, prices)} → {row['target_price']}")
        plan.append(row)

    if not plan:
        print("Менять нечего")
        return
    if not confirm:
        print(f"\nК изменению: {len(plan)}. Это пробный прогон, для записи: --confirm")
        return

    if not navigate_with_retry(driver, MY_SITES_URL, logger):
        return

    saved = []
    for row in plan:
        if apply_site_price(driver, row["site_id"], row["target_price"], logger):
            saved.append(row)
        time.sleep(DETAIL_REQUEST_DELAY)

    # Сверка: перечитываем карточку, applied_at ставим только подтверждённым.
    verified = 0
    cursor = conn.cursor()
    try:
        for row in saved:
            prices = read_site_prices(driver, row["site_id"], logger)
            time.sleep(DETAIL_REQUEST_DELAY)
            if prices is None:
                print(f"{row['host']:<30} сохранено, но не прочитать для сверки")
                continue
            save_site_prices(conn, row["host"], row["site_id"], prices, logger)
            problems = price_problems(row, prices)
            if problems:
                print(f"{row['host']:<30} не совпало: {'; '.join(problems)}")
                continue
            cursor.execute(
                f"UPDATE {DB_FULL_PRICE_EXPERIMENT_TABLE} "
                "SET applied_at = COALESCE(applied_at, NOW()) WHERE host = %s",
                (row["host"],),
            )
            verified += 1
        conn.commit()
    except mysql.connector.Error as e:
        logger.error("Failed to mark applied prices: %s", e)
        conn.rollback()
    finally:
        cursor.close()

    print(f"\nПрименено и проверено: {verified} из {len(plan)}")
    logger.info("Prices applied: planned=%s verified=%s", len(plan), verified)


def prices_report(conn: MySQLConnection, logger: logging.Logger) -> None:
    """--prices-report: sales, revenue, costs and profit per group.

    Period: from the first applied_at till now. Costs: ARTICLE_COST per
    ORDER_TASK_TITLES task.

    Формат вывода зафиксирован владельцем (docs/TZ_price_experiment.md,
    «Формат отчёта зафиксирован») — не менять без прямой просьбы.
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            f"SELECT MIN(applied_at) AS started, NOW() AS now "
            f"FROM {DB_FULL_PRICE_EXPERIMENT_TABLE}"
        )
        period: Any = cursor.fetchone()
        if period["started"] is None:
            print("Цены ещё не применены (--prices-apply --confirm)")
            return
        started, now = period["started"], period["now"]

        cursor.execute(
            f"SELECT grp, COUNT(*) AS domains FROM {DB_FULL_PRICE_EXPERIMENT_TABLE} "
            "GROUP BY grp ORDER BY grp"
        )
        domains = {row["grp"]: row["domains"] for row in cursor.fetchall()}

        title_placeholders = ", ".join(["%s"] * len(ORDER_TASK_TITLES))
        cursor.execute(
            f"""SELECT e.grp,
                       COUNT(t.id) AS sales,
                       COALESCE(SUM(t.price), 0) AS revenue,
                       COALESCE(SUM(t.title IN ({title_placeholders})), 0) AS articles
                FROM {DB_FULL_PRICE_EXPERIMENT_TABLE} e
                JOIN {DB_FULL_TABLE} t
                    -- collation колонок разная (unicode_ci и 0900_ai_ci),
                    -- без COLLATE MySQL отказывается их сравнивать.
                    ON t.domain = e.host COLLATE utf8mb4_unicode_ci
                    AND t.price > 0
                    AND t.created_at >= %s
                GROUP BY e.grp
            """,
            (*ORDER_TASK_TITLES, started),
        )
        stats: Dict[str, Any] = {row["grp"]: row for row in cursor.fetchall()}
    except mysql.connector.Error as e:
        logger.error("Failed to build price report: %s", e)
        return
    finally:
        cursor.close()

    days = (now - started).days
    print(f"Эксперимент с {started:%d.%m.%Y}, дней: {days}.")
    print(
        f"{'Группа':<9} {'Доменов':>7} {'Продаж':>6} "
        f"{'Выручка':>9} {'Затраты':>8} {'Прибыль':>9}"
    )
    for group, count in domains.items():
        row = stats.get(group)
        sales = int(row["sales"]) if row else 0
        revenue = Decimal(row["revenue"]) if row else Decimal("0")
        costs = ARTICLE_COST * (int(row["articles"]) if row else 0)
        print(
            f"{group:<9} {count:>7} {sales:>6} {revenue:>9.0f} "
            f"{costs:>8.0f} {revenue - costs:>9.0f}"
        )


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


def get_telegram_proxies(
    telegram_config: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """Build proxy settings for Telegram requests.

    Args:
        telegram_config: Telegram configuration dictionary.

    Returns:
        Requests proxies mapping or None when proxy is disabled.
    """
    proxy_server = telegram_config.get("proxy", "").strip()
    if not proxy_server:
        proxy_server = DEFAULT_FALLBACK_PROXY

    if not proxy_server:
        return None

    return {
        "http": f"http://{proxy_server}",
        "https": f"http://{proxy_server}",
    }


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
        if task.get("rework"):
            task_line += " | 🔁 <b>на доработку</b> (вручную)"
        if task.get("advertiser_text"):
            task_line += " | 📄 <b>статья предоставлена заказчиком</b> (не пишем)"
        if article_order_skip_reason(task) is None:
            task_line += " | ✍️ <b>статья пишется</b> (ждать)"
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


def format_metric_changes_message(changes: List[Dict[str, Any]]) -> str:
    """Format per-site metric changes as Telegram HTML message."""
    total_metrics = sum(len(item.get("changes", [])) for item in changes)
    lines = [
        f"<b>Изменения метрик GoGetLinks "
        f"({len(changes)} сайт(ов), {total_metrics} показател(ей))</b>"
    ]

    for item in changes:
        host = str(item.get("site", "—"))
        site = html.escape(host)
        priority_mark = " 👑" if host.strip().lower() in GGL_TOP_DOMAINS else ""
        lines.append("")
        lines.append(f"<b>{site}</b>{priority_mark}")
        for change in item.get("changes", []):
            label = html.escape(str(change.get("label", "—")))
            old_value = html.escape(str(change.get("old", "—")))
            new_value = html.escape(str(change.get("new", "—")))
            direction = change.get("direction")
            mark = {"up": "🟢", "down": "🔴"}.get(direction, "")
            prefix = f"{mark} " if mark else ""
            lines.append(f"• {prefix}{label}: {old_value} → <b>{new_value}</b>")

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
    proxies = get_telegram_proxies(telegram_config)

    try:
        request_kwargs = {"json": payload, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies

        response = requests.post(url, **request_kwargs)
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
    proxies = get_telegram_proxies(telegram_config)

    try:
        request_kwargs = {"json": payload, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies

        response = requests.post(url, **request_kwargs)
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


def send_metric_changes_notification(
    changes: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> bool:
    """Send Telegram notification about changed /mySites metrics."""
    telegram_config = config["telegram"]

    if not telegram_config.get("enabled"):
        logger.debug("Telegram notifications disabled")
        return False

    if not config.get("metrics", {}).get("enabled", True):
        logger.debug("Metric change notifications disabled")
        return False

    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        logger.warning("Telegram bot_token or chat_id not configured")
        return False

    if len(changes) == 0:
        logger.debug("No metric changes to notify about")
        return False

    message = format_metric_changes_message(changes)
    url = TELEGRAM_API_URL.format(bot_token)

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    proxies = get_telegram_proxies(telegram_config)

    try:
        request_kwargs = {"json": payload, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies

        response = requests.post(url, **request_kwargs)
        response.raise_for_status()
        result = response.json()

        if result.get("ok"):
            logger.info(
                "Telegram metric-change notification sent: "
                f"{len(changes)} site(s)"
            )
            return True

        logger.error(f"Telegram API error: {result.get('description')}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to send metric-change notification: {e}")
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
    proxies = get_telegram_proxies(telegram_config)

    try:
        request_kwargs = {"json": payload, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies

        response = requests.post(url, **request_kwargs)
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
    parser.add_argument(
        "--warm-links",
        action="store_true",
        help="Warm link cache by sending GET to each URL in ggl_links",
    )
    parser.add_argument(
        "--orders",
        action="store_true",
        help=(
            "Report ready/cancelled/stuck article orders from ggl_article_order "
            "to Telegram (no Selenium, implies --skip-tasks --skip-sites)"
        ),
    )
    parser.add_argument(
        "--cancel-order",
        type=int,
        metavar="TASK_ID",
        help=(
            "Request cancellation of an article order by gogetlinks task id "
            "(no Selenium, implies --skip-tasks --skip-sites)"
        ),
    )
    parser.add_argument(
        "--prices-assign",
        action="store_true",
        help="Price experiment: split trust-9 domains into groups (once)",
    )
    parser.add_argument(
        "--prices-read",
        action="store_true",
        help="Price experiment: read site card prices into ggl_site_prices",
    )
    parser.add_argument(
        "--prices-apply",
        action="store_true",
        help="Price experiment: show price changes (write only with --confirm)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="With --prices-apply: really save prices on gogetlinks",
    )
    parser.add_argument(
        "--prices-report",
        action="store_true",
        help="Price experiment: sales/revenue/costs per group, before vs after",
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

        needs_orders = args.orders
        cancel_order_task_id = args.cancel_order

        # Order modes are DB-only and run by their own cron line, so they never
        # drag the heavy Selenium stages along.
        orders_only = needs_orders or cancel_order_task_id is not None

        # Price experiment runs only on demand, never with the regular stages.
        prices_selenium = args.prices_read or args.prices_apply
        prices_only = prices_selenium or args.prices_assign or args.prices_report
        standalone = orders_only or prices_only

        needs_tasks = not args.skip_tasks and not standalone
        needs_sites = not args.skip_sites and not standalone
        needs_sync_links = args.sync_links
        needs_check_links = args.check_links
        needs_warm_links = args.warm_links
        needs_selenium = (
            needs_tasks or needs_sites or needs_sync_links or prices_selenium
        )

        if (
            not needs_tasks
            and not needs_sites
            and not needs_sync_links
            and not needs_check_links
            and not needs_warm_links
            and not standalone
        ):
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
        if needs_sites or prices_selenium:
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

        # --cancel-order: DB-only, nothing else runs in this mode
        if cancel_order_task_id is not None:
            logger.info("Cancelling article order %s", cancel_order_task_id)
            result = cancel_order(conn, cancel_order_task_id, logger)
            if result is None:
                return EXIT_DATABASE_ERROR
            if result is False:
                return EXIT_NOT_FOUND
            return EXIT_SUCCESS

        # --orders: DB + Telegram only
        if needs_orders:
            logger.info("Processing article orders (--orders)")
            process_orders(conn, config, logger)

        if args.prices_assign:
            logger.info("Assigning price groups (--prices-assign)")
            assignment = assign_price_groups(conn, logger)
            if assignment is None:
                return EXIT_DATABASE_ERROR
            if assignment:
                print(format_price_groups(assignment))

        if args.prices_report:
            prices_report(conn, logger)

        # --warm-links / --check-links: no Selenium needed, just DB + HTTP
        if needs_warm_links:
            logger.info("Warming links (--warm-links)")
            warm_links(conn, logger)

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

        if args.prices_read:
            logger.info("Reading site prices (--prices-read)")
            read_experiment_prices(driver, conn, logger)

        if args.prices_apply:
            logger.info("Applying site prices (--prices-apply)")
            apply_experiment_prices(driver, conn, logger, confirm=args.confirm)

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

                    # 8a. Hand new "Статья" tasks over to DDL for generation
                    process_new_article_orders(conn, new_tasks, config, logger)

                # 9. Print output (if enabled)
                print_tasks(tasks, config["output"]["print_to_console"])

        # 10. Parse and save mySites metrics
        if not needs_sites:
            logger.info("Skipping mySites parsing (--skip-sites)")
        else:
            sites = parse_my_sites(driver, logger)
            updated_sites, status_changes, metric_changes = save_sites_to_db(
                conn, sites, logger, config.get("metrics")
            )
            if len(status_changes) > 0:
                send_status_changes_notification(status_changes, config, logger)
            if len(metric_changes) > 0:
                send_metric_changes_notification(metric_changes, config, logger)
            logger.info(
                "mySites summary: "
                f"parsed={len(sites)}, updated={updated_sites}, "
                f"status_changed={len(status_changes)}, "
                f"metrics_changed={len(metric_changes)}"
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
