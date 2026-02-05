# Уточнение: Парсер задач Gogetlinks

## Граничные случаи и сценарии ошибок

### EC1: Граничные случаи, связанные с капчей

#### EC1.1: Капча отсутствует
**Сценарий:** Страница входа загружается без капчи
**Причина:** Cookie сессии все еще действителен ИЛИ сайт временно отключил капчу
**Обработка:**
```python
if captcha_element is None:
    logger.warning("No captcha found, attempting direct login")
    # Продолжить отправку формы без токена капчи
```
**Тест:** Очистить cookies и проверить, появляется ли капча

#### EC1.2: Sitekey капчи изменился
**Сценарий:** Anti-captcha получает sitekey в другом формате
**Причина:** Сайт обновил версию reCAPTCHA
**Обработка:**
```python
if not is_valid_sitekey(sitekey):
    logger.error(f"Invalid sitekey format: {sitekey}")
    # Сделать скриншот для отладки
    driver.save_screenshot("invalid_sitekey.png")
    raise CaptchaError("Sitekey format changed")
```

#### EC1.3: Лимит частоты запросов к API Anti-Captcha
**Сценарий:** Слишком много запросов к anti-captcha.com
**Причина:** Слишком частый запуск парсера
**Обработка:**
```python
if response.status_code == 429:
    logger.warning("Rate limited by anti-captcha, waiting 60s")
    time.sleep(60)
    retry_solve_captcha()
```

#### EC1.4: Капча решена, но вход все равно не выполнен
**Сценарий:** Токен капчи действителен, но форма входа отклоняет отправку
**Причина:** Неверные учетные данные ИЛИ дополнительный шаг верификации
**Обработка:**
```python
if captcha_solved and not is_authenticated():
    logger.error("Captcha solved but login failed")
    # Проверить сообщения об ошибках на странице
    error_msg = driver.find_element(By.CSS_SELECTOR, ".error-message").text
    logger.error(f"Login error: {error_msg}")
    raise AuthenticationError("Credentials rejected")
```

### EC2: Граничные случаи парсинга

#### EC2.1: Неполные строки задач
**Сценарий:** В строке задачи отсутствуют ячейки <td>
**Причина:** Некорректный HTML ИЛИ другой тип задачи
**Обработка:**
```python
def parse_task_row_safe(row):
    try:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            logger.warning(f"Incomplete row (task_id unknown): {len(cells)} cells")
            return None  # Пропустить эту задачу
        return parse_task_row(row)
    except Exception as e:
        logger.warning(f"Failed to parse row: {e}")
        return None
```

#### EC2.2: Цена в неожиданном формате
**Сценарий:** Цена содержит символы валют, буквы или несколько десятичных разделителей
**Примеры:**
- "$123.45 USD"
- "1,234.56"
- "FREE"
- "TBD"

**Обработка:**
```python
def parse_price_robust(text):
    # Удалить распространенные символы валют и пробелы
    text = re.sub(r'[^\d.,]', '', text)

    # Заменить запятую на точку
    text = text.replace(',', '.')

    # Обработать несколько точек (взять последний сегмент)
    if text.count('.') > 1:
        parts = text.split('.')
        text = parts[-2] + '.' + parts[-1]

    try:
        return Decimal(text)
    except:
        logger.warning(f"Could not parse price: {text}")
        return Decimal('0.00')
```

#### EC2.3: Проблемы с кодировкой кириллицы
**Сценарий:** Описание задачи содержит некорректные кириллические символы
**Причина:** Неправильное определение кодировки (не Windows-1251)
**Обработка:**
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

#### EC2.4: Пустой список задач (нет НОВЫХ задач)
**Сценарий:** /webTask/index возвращает пустую таблицу
**Причина:** Новые задачи отсутствуют ИЛИ загружена неправильная страница
**Обработка:**
```python
task_rows = driver.find_elements(By.CSS_SELECTOR, "tr[id^='col_row_']")
if len(task_rows) == 0:
    # Проверить, что мы на правильной странице
    if "Новые" not in driver.page_source:
        logger.error("Not on NEW tasks page, possible navigation error")
        raise NavigationError("Wrong page loaded")
    logger.info("No new tasks available")
    return []
```

#### EC2.5: Страница деталей задачи возвращает 404
**Сценарий:** URL деталей задачи возвращает 404
**Причина:** Задача была удалена ИЛИ формат URL изменился
**Обработка:**
```python
driver.get(f"https://gogetlinks.net/template/view_task.php?curr_id={task_id}")
if "404" in driver.title or "Not Found" in driver.page_source:
    logger.warning(f"Task {task_id} not found (deleted?)")
    return None  # Пропустить эту задачу
```

### EC3: Граничные случаи базы данных

