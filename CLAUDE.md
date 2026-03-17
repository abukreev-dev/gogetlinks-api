# CLAUDE.md

Пиши на русском языке

## Правила MySQL через SSH
При выполнении SQL через ssh ddl использовать формат:
ssh ddl 'mysql ddl -N -e "SQL запрос здесь"'
Внешние кавычки одинарные, внутренние двойные.

## Preferences
- Не выводить diff при редактировании файлов
- Показывать только название файла и количество изменённых строк
- Не объединять команды через && в одну строку
- Каждую команду выполнять отдельно

## Conventions
- **Formatting**: Black, 88 chars, 4 spaces. Type hints. Google-style docstrings.
- **Commits**: `type(scope): description` — types: feat, fix, refactor, test, docs, chore, style, perf
- **Security**: Never log credentials — use `mask_email()`. Parameterized SQL only (`%s`). `config.ini` gitignored (chmod 600).
- **Testing**: pytest, AAA pattern, >=80% coverage.

## Docs (читать по необходимости, не грузить всегда)
- `docs/architecture.md` — архитектура, команды make, gotchas
- `docs/rules/coding-style.md` — стиль кода
- `docs/rules/git-workflow.md` — git workflow
- `docs/rules/testing.md` — правила тестирования
- `.claude/rules/security.md` — безопасность (грузится автоматически)

## Окружения

### Локальная разработка
- Все изменения кода — только локально
- Деплой — только через git push → GitHub → проект на сервере я обновляю вручную

### Сервер (ТОЛЬКО ЧТЕНИЕ)
- Доступ: `ssh ddl` (алиас в ~/.ssh/config)
- Можно: смотреть логи, читать БД (SELECT), проверять статус процессов
- НЕЛЬЗЯ: изменять файлы, редактировать конфиги, перезапускать процессы,
  устанавливать пакеты, писать в БД, удалять что-либо
Правило: если задача требует изменений на сервере — делай локально и деплой через git.
Если нужны изменения на сервере - пиши что нужно сделать пошагово вручную.
