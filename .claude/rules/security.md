# Security Rules

Правила безопасности для проекта Gogetlinks Task Parser.

## Критические правила

### 1. НИКОГДА не логировать credentials
```python
# ❌ ЗАПРЕЩЕНО
logger.info(f"Password: {password}")
logger.debug(f"API key: {api_key}")
logger.info(f"Authenticating with {username}:{password}")

# ✅ ПРАВИЛЬНО
logger.info(f"Authenticating as {mask_email(username)}")
logger.info("API key configured")
```

### 2. Маскирование чувствительных данных
```python
def mask_email(email: str) -> str:
    """Mask email for logging."""
    if '@' not in email:
        return '***'

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = '*' * len(local)
    else:
        masked_local = local[0] + '*' * (len(local) - 1)

    return f"{masked_local}@{domain}"

# Output: "u***@example.com"
```

### 3. Хранение credentials
```python
# ❌ ЗАПРЕЩЕНО - хардкод в коде
USERNAME = "myuser@example.com"
PASSWORD = "mypassword123"

# ✅ ПРАВИЛЬНО - из config файла
config = configparser.ConfigParser()
config.read('config.ini')
username = config['gogetlinks']['username']
password = config['gogetlinks']['password']

# ❌ ЗАПРЕЩЕНО - коммитить config.ini
# ✅ ПРАВИЛЬНО - использовать config.ini.example
```

## SQL Injection Protection

### Используйте параметризованные запросы
```python
# ❌ ОПАСНО - SQL injection
cursor.execute(f"SELECT * FROM tasks WHERE task_id = {task_id}")

# ✅ БЕЗОПАСНО - параметризованный запрос
cursor.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))

# ✅ БЕЗОПАСНО - INSERT с параметрами
cursor.execute("""
    INSERT INTO tasks (task_id, title, price)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE
        title = VALUES(title),
        price = VALUES(price)
""", (task_id, title, price))
```

## XSS Protection

### Валидация и санитизация входных данных
```python
def sanitize_html(text: str) -> str:
    """Remove potentially dangerous HTML."""
    # Remove script tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove event handlers
    text = re.sub(r'\son\w+\s*=\s*["\'].*?["\']', '', text, flags=re.IGNORECASE)

    return text

# Использование
title = sanitize_html(raw_title)
```

## Path Traversal Protection

```python
import os

def safe_file_path(base_dir: str, filename: str) -> str:
    """Prevent path traversal attacks."""
    # Normalize path
    filepath = os.path.normpath(os.path.join(base_dir, filename))

    # Ensure it's within base_dir
    if not filepath.startswith(os.path.abspath(base_dir)):
        raise ValueError(f"Invalid file path: {filename}")

    return filepath

# ❌ ОПАСНО
log_file = f"/var/log/{user_input}.log"

# ✅ БЕЗОПАСНО
log_file = safe_file_path("/var/log", user_input)
```

## Selenium Security

### Отключение опасных функций
```python
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

# Отключить расширения
options.add_argument('--disable-extensions')

# Отключить JavaScript (если не нужен)
options.add_experimental_option('prefs', {
    'profile.managed_default_content_settings.javascript': 2
})
```

### Проверка URL перед навигацией
```python
from urllib.parse import urlparse

ALLOWED_DOMAINS = ['gogetlinks.net']

def safe_navigate(driver: WebDriver, url: str) -> None:
    """Navigate only to allowed domains."""
    parsed = urlparse(url)

    if parsed.netloc not in ALLOWED_DOMAINS:
        raise ValueError(f"Navigation to {parsed.netloc} is not allowed")

    driver.get(url)
```

## API Key Security

### Валидация API ключей
```python
def validate_api_key(api_key: str) -> bool:
    """Validate Anti-Captcha API key format."""
    # Anti-Captcha keys are 32 hex characters
    pattern = r'^[a-f0-9]{32}$'

    if not re.match(pattern, api_key, re.IGNORECASE):
        logger.error("Invalid API key format")
        return False

    return True
```

### Ротация API ключей
```python
# Использовать environment variables для production
import os

API_KEY = os.getenv('ANTICAPTCHA_API_KEY')
if not API_KEY:
    logger.error("ANTICAPTCHA_API_KEY not set")
    sys.exit(3)
```

## Database Security

### Минимальные привилегии
```sql
-- Создать пользователя только с необходимыми правами
CREATE USER 'gogetlinks_parser'@'localhost' IDENTIFIED BY 'secure_password';

-- Только SELECT, INSERT, UPDATE на tasks
GRANT SELECT, INSERT, UPDATE ON gogetlinks_db.tasks TO 'gogetlinks_parser'@'localhost';

-- НЕ давать DROP, DELETE, или admin права
FLUSH PRIVILEGES;
```

### Connection String Security
```python
# ❌ ЗАПРЕЩЕНО - логировать connection string
logger.info(f"Connecting to {connection_string}")

# ✅ ПРАВИЛЬНО
logger.info(f"Connecting to database on {host}")

# Использовать SSL для удалённых подключений
connection = mysql.connector.connect(
    host=host,
    user=user,
    password=password,
    database=database,
    ssl_ca='/path/to/ca.pem',
    ssl_verify_cert=True
)
```

## Error Handling Security

### Не раскрывать stack traces пользователю
```python
# ❌ ОПАСНО - полный stack trace в логе
except Exception as e:
    logger.error(f"Error: {e}")
    print(traceback.format_exc())

# ✅ БЕЗОПАСНО - общее сообщение + внутренний лог
except Exception as e:
    logger.error(f"Authentication failed: {type(e).__name__}", exc_info=True)
    print("Authentication failed. Check logs for details.")
    sys.exit(1)
```

## File Permissions

### Правильные права доступа
```bash
# Config файл - только владелец может читать
chmod 600 config.ini

# Log файлы - владелец может читать/писать
chmod 640 *.log

# Скрипт - владелец может выполнять
chmod 750 gogetlinks_parser.py
```

## Session Management

### Безопасное хранение cookies
```python
import pickle
import os

COOKIE_FILE = 'session_cookies.pkl'

def save_cookies(driver: WebDriver) -> None:
    """Save cookies securely."""
    cookies = driver.get_cookies()

    with open(COOKIE_FILE, 'wb') as f:
        pickle.dump(cookies, f)

    # Set restrictive permissions
    os.chmod(COOKIE_FILE, 0o600)

def load_cookies(driver: WebDriver) -> None:
    """Load cookies if exist."""
    if os.path.exists(COOKIE_FILE):
        # Verify permissions
        stat = os.stat(COOKIE_FILE)
        if stat.st_mode & 0o077:
            logger.warning("Cookie file has insecure permissions")
            return

        with open(COOKIE_FILE, 'rb') as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
```

## Security Checklist

Перед каждым коммитом проверить:
- [ ] Нет хардкода паролей/ключей
- [ ] Нет логирования credentials
- [ ] Используются параметризованные SQL запросы
- [ ] Валидация всех входных данных
- [ ] Правильные file permissions
- [ ] config.ini в .gitignore
- [ ] Безопасная обработка ошибок
- [ ] Нет раскрытия stack traces пользователю

## Incident Response

При обнаружении утечки credentials:
1. Немедленно сменить пароли/API ключи
2. Ревокнуть скомпрометированные токены
3. Проверить git history на наличие credentials
4. Если нашли в git - использовать git filter-branch для удаления
5. Force push cleaned history (ТОЛЬКО в этом случае)
