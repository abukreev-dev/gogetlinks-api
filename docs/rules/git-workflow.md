# Git Workflow Rules

Правила работы с git для проекта.

## Commit Messages

### Формат
```
type(scope): description

[optional body]

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### Типы коммитов

- `feat` - новая функциональность
- `fix` - исправление бага
- `refactor` - рефакторинг без изменения поведения
- `test` - добавление или изменение тестов
- `docs` - изменения в документации
- `chore` - инфраструктурные изменения (Makefile, .gitignore, etc.)
- `style` - форматирование кода (без изменения логики)
- `perf` - улучшение производительности

### Примеры

```bash
feat(parser): add detail page extraction
fix(auth): handle captcha timeout correctly
test(parser): add price parsing edge cases
docs(readme): update installation steps
refactor(database): extract connection logic to separate function
chore(makefile): add test-cov command
```

## Branch Strategy

### Main Branch
- `main` - production-ready код
- Все коммиты должны проходить через PR (кроме hotfix)
- Требуются passing tests

### Feature Branches
```bash
# Создание feature branch
git checkout -b feat/detail-page-parsing

# Работа над фичей
git add .
git commit -m "feat(parser): add detail page extraction"

# Push и создание PR
git push -u origin feat/detail-page-parsing
gh pr create --title "Add detail page parsing" --body "..."
```

### Hotfix Branches
```bash
git checkout -b hotfix/captcha-timeout
git commit -m "fix(auth): increase captcha timeout to 120s"
git push -u origin hotfix/captcha-timeout
```

## Правила

### 1. Атомарные коммиты
- Один коммит = одно логическое изменение
- НЕ смешивать рефакторинг с новой функциональностью

### 2. Тестирование перед коммитом
```bash
# Всегда запускать тесты
make test

# Проверить покрытие
make test-cov
```

### 3. Commit Before Push
```bash
# ПЛОХО - push без коммита
git push

# ХОРОШО - сначала коммит, потом push
git add .
git commit -m "feat(parser): add new feature"
git push
```

### 4. Rebase vs Merge
- Используйте `git pull --rebase` для обновления локальной ветки
- Squash commits перед мержем в main (через GitHub UI)

### 5. Не коммитить
- `config.ini` (только config.ini.example)
- `*.log` файлы
- `session_cookies.pkl`
- `__pycache__/`, `*.pyc`
- `.env` файлы

## Pull Requests

### Checklist
- [ ] Тесты проходят (`make test`)
- [ ] Покрытие >= 80% (`make test-cov`)
- [ ] Code review от maintainer
- [ ] Документация обновлена (если нужно)
- [ ] CHANGELOG.md обновлён

### PR Template
```markdown
## Summary
[Brief description of changes]

## Changes
- Added X
- Fixed Y
- Refactored Z

## Test plan
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Screenshots (if applicable)
[Add screenshots]
```

## Emergency Protocol

### Revert Last Commit
```bash
git revert HEAD
git push
```

### Fix Wrong Commit Message
```bash
# Если ещё не запушили
git commit --amend -m "fix(auth): correct commit message"

# Если уже запушили - НЕ использовать --force
# Вместо этого создать новый коммит
```

## Code Review Rules

### Reviewer Checklist
- [ ] Код соответствует coding standards
- [ ] Нет логирования паролей/API ключей
- [ ] Правильная обработка ошибок
- [ ] Тесты покрывают критические пути
- [ ] Нет SQL injection уязвимостей

### Author Response
- Отвечать на все комментарии
- Не удалять код без объяснения
- Обновлять PR после фикса
