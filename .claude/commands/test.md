# Test Command

Команда для запуска тестов.

## Использование

```
/test                  # Запустить все тесты
/test parser           # Запустить тесты парсера
/test auth             # Запустить тесты аутентификации
/test database         # Запустить тесты БД
/test integration      # Запустить интеграционные тесты
/test coverage         # Запустить тесты с покрытием
```

## Что делает команда

1. Активирует виртуальное окружение (если нужно)
2. Запускает pytest с соответствующими параметрами
3. Показывает результаты тестов
4. Для coverage - генерирует HTML отчёт

## Эквивалентные make команды

```bash
/test           → make test
/test coverage  → make test-cov
```

## Примеры вывода

### Успешный запуск
```
============================= test session starts ==============================
tests/test_parser.py::TestPriceParser::test_parse_price_robust PASSED    [ 33%]
tests/test_parser.py::TestTaskIdExtraction::test_extract_task_id_valid PASSED [ 66%]
tests/test_auth.py::TestAuthentication::test_is_authenticated_markup PASSED [100%]

============================== 3 passed in 0.42s ===============================
```

### С покрытием
```
Name                    Stmts   Miss  Cover
-------------------------------------------
gogetlinks_parser.py      250     25    90%
-------------------------------------------
TOTAL                     250     25    90%
```

## Параметры

- `--verbose` или `-v`: Детальный вывод
- `--coverage`: Генерировать отчёт о покрытии
- `--markers`: Показать доступные маркеры (slow, integration, etc.)
