# Project Context Skill

Навык понимания контекста проекта Gogetlinks Task Parser.

## Описание проекта

Автоматизированный парсер заданий с биржи фриланса gogetlinks.net.

## Ключевые компоненты

### 1. Authentication Module
- Вход на gogetlinks.net
- Решение reCAPTCHA через anti-captcha.com API
- Проверка валидности сессии

### 2. Parser Module
- Парсинг списка задач (list view)
- Парсинг деталей задачи (detail view)
- Обработка Windows-1251 → UTF-8

### 3. Database Module
- MySQL CRUD операции
- Дедупликация через UNIQUE INDEX
- Флаг is_new для отслеживания новых задач

### 4. Config Module
- INI файл с credentials
- Валидация конфигурации

### 5. Logging Module
- Структурированное логирование
- Exit codes для cron мониторинга

## Технологический стек

- Python 3.8+
- Selenium 4+ (headless Chrome)
- MySQL 8.0+
- Anti-Captcha.com API
- Cron (scheduler)

## Архитектурные принципы

1. **Простота** - Single script для MVP
2. **Надёжность** - Graceful error handling
3. **Безопасность** - Никогда не логировать credentials
4. **Производительность** - UNIQUE INDEX для дедупликации

## Важные URL

- Login: `https://gogetlinks.net/user/signIn`
- Task list: `https://gogetlinks.net/webTask/index`
- Task details: `https://gogetlinks.net/template/view_task.php?curr_id={id}`

## Exit Codes

- 0 = Success
- 1 = Authentication failed
- 2 = Captcha solving failed
- 3 = Config error
- 4 = Database error
- 5 = WebDriver error
- 99 = Unexpected error

## Основные метрики

- Parsing success rate: >95%
- Cycle time: 2-3 min
- Captcha success: >90%
- Zero duplicates: 100%
