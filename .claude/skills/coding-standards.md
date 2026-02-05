# Coding Standards Skill

Стандарты кодирования для проекта Gogetlinks Task Parser.

## Стиль кода

### PEP 8 Compliance
- Используйте `black` для автоматического форматирования
- Максимальная длина строки: 88 символов
- Используйте 4 пробела для отступов

### Type Hints
Всегда используйте type hints для функций:

```python
def parse_task(row: WebElement) -> Task:
    """Extract task data from HTML row."""
    pass

def authenticate(driver: WebDriver, config: Dict[str, Any]) -> bool:
    """Authenticate on gogetlinks.net."""
    pass
```

### Docstrings
Используйте Google style docstrings:

```python
def solve_captcha(api_key: str, sitekey: str) -> Optional[str]:
    """Solve reCAPTCHA using anti-captcha.com.

    Args:
        api_key: Anti-captcha.com API key
        sitekey: reCAPTCHA site key

    Returns:
        Captcha token string or None if failed

    Raises:
        CaptchaError: If captcha solving fails after retries
    """
    pass
```

## Именование

### Функции и переменные
- `snake_case` для функций и переменных
- Глаголы для функций: `parse_task()`, `authenticate()`, `insert_task()`
- Существительные для переменных: `task_id`, `captcha_token`, `db_connection`

### Классы
- `PascalCase` для классов: `TaskParser`, `Authenticator`, `TaskDatabase`

### Константы
- `UPPER_SNAKE_CASE` для констант: `MAX_RETRIES`, `DEFAULT_TIMEOUT`

## Обработка ошибок

### Специфичные исключения
```python
# ХОРОШО
try:
    task = parse_task(row)
except ValueError as e:
    logger.warning(f"Invalid task format: {e}")
    return None

# ПЛОХО
except Exception:
    pass
```

### Логирование с контекстом
```python
# ХОРОШО
logger.error(f"Failed to parse task {task_id}: {e}", exc_info=True)

# ПЛОХО
logger.error("Error occurred")
```

### Exit codes
Всегда используйте правильные exit codes:
```python
sys.exit(0)   # Success
sys.exit(1)   # Auth failed
sys.exit(2)   # Captcha failed
sys.exit(3)   # Config error
sys.exit(4)   # Database error
```

## Безопасность

### НИКОГДА не логировать
```python
# ЗАПРЕЩЕНО
logger.info(f"Password: {password}")
logger.debug(f"API key: {api_key}")

# ПРАВИЛЬНО
logger.info(f"Authenticating as {mask_email(username)}")
# Output: "Authenticating as u***@example.com"
```

### Валидация входных данных
```python
def parse_price(text: str) -> Decimal:
    """Parse price with validation."""
    if not text:
        return Decimal("0.00")

    # Sanitize input
    cleaned = re.sub(r'[^\d.,]', '', text)

    try:
        return Decimal(cleaned)
    except (ValueError, InvalidOperation):
        logger.warning(f"Invalid price format: {text}")
        return Decimal("0.00")
```

## Тестирование

### Структура тестов
```python
class TestPriceParser:
    """Тесты парсинга цен."""

    @pytest.mark.parametrize("input_price,expected", [
        ("$123.45", Decimal("123.45")),
        ("FREE", Decimal("0.00")),
    ])
    def test_parse_price_robust(self, input_price, expected):
        """Тест парсинга различных форматов."""
        assert parse_price(input_price) == expected
```

### Минимальное покрытие
- Общее покрытие: >80%
- Критические пути (auth, parsing, db): 100%

## Производительность

### База данных
```python
# ХОРОШО - Атомарная операция
INSERT INTO tasks (...) VALUES (...)
ON DUPLICATE KEY UPDATE ...

# ПЛОХО - Две операции
if not task_exists(task_id):
    insert_task(task)
```

### Selenium
```python
# ХОРОШО - Явное ожидание
element = WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, "tr[id^='col_row_']"))
)

# ПЛОХО - time.sleep
time.sleep(5)
```

## Git Workflow

### Commit Messages
```bash
# Формат
type(scope): description

# Примеры
feat(parser): add detail page extraction
fix(auth): handle captcha timeout correctly
test(parser): add price parsing tests
docs(readme): update installation steps
```

### Типы коммитов
- `feat` - новая функциональность
- `fix` - исправление бага
- `refactor` - рефакторинг
- `test` - добавление тестов
- `docs` - документация
- `chore` - инфраструктура

### Правило
1 логическое изменение = 1 коммит
