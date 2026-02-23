# Gogetlinks Parser - Краткое руководство по началу работы

## 📦 Вы получили 2 архива

### 1️⃣ gogetlinks-parser-docs.zip (44 KB)
**Полная SPARC документация (9 файлов):**
- PRD.md — Product Requirements
- Solution_Strategy.md — Анализ проблемы
- Specification.md — Детальные требования
- Pseudocode.md — Алгоритмы
- Architecture.md — Системный дизайн
- Refinement.md — Edge cases + тесты
- Completion.md — Deployment план
- Research_Findings.md — Research синтез
- Final_Summary.md — Executive summary

**Кому:** Для изучения перед разработкой

### 2️⃣ gogetlinks-parser-cc-toolkit.zip (14 KB)
**Claude Code инструменты (11 файлов):**
- CLAUDE.md — AI integration guide
- 2 agents (planner, code-reviewer)
- 2 skills (project-context, coding-standards)
- 1 command (/test)
- 4 rules (git-workflow, security, testing, coding-style)

**Кому:** Для использования в Claude Code при разработке

---

## 🚀 Начало работы

### Вариант А: Автоматическая установка (Рекомендуется)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/abukreev-dev/gogetlinks-api.git
cd gogetlinks-api

# 2. Установить всё автоматически
make install-dev

# 3. Настроить конфигурацию
make setup-config
# Затем отредактировать config.ini своими credentials

# 4. Создать базу данных
make setup-db

# 5. Запустить тесты
make test

# 6. Готово! Начинайте разработку
make run
```

### Вариант Б: Ручная установка

#### Шаг 1: Установка зависимостей

```bash
# Клонировать репозиторий
git clone https://github.com/abukreev-dev/gogetlinks-api.git
cd gogetlinks-api

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Для разработки также установить:
pip install pytest pytest-cov black flake8 mypy
```

#### Шаг 2: Настройка конфигурации

```bash
# Скопировать шаблон
cp config.ini.example config.ini

# Установить права доступа
chmod 600 config.ini

# Отредактировать config.ini
nano config.ini
```

**Заполнить в config.ini:**
- `[gogetlinks]` - логин и пароль от gogetlinks.net
- `[anticaptcha]` - API ключ от anti-captcha.com
- `[database]` - настройки MySQL
- `[telegram]` - (опционально) bot_token, chat_id, mention для уведомлений

#### Шаг 3: Инициализация базы данных

```bash
# Создать базу данных
mysql -u root -p < schema.sql

# Или через make
make setup-db
```

#### Шаг 4: Проверка установки

```bash
# Запустить тесты
pytest tests/

# Запустить парсер
python gogetlinks_parser.py
```

---

## 🛠️ Makefile команды

Проект включает **Makefile** с 25+ командами для автоматизации разработки:

### Установка и настройка
```bash
make install          # Установить зависимости
make install-dev      # Установить dev зависимости (pytest, black, etc)
make setup-config     # Создать config.ini из шаблона
make setup-db         # Инициализировать базу данных
```

### Разработка
```bash
make run              # Запустить парсер
make run-debug        # Запустить в debug режиме с полным логом
make test             # Запустить тесты
make test-cov         # Запустить тесты с покрытием (HTML отчёт)
make lint             # Проверить код линтером (flake8)
make format           # Отформатировать код (black)
make type-check       # Проверить типы (mypy)
```

### Мониторинг
```bash
make logs             # Показать последние 50 строк логов
make logs-errors      # Показать только ошибки из логов
make db-tasks         # Показать новые задачи из БД
```

### Утилиты
```bash
make clean            # Очистить временные файлы (__pycache__, .pyc)
make clean-all        # Полная очистка (включая venv)
make deploy-check     # Проверить готовность к деплою
make backup-db        # Создать backup базы данных
make help             # Показать все доступные команды
```

### Пример workflow разработки

```bash
# Утро: начало работы
make install-dev      # Первая установка (один раз)
make test             # Проверить что всё работает

# Разработка функции
make run-debug        # Тестовый запуск
make logs             # Проверить логи
make db-tasks         # Проверить результаты в БД

# Перед коммитом
make format           # Отформатировать код
make lint             # Проверить код
make test-cov         # Запустить тесты с покрытием

