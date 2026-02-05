# Gogetlinks Task Parser - Руководство по Claude Code

## Обзор проекта

**Gogetlinks Task Parser** — автоматизированный парсер заданий для фриланс-платформы gogetlinks.net. Запускается ежечасно через cron, выполняет аутентификацию (с использованием anti-captcha), парсит списки задач, сохраняет в MySQL с дедупликацией.

**Статус:** MVP готов к разработке
**Язык:** Python 3.8+
**Развёртывание:** VPS (без Docker)

## Быстрый старт

```bash
# Установка
git clone <repo>
cd gogetlinks-parser
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Настройка
cp config.ini.example config.ini
nano config.ini  # Заполнить учётные данные
chmod 600 config.ini

# Инициализация БД
mysql -u root -p < schema.sql

# Запуск
python gogetlinks_parser.py

# Настройка cron
crontab -e
# Добавить: 0 * * * * cd ~/gogetlinks-parser && venv/bin/python gogetlinks_parser.py
```

## Архитектурная сводка

```
Cron → Python Script
       ├─ Selenium (headless Chrome)
       │  └─ gogetlinks.net
       ├─ Anti-Captcha API (решение капчи)
       └─ MySQL (хранение задач)
```

**Ключевые компоненты:**
- **Auth Module:** Вход + решение капчи (anti-captcha.com)
- **Parser Module:** Извлечение HTML (список + детальные виды)
- **Database Module:** MySQL CRUD с дедупликацией через UNIQUE INDEX
- **Config Module:** Парсинг INI + валидация
- **Logging:** Структурированное логирование в файл

## Ключевые файлы

| Файл | Назначение | Строк |
|------|---------|-------|
| `gogetlinks_parser.py` | Основной скрипт (оркестратор) | ~500 |
| `config.ini` | Учётные данные (в gitignore) | ~20 |
| `schema.sql` | MySQL DDL | ~30 |
| `requirements.txt` | Python зависимости | 2 |
| `README.md` | Пользовательская документация | ~100 |

## Типовые задачи

### Добавить новую функцию
1. Прочитать `Specification.md` для требований
2. Проверить `Pseudocode.md` для потока данных
3. Реализовать в модульной функции
4. Добавить unit тесты (pytest)
5. Обновить `CHANGELOG.md`

### Исправить баг
1. Проверить логи: `tail -f gogetlinks_parser.log`
2. Сделать скриншот при ошибке (если Selenium)
3. Дамп HTML при сбоях парсинга
4. Исправить + добавить регрессионный тест
5. Проверить ручным запуском

### Обновить селекторы (если сайт изменился)
1. Инспектировать HTML gogetlinks.net
2. Обновить CSS селекторы в модуле парсера
3. Протестировать в dry run режиме
4. Задокументировать в `CHANGELOG.md`

## Практики разработки

### Стратегия параллельного выполнения
- Использовать инструмент `Task` для независимых подзадач (например, парсинг нескольких детальных страниц)
- Запускать тесты, линтинг, проверку типов параллельно
- Для сложных функций: запускать специализированных агентов

**Пример:**
```python
# Параллельное получение деталей (будущая оптимизация)
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(parse_details, id) for id in task_ids]
    results = [f.result() for f in futures]
```

### Git рабочий процесс
**Конвенции коммитов:**
- `feat(scope): description` — новая функциональность
- `fix(scope): description` — исправление бага
- `refactor(scope): description` — рефакторинг
- `test(scope): description` — тесты
- `docs(scope): description` — документация
- `chore(scope): description` — инфраструктура

**Правило:** 1 логическое изменение = 1 коммит

**Пример:**
```bash
git commit -m "feat(parser): add detail page extraction"
git commit -m "test(parser): add unit tests for detail parsing"
```

### Подсказки по Swarm агентам
**Когда использовать несколько агентов:**
- **Большая функция:** `@planner` для декомпозиции + 2-3 агента реализации параллельно
- **Рефакторинг:** `@code-reviewer` + агенты рефакторинга
- **Исправление бага:** Один агент (параллелизм не нужен)

**Координация:**
- Использовать инструмент `Task` для параллельного выполнения
- Делиться контекстом через запись в файлы (например, `feature_plan.md`)
- Финальное слияние координирующим агентом

