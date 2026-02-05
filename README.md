# Gogetlinks Task Parser

Автоматизированный парсер заданий с биржи фриланса gogetlinks.net. Система работает автономно по расписанию cron, извлекает данные о новых задачах через browser automation (Selenium), решает капчи через anti-captcha.com, и хранит данные в MySQL с автоматической дедупликацией.

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

# 2. Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить конфигурацию
cp config.ini.example config.ini
nano config.ini  # Заполнить credentials
chmod 600 config.ini

# 5. Инициализировать базу данных
mysql -u root -p < schema.sql

# 6. Запустить парсер
python gogetlinks_parser.py
```

### Настройка cron

```bash
crontab -e
# Добавить строку для запуска каждый час:
0 * * * * cd ~/gogetlinks-api && venv/bin/python gogetlinks_parser.py >> /var/log/gogetlinks_cron.log 2>&1
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
database = gogetlinks
user = gogetlinks_parser
password = db_password

[output]
print_tasks = false

[logging]
level = INFO
file = gogetlinks_parser.log
```

## 🎯 Основные функции

### MVP (v1.0)
- ✅ Автоматическая авторизация с решением капчи
- ✅ Парсинг списка новых задач
- ✅ Хранение в MySQL с дедупликацией
- ✅ Структурированное логирование
- ✅ Запуск по расписанию cron

### Планируемые (v1.1)
- 🔄 Парсинг детальной информации о задачах
- 🔄 Сохранение cookie сессии
- 🔄 Логика повторных попыток
- 🔄 Email/Telegram уведомления

## 📊 Схема базы данных

```sql
CREATE TABLE tasks (
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

## 🧪 Тестирование

```bash
# Запустить все тесты
pytest tests/

# Запустить с покрытием
pytest --cov=gogetlinks_parser tests/

# Конкретный тест
pytest tests/test_parser.py::test_price_parsing
```

## 🔍 Мониторинг

```bash
# Проверить последний запуск
tail -n 50 gogetlinks_parser.log | grep "Exit code"

# Подсчитать ошибки за последние 24 часа
grep -c "ERROR" gogetlinks_parser.log | tail -n 24

# Посмотреть новые задачи в БД
mysql -u gogetlinks_parser -p -e "SELECT * FROM gogetlinks.tasks WHERE is_new=1 ORDER BY created_at DESC LIMIT 10;"
```

## 🐛 Устранение неполадок

| Проблема | Решение |
|----------|---------|
| "Authentication failed" | Проверить учётные данные в config.ini |
| "Captcha solving failed" | Проверить баланс anti-captcha (>$5) |
| "Database error" | Проверить MySQL: `sudo systemctl status mysql` |
| Пустой список задач | Возможно изменился макет сайта, обновить селекторы |
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

**Статус:** ✅ MVP готов к разработке
**Версия:** 1.0
**Последнее обновление:** 2026-02-05
