# Gogetlinks Task Parser

Автоматизированный парсер биржи gogetlinks.net. Скрипт работает по cron, собирает новые задачи (`/webTask`) и метрики по сайтам (`/mySites`), решает reCAPTCHA через anti-captcha.com и сохраняет данные в MySQL.

## 🚀 Быстрый старт

### Требования
- Python 3.8+
- MySQL 8.0+
- Chrome/Chromium browser
- Ubuntu 20.04+ или аналогичный Linux (VPS)

### Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/abukreev-dev/gogetlinks-api.git
cd gogetlinks-api

# 2. Установить зависимости (создаёт venv, ставит пакеты, создаёт logs/)
make install

# 3. Настроить конфигурацию
make setup-config   # Создаёт config.ini из шаблона (chmod 600)
nano config.ini     # Заполнить credentials

# 4. Инициализировать базу данных
make setup-db

# 5. Проверить готовность
make deploy-check

# 6. Запустить парсер
make run
```

### Настройка cron

```bash
make setup-cron  # Покажет готовые строки для crontab
crontab -e
# Добавить:
CRON_TZ=Europe/Moscow
0 * * * * cd ~/gogetlinks-api && venv/bin/python gogetlinks_parser.py --skip-sites >> /var/log/gogetlinks_cron.log 2>&1
15 7 * * * cd ~/gogetlinks-api && venv/bin/python gogetlinks_parser.py --skip-tasks >> /var/log/gogetlinks_cron.log 2>&1
```

## 📚 Документация

Полная документация проекта доступна в каталоге [`docs/`](docs/) на двух языках:

### Основные документы (русский)
- 📖 [**Быстрый старт**](docs/QUICK_START_GUIDE_RU.md) - Краткое руководство по началу работы
- 📋 [**PRD**](docs/PRD_RU.md) - Требования к продукту и функции
- 🏗️ [**Архитектура**](docs/Architecture_RU.md) - Системный дизайн и технический стек
- 📝 [**Спецификация**](docs/Specification_RU.md) - Детальные требования и user stories
- 💻 [**Псевдокод**](docs/Pseudocode_RU.md) - Алгоритмы и поток данных
- 🔬 [**Исследование**](docs/Research_Findings_RU.md) - Результаты технического исследования
- 🎯 [**Стратегия**](docs/Solution_Strategy_RU.md) - Анализ проблемы и выбор решения
- 🛠️ [**Доработка**](docs/Refinement_RU.md) - Edge cases и стратегия тестирования
- 🚢 [**Развёртывание**](docs/Completion_RU.md) - План деплоя и мониторинга
- 📊 [**Итоговое резюме**](docs/Final_Summary_RU.md) - Executive summary

### Claude Code интеграция
- 🤖 [**CLAUDE.md**](cc-toolkit/CLAUDE_RU.md) - Руководство по AI-assisted разработке

## 🛠️ Технологический стек

- **Python 3.8+** - Основной язык разработки
- **Selenium 4+** - Browser automation (headless Chrome)
- **MySQL 8.0+** - База данных
- **Anti-Captcha.com** - Решение reCAPTCHA
- **Cron** - Планировщик задач

## ⚙️ Конфигурация

Файл `config.ini` (пример в `config.ini.example`):

```ini
[gogetlinks]
username = your_email@example.com
password = your_password

[anticaptcha]
api_key = your_anticaptcha_api_key

[database]
host = localhost
port = 3306
database = ddl
user = gogetlinks_parser
password = db_password

[telegram]
enabled = false
bot_token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
chat_id = -100123456789
# Упоминания применяются только к уведомлениям о новых задачах (/webTask)
mention = @user1 @user2

[output]
print_to_console = true

[logging]
log_level = INFO
log_file = logs/gogetlinks_parser.log
```

## 🎯 Основные функции

### MVP (v1.0)
- ✅ Автоматическая авторизация с решением капчи
- ✅ Парсинг списка новых задач
- ✅ Хранение в MySQL с дедупликацией
- ✅ Структурированное логирование
- ✅ Запуск по расписанию cron

### v1.1
- ✅ Парсинг детальной информации о задачах (описание, URL, требования, анкор)
- ✅ Telegram-уведомления о новых задачах (цена в ₽, тип задачи, домены)
- ✅ Настраиваемые теги сотрудников в уведомлениях (`mention`)
- ✅ Реальные тесты с assertions (58 тестов)

### v1.2 (текущая)
- ✅ Сохранение cookie сессии для пропуска повторной авторизации
- ✅ 64 теста с assertions

### v1.2.1
- ✅ Фикс парсинга цены: заглавная кириллическая `Р` (U+0420) теперь корректно удаляется (`re.IGNORECASE`)
- ✅ Пропуск AJAX-модалок для задач, уже имеющих `description` в БД (~10× быстрее при повторных запусках)
- ✅ 72 теста с assertions

### v1.3 (текущая)
- ✅ Переезд на `ddl.ggl_tasks` (без создания БД в `schema.sql`)
- ✅ Парсинг `/mySites` и обновление метрик в `ddl.domain`
- ✅ Обход всех страниц `/mySites` (а не только первой)
- ✅ Telegram-уведомления о смене `ggl_status` (без `mention`)
- ✅ Fallback авторизации: direct -> proxy `127.0.0.1:3128` при anti-bot блоке
- ✅ Разделённые режимы запуска: `--skip-sites` и `--skip-tasks`
- ✅ 77 тестов с assertions

### Планируемые (v1.4)
- 🔄 Фильтрация задач по критериям
- 🔄 Web панель управления (Flask)

## 📊 Схема базы данных

```sql
CREATE TABLE ddl.ggl_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT UNIQUE NOT NULL,
    title VARCHAR(500),
    description TEXT,
    price DECIMAL(10,2),
    deadline DATETIME,
    customer VARCHAR(255),
    customer_url VARCHAR(500),
    domain VARCHAR(255),
    url VARCHAR(500),
    requirements TEXT,
    contacts TEXT,
    external_links INT,
    time_passed VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_new BOOLEAN DEFAULT 1,

    INDEX idx_task_id (task_id),
    INDEX idx_created_at (created_at),
    INDEX idx_is_new (is_new)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