## Соглашения

### Стиль кода
- Соответствие **PEP 8** (проверяется форматером `black`)
- **Аннотации типов** для сигнатур функций
- **Docstrings:** стиль Google
```python
def parse_task(row: WebElement) -> Task:
    """Извлечь данные задачи из HTML строки.

    Args:
        row: Selenium WebElement представляющий строку задачи

    Returns:
        Объект Task с извлечёнными полями

    Raises:
        ValueError: Если формат строки недействителен
    """
```

### Обработка ошибок
- **Специфичные исключения** вместо голого `Exception`
- **Контекст в логах:** Включать task_id, URL, операцию
- **Коды выхода:** 0=успех, 1=auth, 2=captcha, 3=config, 4=db, 5=webdriver, 99=неожиданное

### Безопасность
- **Никогда не логировать** пароли, API ключи, токены
- **Маскировать чувствительные данные:** `user***@example.com`
- **Права на файлы:** `config.ini` должен быть `chmod 600`

## Тестирование

### Запуск тестов
```bash
# Все тесты
pytest tests/

# Конкретный тест
pytest tests/test_parser.py::test_price_parsing

# С покрытием
pytest --cov=gogetlinks_parser tests/
```

### Структура тестов
```
tests/
├── test_auth.py         # Тесты аутентификации
├── test_parser.py       # Тесты парсинга
├── test_database.py     # Тесты базы данных
└── conftest.py          # Фикстуры
```

### Требования к покрытию
- **Минимум:** 80% покрытие кода
- **Критические пути:** 100% (auth, parsing, db insert)

## Развёртывание

### Ручное развёртывание
```bash
# 1. Клонировать на VPS
ssh user@vps
cd ~
git clone <repo>

# 2. Настройка (см. Быстрый старт)

# 3. Тестовый запуск
python gogetlinks_parser.py

# 4. Настройка cron
crontab -e
```

### Мониторинг
```bash
# Проверить статус последнего запуска
tail -n 50 gogetlinks_parser.log | grep "Exit code"

# Подсчитать ошибки (последние 24ч)
grep -c "ERROR" gogetlinks_parser.log | tail -n 24

# Посмотреть новые задачи в БД
mysql -u gogetlinks_parser -p -e "SELECT * FROM gogetlinks.tasks WHERE is_new=1 ORDER BY created_at DESC LIMIT 10;"
```

## Устранение неполадок

| Проблема | Решение |
|-------|----------|
| "Authentication failed" | Проверить учётные данные в config.ini, проверить баланс anti-captcha |
| "Captcha solving failed" | Проверить API ключ anti-captcha, проверить баланс >$5 |
| "Database error" | Проверить сервис MySQL: `sudo systemctl status mysql` |
| Парсер возвращает пустой список | Проверить, изменился ли макет сайта (инспектировать HTML), обновить селекторы |
| Cron не запускается | Проверить crontab: `crontab -l`, проверить логи: `/var/log/gogetlinks_cron.log` |

## Бенчмарки производительности

| Метрика | Ожидаемое | Фактическое |
|--------|----------|--------|
| Время авторизации | 20-30с | - |
| Парсинг 100 задач | 60с | - |
| Парсинг 10 деталей | 30с | - |
| Полный цикл | 2-3 мин | - |

## Ресурсы

- **Документация:** каталог `/docs/` (SPARC файлы)
- **Отслеживание проблем:** GitHub Issues
- **API документация:** Anti-Captcha: https://anti-captcha.com/apidoc
- **Selenium документация:** https://www.selenium.dev/documentation/

## Будущие улучшения

### v1.1 (Неделя 3-4)
- Парсинг деталей (описание, требования, контакты)
- Сохранение cookie сессии
- Логика повтора с экспоненциальной задержкой

### v2.0 (Месяц 2+)
- Web панель управления (Flask)
- Email/Telegram уведомления
- Движок фильтрации задач

### v3.0 (Месяц 6+)
- Docker + развёртывание Coolify
- Поддержка нескольких пользователей
- API для интеграций

---

**Версия документа:** 1.0
**Последнее обновление:** 2026-02-05
**По вопросам:** См. README.md или GitHub Issues
