# Coding Style Rules

Правила стиля кода для проекта Gogetlinks Task Parser.

## Автоматическое форматирование

### Black
```bash
# Форматирование всего проекта
black .

# Проверка без изменений
black --check .

# Форматирование конкретного файла
black gogetlinks_parser.py
```

### Конфигурация
```toml
# pyproject.toml
[tool.black]
line-length = 88
target-version = ['py38']
include = '\.pyi?$'
extend-exclude = '''
/(
  # directories
  \.eggs
  | \.git
  | \.venv
  | build
  | dist
)/
'''
```

## PEP 8 Compliance

### Line Length
- Максимум 88 символов (Black default)
- Для комментариев: 72 символа

### Indentation
- 4 пробела для отступов
- НЕ использовать tabs

### Imports
```python
# Порядок импортов:
# 1. Standard library
import sys
import os
from typing import Optional, List, Dict

# 2. Third-party
import mysql.connector
from selenium import webdriver
from selenium.webdriver.common.by import By

# 3. Local application
from config import load_config
from logger import setup_logger

# Использовать absolute imports
from gogetlinks_parser import parse_task  # ✅
from .parser import parse_task             # ❌
```

### Whitespace
```python
# ✅ ПРАВИЛЬНО
def function(arg1, arg2):
    result = arg1 + arg2
    return result

x = 1
y = 2
long_variable = 3

# ❌ НЕПРАВИЛЬНО
def function( arg1,arg2 ):
    result=arg1+arg2
    return result

x      = 1
y      = 2
long_variable=3
```

## Type Hints

### Обязательны для всех функций
```python
from typing import Optional, List, Dict, Any
from decimal import Decimal
from selenium.webdriver.remote.webelement import WebElement

def parse_price(text: str) -> Decimal:
    """Parse price from text."""
    pass

def authenticate(
    driver: WebDriver,
    username: str,
    password: str
) -> bool:
    """Authenticate on gogetlinks.net."""
    pass

def parse_task_row(row: WebElement) -> Optional[Dict[str, Any]]:
    """Extract task data from HTML row."""
    pass
```

### Complex types
```python
from typing import Tuple, Union, Callable

# Function returning tuple
def get_credentials() -> Tuple[str, str]:
    return username, password

# Union types
def parse_value(text: str) -> Union[Decimal, None]:
    pass

# Callbacks
def retry(
    func: Callable[[], bool],
    max_attempts: int = 3
) -> bool:
    pass
```

## Docstrings

### Google Style
```python
def solve_captcha(
    api_key: str,
    sitekey: str,
    page_url: str,
    timeout: int = 120
) -> Optional[str]:
    """Solve reCAPTCHA using anti-captcha.com API.

    Sends captcha task to anti-captcha.com and polls for solution.
    Retries on network errors. Returns None on timeout or API errors.

    Args:
        api_key: Anti-captcha.com API key (32 hex chars)
        sitekey: reCAPTCHA site key from target page
        page_url: Full URL where captcha is located
        timeout: Maximum seconds to wait for solution (default: 120)

    Returns:
        Captcha solution token string, or None if solving failed

    Raises:
        ValueError: If api_key or sitekey format is invalid
        requests.RequestException: On network errors after all retries

    Example:
        >>> token = solve_captcha(
        ...     api_key='a1b2c3...',
        ...     sitekey='6LcX...',
        ...     page_url='https://example.com/login'
        ... )
        >>> if token:
        ...     print(f"Solved: {token[:20]}...")
    """
    pass
```

### Краткие docstrings
```python
def mask_email(email: str) -> str:
    """Mask email for safe logging (e.g., u***@example.com)."""
    pass

def is_authenticated(driver: WebDriver) -> bool:
    """Check if user is currently authenticated."""
    pass
```

## Naming Conventions

### Functions and Variables
```python
# snake_case для функций и переменных
def parse_task_list():
    pass

task_id = 123
captcha_token = "abc123"
db_connection = connect_to_database()

# Глаголы для функций
def authenticate():    # ✅
def parse_price():     # ✅
def is_valid():        # ✅

def authentication():  # ❌ существительное
def price_parser():    # ❌ существительное
```

### Classes
```python
# PascalCase для классов
class TaskParser:
    pass

class Authenticator:
    pass

class TaskDatabase:
    pass

# Существительные для классов
class Task:           # ✅
class WebDriver:      # ✅

class ParseTask:      # ❌ глагол
class AuthenticateUser:  # ❌ глагол
```

### Constants
```python
# UPPER_SNAKE_CASE для констант
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
LOGIN_URL = "https://gogetlinks.net/user/signIn"

# Размещать в начале модуля
```

### Private Members
```python
class TaskParser:
    def __init__(self):
        self._driver = None        # Protected
        self.__api_key = "secret"  # Private

    def parse(self):               # Public
        """Public method."""
        self._prepare()            # Protected method

    def _prepare(self):            # Protected
        """Internal preparation."""
        pass
```

## Code Organization