#### EC3.1: Потеря соединения с базой данных во время операции
**Сценарий:** Соединение MySQL обрывается во время пакетной вставки
**Причина:** Проблема с сетью ИЛИ таймаут MySQL
**Обработка:**
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

#### EC3.2: Дублирование ключа при конкурентных вставках
**Сценарий:** Два экземпляра парсера пытаются вставить один и тот же task_id
**Причина:** Перекрывающиеся расписания cron ИЛИ ручное выполнение
**Обработка:**
```python
INSERT INTO tasks (...) VALUES (...)
ON DUPLICATE KEY UPDATE
    updated_at = NOW(),
    is_new = IF(is_new = 1, 1, 0)  -- Сохранить флаг новизны
```

#### EC3.3: Диск базы данных заполнен
**Сценарий:** INSERT завершается неудачей из-за нехватки места на диске
**Причина:** Рост таблицы логов ИЛИ временные файлы
**Обработка:**
```python
except mysql.connector.errors.DatabaseError as e:
    if "disk full" in str(e).lower():
        logger.critical("Database disk full! Manual intervention required")
        send_alert_email()  # Будущая функция
        sys.exit(4)
```

### EC4: Граничные случаи сети и таймаутов

#### EC4.1: gogetlinks.net временно недоступен
**Сценарий:** Сайт возвращает 503 или отказ в соединении
**Причина:** Обслуживание ИЛИ перегрузка
**Обработка:**
```python
try:
    driver.get("https://gogetlinks.net/user/signIn")
except WebDriverException as e:
    if "connection refused" in str(e).lower():
        logger.warning("gogetlinks.net unreachable, will retry next cron cycle")
        sys.exit(0)  # Выйти корректно, это не ошибка
```

#### EC4.2: Таймаут загрузки страницы
**Сценарий:** Загрузка списка задач занимает > 30 секунд
**Причина:** Медленная работа сайта ИЛИ перегрузка сети
**Обработка:**
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

#### EC4.3: Устаревший элемент после обновления страницы
**Сценарий:** Парсируемый элемент становится устаревшим во время извлечения данных
**Причина:** JavaScript динамически обновил DOM
**Обработка:**
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

## Стратегия тестирования

### Модульные тесты

#### Тест 1: Валидация конфигурации
```python
def test_config_validation():
    # Невалидная конфигурация (отсутствует секция)
    config = configparser.ConfigParser()
    config.read_string("[database]\nhost=localhost")
    with pytest.raises(ConfigError):
        validate_config(config)

    # Валидная конфигурация
    config = load_test_config()
    assert validate_config(config) == True
```

#### Тест 2: Парсинг цены
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

#### Тест 3: Извлечение ID задачи
```python
def test_task_id_extraction():
    # Валидный ID
    row = Mock()
    row.get_attribute.return_value = "col_row_123456"
    assert extract_task_id(row) == 123456

    # Невалидный формат
    row.get_attribute.return_value = "invalid"
    with pytest.raises(ValueError):
        extract_task_id(row)
```

### Интеграционные тесты

#### Тест 4: Полный процесс аутентификации (используя тестовый аккаунт)
```python
def test_authentication_flow():
    """Требует тестовые учетные данные в config_test.ini"""
    config = load_test_config()
    driver = webdriver.Chrome(options=get_headless_options())

    try:
        authenticator = Authenticator(driver, config)
        result = authenticator.authenticate()
        assert result == True

        # Проверить, что мы на аутентифицированной странице
        assert "/profile" in driver.current_url or "Выйти" in driver.page_source
    finally:
        driver.quit()
```

#### Тест 5: Парсинг пустого списка задач
```python
def test_parse_empty_task_list(mock_driver):
    mock_driver.find_elements.return_value = []
    parser = TaskParser(mock_driver)
    tasks = parser.parse_task_list()
    assert tasks == []
```

#### Тест 6: Дедупликация в базе данных
```python
def test_database_deduplication():
    db = get_test_database()
    task = Task(task_id=999, domain="test.com", price=100)

    # Первая вставка
    insert_task(db, task)
    count1 = db.cursor().execute("SELECT COUNT(*) FROM tasks WHERE task_id=999").fetchone()[0]
    assert count1 == 1

    # Вторая вставка (должна обновить, а не дублировать)
    task.price = 200
    insert_task(db, task)
    count2 = db.cursor().execute("SELECT COUNT(*) FROM tasks WHERE task_id=999").fetchone()[0]
    assert count2 == 1  # По-прежнему только 1 строка

    # Проверить, что цена была обновлена
    price = db.cursor().execute("SELECT price FROM tasks WHERE task_id=999").fetchone()[0]
    assert price == Decimal("200.00")
```

### Сквозные тесты

