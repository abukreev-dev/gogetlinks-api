# Gogetlinks Parser - Quick Start Guide

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

| Phase | Features | Timeline |
|-------|----------|----------|
| **MVP (v1.0)** | Auth + parsing + MySQL | Week 1-2 |
| **v1.1** | Detail parsing + session persist | Week 3-4 |
| **v2.0** | Web dashboard + notifications | Month 2+ |

---

## 🛠️ Tech Stack

- Python 3.8+
- Selenium 4+ (headless Chrome)
- MySQL 8.0+
- Anti-Captcha.com API
- Cron (scheduler)

---

## 📚 Key Documents Reference

**Перед началом фичи:**
1. Check Specification.md для requirements
2. Check Pseudocode.md для алгоритмов
3. Use @planner для декомпозиции

**Во время разработки:**
1. Refer to Architecture.md для tech decisions
2. Use project-context skill для domain knowledge
3. Follow coding-standards skill

**Перед коммитом:**
1. Run /test
2. Use @code-reviewer
3. Follow git-workflow rules

---

## ❓ FAQ

**Q: Где начать?**  
A: Прочитать Final_Summary.md → PRD.md → Architecture.md

**Q: Как использовать agents?**  
A: `@planner plan [feature]` или `@code-reviewer review [file]`

**Q: Что делать если сайт поменял вёрстку?**  
A: См. Refinement.md → Edge Cases → "Site layout changes"

**Q: Как деплоить?**  
A: См. Completion.md → Deployment Steps

---

## 🎯 Success Metrics

| Metric | Target |
|--------|--------|
| Parsing success | >95% |
| Cycle time | 2-3 min |
| Captcha success | >90% |
| Zero duplicates | 100% |

---

## 🔗 Resources

- **Anti-Captcha API:** https://anti-captcha.com/apidoc
- **Selenium Docs:** https://selenium.dev/documentation
- **MySQL Docs:** https://dev.mysql.com/doc/

---

**Status:** ✅ READY FOR VIBE CODING

Вся документация готова. Все инструменты созданы. Можно начинать разработку!

---

*Generated: 2026-02-05*  
*Version: 1.0*