### Module Structure
```python
"""Module docstring describing purpose.

This module handles authentication on gogetlinks.net
including captcha solving via anti-captcha.com API.
"""

# Imports
import sys
import logging
from typing import Optional

# Constants
MAX_RETRIES = 3
TIMEOUT = 30

# Module-level variables
logger = logging.getLogger(__name__)

# Functions
def authenticate(username: str, password: str) -> bool:
    """Authenticate user."""
    pass

# Classes
class Authenticator:
    """Handle authentication logic."""
    pass

# Main guard
if __name__ == "__main__":
    main()
```

### Function Length
- Максимум 50 строк на функцию
- Если больше - разбить на подфункции

```python
# ❌ ПЛОХО - слишком длинная функция
def parse_and_save_tasks():
    # 100 lines of code...
    pass

# ✅ ХОРОШО - разбито на части
def parse_tasks() -> List[Task]:
    """Parse tasks from page."""
    pass

def save_tasks(tasks: List[Task]) -> None:
    """Save tasks to database."""
    pass

def parse_and_save_tasks() -> None:
    """Orchestrate parsing and saving."""
    tasks = parse_tasks()
    save_tasks(tasks)
```

## Comments

### When to Comment
```python
# ✅ ХОРОШО - объяснение "почему"
# Use Windows-1251 encoding because gogetlinks.net returns this encoding
content = response.content.decode('windows-1251')

# ✅ ХОРОШО - предупреждение
# WARNING: This must run before driver.get() or cookies won't be set
for cookie in cookies:
    driver.add_cookie(cookie)

# ❌ ПЛОХО - объяснение "что" (очевидно из кода)
# Increment counter by 1
counter += 1
```

### TODO Comments
```python
# TODO(username): Add retry logic for network errors
# TODO(username): Optimize query with index on task_id
# FIXME(username): Handle case when captcha API is down
# HACK(username): Temporary workaround for Selenium 4.0 bug
```

## Error Handling

### Specific Exceptions
```python
# ✅ ХОРОШО
try:
    task = parse_task(row)
except ValueError as e:
    logger.warning(f"Invalid task format: {e}")
    return None
except KeyError as e:
    logger.error(f"Missing required field: {e}")
    return None

# ❌ ПЛОХО
try:
    task = parse_task(row)
except Exception:
    pass
```

### Exception Chaining
```python
# ✅ ХОРОШО
try:
    connect_to_database()
except mysql.connector.Error as e:
    raise DatabaseError("Failed to connect") from e

# ❌ ПЛОХО
try:
    connect_to_database()
except mysql.connector.Error:
    raise DatabaseError("Failed to connect")  # Теряется original exception
```

## Logging

### Structured Logging
```python
# ✅ ХОРОШО - с контекстом
logger.info(f"Parsing task {task_id}")
logger.error(f"Failed to parse task {task_id}: {e}", exc_info=True)
logger.warning(f"Retrying ({attempt}/{max_retries})")

# ❌ ПЛОХО - без контекста
logger.info("Parsing task")
logger.error("Error occurred")
```

### Log Levels
```python
logger.debug("Detailed info for debugging")    # Development only
logger.info("General informational messages")  # Normal operation
logger.warning("Warning messages")             # Recoverable issues
logger.error("Error messages")                 # Failures
logger.critical("Critical failures")           # System-wide failures
```

## Boolean Expressions

### Explicit Comparisons
```python
# ✅ ХОРОШО
if len(tasks) > 0:
    process_tasks(tasks)

if user is not None:
    authenticate(user)

# ❌ ПЛОХО (хотя и работает)
if tasks:
    process_tasks(tasks)

if user:
    authenticate(user)
```

### Early Returns
```python
# ✅ ХОРОШО - early return
def process_task(task: Optional[Task]) -> bool:
    if task is None:
        return False

    if not task.is_valid():
        return False

    # Main logic here
    return save_task(task)

# ❌ ПЛОХО - вложенные if
def process_task(task: Optional[Task]) -> bool:
    if task is not None:
        if task.is_valid():
            return save_task(task)
        else:
            return False
    else:
        return False
```

## String Formatting

### f-strings (Python 3.6+)
```python
# ✅ ХОРОШО
logger.info(f"Processing task {task_id}")
message = f"Found {len(tasks)} tasks"

# ❌ УСТАРЕЛО
logger.info("Processing task %s" % task_id)
message = "Found {} tasks".format(len(tasks))
```

## Code Smells to Avoid

### Magic Numbers
```python
# ❌ ПЛОХО
time.sleep(120)
if attempts > 3:
    break

# ✅ ХОРОШО
CAPTCHA_TIMEOUT = 120
MAX_RETRIES = 3

time.sleep(CAPTCHA_TIMEOUT)
if attempts > MAX_RETRIES:
    break
```

### Nested Loops/Conditions
```python
# ❌ ПЛОХО - 3+ levels
for task in tasks:
    if task.is_valid():
        if not task.exists_in_db():
            if task.save():
                count += 1

# ✅ ХОРОШО - refactored
for task in tasks:
    if not task.is_valid():
        continue

    if task.exists_in_db():
        continue

    if task.save():
        count += 1
```

## Linting

### flake8 configuration
```ini
# .flake8
[flake8]
max-line-length = 88
extend-ignore = E203, W503
exclude =
    .git,
    __pycache__,
    .venv,
    build,
    dist
```

### Pre-commit checks
```bash
# В Makefile
lint:
	black --check .
	flake8 .
	mypy *.py

format:
	black .
	isort .
```
