# Спецификация: Gogetlinks Task Parser

## Функциональные требования

### FR1: Аутентификация и обработка капчи

#### FR1.1: Вход пользователя
**Приоритет:** MUST HAVE
**Описание:** Автоматическая авторизация на gogetlinks.net с использованием credentials из конфига.

**Критерии приемки:**
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

#### FR1.2: Решение капчи
**Приоритет:** MUST HAVE
**Описание:** Интеграция с anti-captcha.org для автоматического решения reCAPTCHA v2.

**Критерии приемки:**
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

### FR2: Парсинг задач

#### FR2.1: Парсинг списка задач
**Приоритет:** MUST HAVE
**Описание:** Парсинг списка новых задач (NEW) с базовыми полями.

**Критерии приемки:**
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

#### FR2.2: Очистка и валидация данных
**Приоритет:** MUST HAVE

**Критерии приемки:**
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

### FR3: Операции с базой данных

#### FR3.1: Хранение задач
**Приоритет:** MUST HAVE

**Критерии приемки:**
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

#### FR3.2: Схема базы данных
**Приоритет:** MUST HAVE

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

### FR4: Управление конфигурацией

#### FR4.1: Файл конфигурации
**Приоритет:** MUST HAVE

**Структура config.ini:**
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

**Критерии приемки:**
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

### FR5: Вывод и логирование

#### FR5.1: Вывод в консоль
**Приоритет:** MUST HAVE

**Критерии приемки:**
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

#### FR5.2: Логирование
**Приоритет:** MUST HAVE

**Критерии приемки:**
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

## Нефункциональные требования

### NFR1: Производительность
- **Требование:** Полный цикл парсинга должен завершаться в течение 5 минут для до 100 задач
- **Измерение:** Общее время выполнения от начала до конца
- **Обоснование:** Позволяет выполнять почасовое расписание cron без пересечений

### NFR2: Надёжность
- **Требование:** 95% успешных сессий парсинга (исключая простой сайта)
- **Измерение:** Успешные запуски / общее количество запусков за 30 дней
- **Обоснование:** Приемлемый процент сбоев для случайных проблем с капчей

### NFR3: Сопровождаемость
- **Требование:** Модульная структура кода с чётким разделением обязанностей
- **Измерение:** Чеклист code review (см. ниже)
- **Обоснование:** Лёгкая отладка и добавление функций

### NFR4: Безопасность
- **Требование:** Учётные данные никогда не логируются и не отображаются в сообщениях об ошибках
- **Измерение:** Аудит кода + просмотр логов
- **Обоснование:** Защита учётных данных пользователя и API ключей

### NFR5: Масштабируемость
- **Требование:** Поддержка парсинга до 1000 задач без деградации производительности
- **Измерение:** Время выполнения для 1000 задач < 30 минут
- **Обоснование:** Готовность к увеличению объёма задач в будущем

## Пользовательские истории

### История 1: Автоматическое обнаружение задач
**Как** фриланс-разработчик
**Я хочу** автоматически проверять наличие новых задач каждый час
**Чтобы** не пропускать возможности, пока я работаю над другими проектами

**Критерии приемки:**
- Парсер запускается каждый час через cron
- Новые задачи помечаются флагом `is_new = 1`
- Я могу запрашивать базу данных для новых задач в любое время

### История 2: Детали задач для принятия решений
**Как** фриланс-разработчик
**Я хочу** видеть полные детали задачи, включая описание и требования
**Чтобы** быстро решить, подходит ли мне задача

**Критерии приемки:**
- Описание, требования и контакты хранятся в базе данных
- Я могу запрашивать по диапазону цен: `SELECT * FROM tasks WHERE price > 50 AND is_new = 1`
- Я могу запрашивать по заказчику: `SELECT * FROM tasks WHERE customer = 'Client A'`

### История 3: Историческое отслеживание
**Как** фриланс-разработчик
**Я хочу** отслеживать, какие задачи я уже просмотрел
**Чтобы** не тратить время на просмотр одних и тех же задач повторно

**Критерии приемки:**
- Задачи обновляют флаг `is_new` на 0 после первого парсинга
- Я могу отмечать задачи как "просмотренные" вручную (будущая функция)
- Отслеживание меток времени показывает, когда задача была впервые обнаружена и последний раз обновлена

## Зависимости

### Внешние сервисы
- **gogetlinks.net** - источник данных (нет SLA)
- **anti-captcha.com** - решение капчи (99% uptime SLA)
- **MySQL server** - база данных (self-hosted)

### Библиотеки Python
```
selenium>=4.10.0        # Browser automation
mysql-connector-python  # MySQL driver
configparser           # INI config parsing
logging                # Standard logging
```

### Системные требования
- Python 3.8+
- Chrome/Chromium browser (headless)
- MySQL 8.0+
- Ubuntu 20.04+ или аналогичный дистрибутив Linux (VPS)
- Минимум 1GB RAM, 10GB дискового пространства

## Тестовые сценарии

### Интеграционные тесты

#### Тест 1: Сквозной позитивный сценарий
```python
def test_full_parsing_cycle():
    """
    Тест полного парсинга от авторизации до вставки в базу данных
    """
    # Given: Валидный config с настоящими credentials
    # When: Парсер выполняет полный цикл
    # Then: Как минимум 1 задача должна быть вставлена в базу данных
    # And: Лог должен содержать "Successfully authenticated"
    # And: Код выхода должен быть 0
```

#### Тест 2: Обработка сбоя капчи
```python
def test_captcha_failure_retry():
    """
    Тест логики повтора при сбое решения капчи
    """
    # Given: Сервис Anti-captcha временно недоступен
    # When: Парсер пытается выполнить аутентификацию
    # Then: Он должен повторить попытку 3 раза с задержкой 5 секунд
    # And: Лог должен содержать "Retry attempt 1/3"
    # And: Код выхода должен быть 2 после 3 неудачных попыток
```

#### Тест 3: Обнаружение дубликатов
```python
def test_duplicate_task_handling():
    """
    Тест того, что дублирующиеся задачи обновляются, а не вставляются
    """
    # Given: База данных уже содержит task_id 123456
    # When: Парсер встречает тот же task_id снова
    # Then: В базе данных должна быть только 1 строка с этим task_id
    # And: updated_at должна быть текущей меткой времени
    # And: is_new должен быть 0
```

---

## Сводка ограничений

| Ограничение | Значение |
|------------|-------|
| Язык программирования | Python 3.8+ |
| Автоматизация браузера | Selenium WebDriver |
| База данных | MySQL 8.0+ |
| Развёртывание | VPS (без Docker) |
| Планировщик | Cron |
| Решение капчи | Anti-Captcha.org |

---

**Версия документа:** 1.0
**Последнее обновление:** 2026-02-05
**Уровень уверенности:** Высокий (95%)