Также скрипт обновляет существующие записи в `ddl.domain` по полю `host`:
`ggl_status`, `ggl_description`, `ggl_traffic`, `ggl_sqi`, `ggl_cf_tf`, `ggl_trust`, `ggl_update_at`.

## 🛠️ Makefile команды

Проект использует Makefile для автоматизации всех рутинных операций. Полный список команд: `make help`

### Установка и настройка

| Команда | Описание |
|---------|----------|
| `make install` | Создать venv, установить зависимости, создать `logs/` |
| `make install-dev` | + dev-зависимости (pytest, black, flake8, mypy) |
| `make setup-config` | Создать `config.ini` из шаблона (chmod 600) |
| `make setup-db` | Инициализировать MySQL из `schema.sql` |
| `make all` | Полная установка: install + setup-config + setup-db + test |

### Запуск

| Команда | Описание |
|---------|----------|
| `make run` | Запустить парсер |
| `make run-debug` | Запустить с выводом в консоль и `debug.log` |

### Тестирование и качество кода

| Команда | Описание |
|---------|----------|
| `make test` | Запустить все тесты |
| `make test-cov` | Тесты + отчёт о покрытии |
| `make lint` | Проверка flake8 |
| `make format` | Форматирование black |
| `make type-check` | Проверка типов mypy |

### Мониторинг и обслуживание

| Команда | Описание |
|---------|----------|
| `make logs` | Последние 50 строк лога |
| `make logs-errors` | Только ошибки из лога |
| `make db-tasks` | Новые задачи из БД (последние 10) |
| `make deploy-check` | Проверить готовность к деплою (Python, Chrome, MySQL, файлы) |
| `make setup-cron` | Показать две cron-задачи (hourly tasks + daily mySites) |
| `make backup-db` | Создать timestamped дамп БД |
| `make clean` | Очистить кеши (__pycache__, .pytest_cache и т.д.) |
| `make clean-all` | Полная очистка включая venv |

## 🧪 Тестирование

```bash
make test           # Все тесты
make test-cov       # Тесты + покрытие

# Конкретный тест (через venv напрямую)
. venv/bin/activate && pytest tests/test_parser.py::test_price_parsing
```

## 🔍 Мониторинг

```bash
make logs           # Последние 50 строк лога
make logs-errors    # Только ошибки
make db-tasks       # Новые задачи в БД
```

## 🐛 Устранение неполадок

| Проблема | Решение |
|----------|---------|
| "Authentication failed" | Проверить учётные данные в config.ini |
| "Captcha solving failed" | Проверить баланс anti-captcha (>$5) |
| "Database error" | Проверить MySQL: `sudo systemctl status mysql` |
| Пустой список задач | Возможно изменился макет сайта, обновить селекторы |
| Перекидывает на `/403.php` | Настроить локальный proxy `127.0.0.1:3128` (fallback используется автоматически) |
| Cron не запускается | Проверить `crontab -l` и логи `/var/log/gogetlinks_cron.log` |

## 📈 Метрики производительности

| Метрика | Целевое значение |
|---------|------------------|
| Успешность парсинга | >95% |
| Время цикла | 2-3 минуты |
| Успешность решения капчи | >90% |
| Дубликаты в БД | 0% |

## 🤝 Вклад в проект

Contributions приветствуются! Пожалуйста:

1. Форкните репозиторий
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Закоммитьте изменения (`git commit -m 'feat: add amazing feature'`)
4. Запушьте в branch (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

## 📄 Лицензия

Этот проект является приватным и предназначен для личного использования.

## 🔗 Полезные ссылки

- [Anti-Captcha API Documentation](https://anti-captcha.com/apidoc)
- [Selenium Documentation](https://www.selenium.dev/documentation/)
- [MySQL Documentation](https://dev.mysql.com/doc/)

## 📧 Контакты

При возникновении вопросов создайте Issue в репозитории.

---

**Статус:** ✅ v1.3 — mySites + статус-уведомления + split-schedule + 77 тестов
**Версия:** 1.3
**Последнее обновление:** 2026-03-05