#### Тест 7: Полный цикл парсинга (Staging)
```python
@pytest.mark.slow
def test_full_parsing_cycle():
    """
    Сквозной тест с использованием реальных учетных данных (staging окружение)
    ВНИМАНИЕ: Использует реальные кредиты anti-captcha
    """
    # Запустить полный скрипт
    result = subprocess.run(
        ["python", "gogetlinks_parser.py"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "Successfully authenticated" in result.stdout
    assert "Parsing completed" in result.stdout

    # Проверить, что в базе данных есть записи
    db = connect_to_database()
    count = db.cursor().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count > 0
```

### Нагрузочные тесты

#### Тест 8: Производительность парсинга 1000 задач
```python
def test_parse_performance():
    """
    Mock-тест для проверки скорости парсинга
    """
    start = time.time()

    # Mock 1000 строк задач
    mock_rows = [create_mock_task_row(i) for i in range(1000)]
    parser = TaskParser(None)

    tasks = []
    for row in mock_rows:
        tasks.append(parser._extract_task_row(row))

    elapsed = time.time() - start
    assert elapsed < 10  # Должно распарсить 1000 за < 10 секунд
    assert len(tasks) == 1000
```

## Оптимизации производительности

### Оптимизация 1: Пакетные вставки в базу данных

**Текущее (MVP):**
```python
for task in tasks:
    insert_task(db, task)
```

**Оптимизированное:**
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

**Преимущество:** В 10 раз быстрее для 100+ задач

### Оптимизация 2: Параллельное получение деталей

**Текущее (MVP):**
```python
for task_id in new_task_ids:
    details = parse_task_details(driver, task_id)
```

**Оптимизированное:**
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

**Преимущество:** В 5 раз быстрее для получения деталей

### Оптимизация 3: Сохранение cookie сессии

**Текущее (MVP):** Аутентификация при каждом запуске

**Оптимизированное:**
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

**Преимущество:** Пропуск аутентификации, если сессия действительна (экономия 20-30с за запуск)

### Оптимизация 4: Инкрементальный парсинг

**Текущее (MVP):** Парсить все задачи каждый раз

**Оптимизированное:**
```python
def get_last_parsed_timestamp():
    cursor = db.cursor()
    cursor.execute("SELECT MAX(created_at) FROM tasks")
    return cursor.fetchone()[0] or datetime.min

def parse_only_new_tasks():
    # Сравнить поле time_passed для обнаружения новых задач
    last_timestamp = get_last_parsed_timestamp()
    # Парсить только задачи новее last_timestamp
```

**Преимущество:** Сокращение времени парсинга при частых запусках

## Инструменты отладки

### Инструмент 1: Скриншот при ошибке

```python
def take_debug_screenshot(driver, prefix="error"):
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    driver.save_screenshot(filename)
    logger.info(f"Debug screenshot saved: {filename}")
```

### Инструмент 2: Дамп HTML при сбое парсинга

```python
def dump_html_on_error(html, task_id=None):
    filename = f"html_dump_{task_id or 'unknown'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info(f"HTML dumped for debugging: {filename}")
```

### Инструмент 3: Режим пробного запуска

```python
if config['debug']['dry_run']:
    logger.info("DRY RUN MODE: Not inserting into database")
    for task in tasks:
        logger.info(f"Would insert: {task}")
else:
    insert_task(db, task)
```

### Инструмент 4: Подробное логирование

```python
if config['debug']['verbose']:
    logger.setLevel(logging.DEBUG)
    logger.debug(f"Raw HTML: {driver.page_source[:500]}")
    logger.debug(f"Current URL: {driver.current_url}")
    logger.debug(f"Cookies: {driver.get_cookies()}")
```

## Чеклист обслуживания

### Еженедельные проверки
- [ ] Просмотреть логи ошибок на наличие новых паттернов
- [ ] Проверить, что успешность решения капчи > 90%
- [ ] Проверить рост размера базы данных (должен быть линейным)
- [ ] Проверить, что задачи cron выполняются по расписанию

### Ежемесячные проверки
- [ ] Обновить Selenium WebDriver, если Chrome обновился
- [ ] Проверить баланс anti-captcha
- [ ] Вручную ротировать файлы логов при необходимости
- [ ] Резервная копия базы данных (`mysqldump gogetlinks > backup.sql`)

### Ежеквартальные проверки
- [ ] Проверить изменения в макете gogetlinks.net (запустить в режиме отладки)
- [ ] Обновить зависимости Python (`pip list --outdated`)
- [ ] Просмотреть и обновить CSS-селекторы при необходимости
- [ ] Аудит безопасности (права на файл конфигурации, привилегии пользователя)

---

**Версия уточнения:** 1.0
**Цель покрытия тестами:** 80%
**Бенчмарки производительности:** См. Architecture.md
