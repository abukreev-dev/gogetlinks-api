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

### Шаг 1: Изучить документацию

```bash
# Распаковать docs
unzip gogetlinks-parser-docs.zip

# Прочитать в следующем порядке:
1. Final_Summary.md — общий обзор
2. PRD.md — требования и фичи
3. Architecture.md — технический стек
4. Pseudocode.md — алгоритмы
```

### Шаг 2: Установить Claude Code toolkit

```bash
# Распаковать toolkit
unzip gogetlinks-parser-cc-toolkit.zip

# Скопировать в корень проекта
cd /path/to/gogetlinks-parser
cp -r gogetlinks-parser-cc-toolkit/.claude ./
cp gogetlinks-parser-cc-toolkit/CLAUDE.md ./
```

### Шаг 3: Начать разработку

**В Claude Code:**
```
@planner plan authentication module
```

**Перед коммитом:**
```
@code-reviewer review gogetlinks_parser.py
```

**Запустить тесты:**
```
/test parser
```

---

## 📋 Roadmap

| Фаза | Функции | Сроки |
|-------|----------|----------|
| **MVP (v1.0)** | Auth + parsing + MySQL | Неделя 1-2 |
| **v1.1** | Detail parsing + session persist | Неделя 3-4 |
| **v2.0** | Web dashboard + notifications | Месяц 2+ |

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

**Перед коммитом:**
1. Запустить /test
2. Использовать @code-reviewer
3. Следовать git-workflow rules

---

## ❓ Часто задаваемые вопросы

**В: Где начать?**
О: Прочитать Final_Summary.md → PRD.md → Architecture.md

**В: Как использовать агентов?**
О: `@planner plan [feature]` или `@code-reviewer review [file]`

**В: Что делать если сайт поменял вёрстку?**
О: См. Refinement.md → Edge Cases → "Site layout changes"

**В: Как деплоить?**
О: См. Completion.md → Deployment Steps

---

## 🎯 Метрики успеха

| Метрика | Целевое значение |
|--------|--------|
| Успешность парсинга | >95% |
| Время цикла | 2-3 мин |
| Успешность решения капчи | >90% |
| Нулевые дубликаты | 100% |

---

## 🔗 Ресурсы

- **Anti-Captcha API:** https://anti-captcha.com/apidoc
- **Selenium Docs:** https://selenium.dev/documentation
- **MySQL Docs:** https://dev.mysql.com/doc/

---

**Статус:** ✅ ГОТОВО К РАЗРАБОТКЕ

Вся документация готова. Все инструменты созданы. Можно начинать разработку!

---

*Создано: 2026-02-05*
*Версия: 1.0*