# Готово к деплою
make deploy-check     # Финальная проверка
```

---

## 📚 Изучение документации

### Шаг 1: Быстрый обзор

```bash
# Прочитать в следующем порядке:
1. README.md — общее описание проекта
2. Final_Summary.md — executive summary
3. PRD.md — требования и функции
4. Architecture.md — технический стек и дизайн
```

### Шаг 2: Детальное изучение

```bash
# Для разработки:
- Pseudocode.md — алгоритмы и поток данных
- Specification.md — детальные требования
- Refinement.md — edge cases и тестирование

# Для деплоя:
- Completion.md — план развёртывания
- schema.sql — схема базы данных
```

---

## 🤖 Claude Code интеграция

### Установка Claude Code toolkit

```bash
# Если у вас есть архив cc-toolkit
unzip gogetlinks-parser-cc-toolkit.zip

# Скопировать в проект
cd gogetlinks-api
cp -r /path/to/cc-toolkit/.claude ./
cp /path/to/cc-toolkit/CLAUDE.md ./
```

### Использование в Claude Code

**Планирование:**
```
@planner plan authentication module
```

**Code review:**
```
@code-reviewer review gogetlinks_parser.py
```

**Запуск тестов:**
```
/test parser
```

---

## 📋 Roadmap

| Фаза | Функции | Статус |
|-------|----------|----------|
| **MVP (v1.0)** | Auth + parsing + MySQL | ✅ Готово |
| **v1.1** | Detail parsing + Telegram-уведомления | ✅ Готово |
| **v1.2** | Cookie session persistence | ✅ Готово |
| **v1.3** | Пагинация + фильтрация | 🔄 Планируется |
| **v2.0** | Web dashboard | 🔄 Планируется |

---

## 🛠️ Технологический стек

- Python 3.8+
- Selenium 4+ (headless Chrome)
- MySQL 8.0+
- Anti-Captcha.com API
- Cron (планировщик)

---

## 📚 Справочник ключевых документов

**Перед началом фичи:**
1. Проверить Specification.md для требований
2. Проверить Pseudocode.md для алгоритмов
3. Использовать @planner для декомпозиции

**Во время разработки:**
1. Обращаться к Architecture.md для технических решений
2. Использовать project-context skill для знаний о домене
3. Следовать coding-standards skill
4. Использовать `make` команды для автоматизации

**Перед коммитом:**
1. Запустить `make format` (форматирование)
2. Запустить `make lint` (проверка кода)
3. Запустить `make test-cov` (тесты с покрытием)
4. Использовать @code-reviewer
5. Следовать git-workflow rules

---

## ❓ Часто задаваемые вопросы

**В: Где начать?**
О: Прочитать README.md → Final_Summary.md → PRD.md → Architecture.md

**В: Как использовать агентов?**
О: `@planner plan [feature]` или `@code-reviewer review [file]`

**В: Что делать если сайт поменял вёрстку?**
О: См. Refinement.md → Edge Cases → "Site layout changes"

**В: Как деплоить?**
О: Запустить `make deploy-check`, затем см. Completion.md → Deployment Steps

**В: Какие команды доступны?**
О: Запустить `make help` для полного списка

**В: Как проверить что всё настроено правильно?**
О: Запустить `make deploy-check` - покажет статус всех компонентов

---

## 🎯 Метрики успеха

| Метрика | Целевое значение |
|--------|--------|
| Успешность парсинга | >95% |
| Время цикла | 2-3 мин |
| Успешность решения капчи | >90% |
| Нулевые дубликаты | 100% |
| Покрытие тестами | >80% |

---

## 🔗 Ресурсы

- **Anti-Captcha API:** https://anti-captcha.com/apidoc
- **Selenium Docs:** https://selenium.dev/documentation
- **MySQL Docs:** https://dev.mysql.com/doc/
- **Pytest Docs:** https://docs.pytest.org

---

## 🎬 Быстрый старт (TL;DR)

```bash
git clone https://github.com/abukreev-dev/gogetlinks-api.git
cd gogetlinks-api
make install-dev
make setup-config  # Затем отредактировать config.ini
make setup-db
make test
make run
```

---

**Статус:** ✅ v1.2 — cookie сессии + парсинг деталей + Telegram

---

*Создано: 2026-02-05*
*Версия: 1.3*
*Обновлено: 2026-02-23 — v1.2 с cookie session persistence*
