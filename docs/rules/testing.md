# Testing Rules

Правила тестирования для проекта Gogetlinks Task Parser.

## Минимальные требования

### Coverage
- **Общее покрытие**: >= 80%
- **Критические модули**: 100%
  - Authentication
  - Parser (price, task_id extraction)
  - Database operations

### Test Types
- Unit tests (быстрые, изолированные)
- Integration tests (с реальной БД)
- End-to-end tests (полный цикл парсинга)

## Структура тестов

### Именование
```python
# test_<module>.py
test_auth.py        # Тесты аутентификации
test_parser.py      # Тесты парсера
test_database.py    # Тесты БД
test_integration.py # Интеграционные тесты

# Внутри файла
class TestPriceParser:
    def test_parse_price_valid_formats(self):
        """Test parsing valid price formats."""
        pass

    def test_parse_price_edge_cases(self):
        """Test edge cases like FREE, empty, etc."""
        pass
```

### Организация
```python
# tests/test_parser.py
import pytest
from decimal import Decimal
from gogetlinks_parser import parse_price, extract_task_id

class TestPriceParser:
    """Тесты парсинга цен."""

    @pytest.mark.parametrize("input_price,expected", [
        ("$123.45", Decimal("123.45")),
        ("123.45 руб", Decimal("123.45")),
        ("FREE", Decimal("0.00")),
        ("", Decimal("0.00")),
        ("N/A", Decimal("0.00")),
    ])
    def test_parse_price_robust(self, input_price, expected):
        """Test parsing various price formats."""
        assert parse_price(input_price) == expected
```

## Fixtures

### conftest.py
```python
# tests/conftest.py
import pytest
import mysql.connector
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

@pytest.fixture
def chrome_driver():
    """Selenium WebDriver fixture."""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')

    driver = webdriver.Chrome(options=options)
    yield driver
    driver.quit()

@pytest.fixture
def db_connection():
    """Database connection fixture."""
    conn = mysql.connector.connect(
        host='localhost',
        user='test_user',
        password='test_password',
        database='test_gogetlinks_db'
    )
    yield conn
    conn.close()

@pytest.fixture
def sample_task_row():
    """Sample HTML row for parsing."""
    return """
    <tr id="col_row_123">
        <td>Task Title</td>
        <td>$99.99</td>
        <td>Active</td>
    </tr>
    """
```

## Test Patterns

### AAA Pattern (Arrange-Act-Assert)
```python
def test_authentication_success(chrome_driver, valid_credentials):
    # Arrange
    username, password = valid_credentials
    auth = Authenticator(chrome_driver)

    # Act
    result = auth.authenticate(username, password)

    # Assert
    assert result is True
    assert auth.is_authenticated()
```

### Given-When-Then (для Integration tests)
```python
@pytest.mark.integration
def test_full_parsing_cycle(chrome_driver, db_connection):
    """Test complete parsing workflow.

    Given: Valid authentication
    When: Parser runs
    Then: Tasks are saved to database
    """
    # Given
    auth = Authenticator(chrome_driver)
    assert auth.authenticate(USERNAME, PASSWORD)

    # When
    parser = TaskParser(chrome_driver)
    tasks = parser.parse_task_list()

    # Then
    assert len(tasks) > 0
    db = TaskDatabase(db_connection)
    db.insert_tasks(tasks)

    saved_task = db.get_task(tasks[0].task_id)
    assert saved_task is not None
```

## Mocking

### Mock external APIs
```python
from unittest.mock import Mock, patch

def test_captcha_solving():
    """Test captcha solving with mocked API."""
    with patch('requests.post') as mock_post:
        # Arrange
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'ready',
            'solution': {'gRecaptchaResponse': 'token123'}
        }
        mock_post.return_value = mock_response

        # Act
        token = solve_captcha('api_key', 'sitekey')

        # Assert
        assert token == 'token123'
        mock_post.assert_called_once()
```

### Mock Selenium elements
```python
def test_parse_task_row():
    """Test parsing task row with mocked WebElement."""
    mock_row = Mock()
    mock_row.get_attribute.return_value = 'col_row_123'
    mock_row.find_element.return_value.text = 'Task Title'

    task = parse_task_row(mock_row)

    assert task.task_id == 123
    assert task.title == 'Task Title'
```

## Edge Cases

### Обязательно тестировать
```python
class TestEdgeCases:
    """Edge cases testing."""

    def test_empty_task_list(self):
        """Test handling empty task list."""
        tasks = parse_task_list([])
        assert tasks == []

    def test_malformed_html(self):
        """Test handling malformed HTML."""
        with pytest.raises(ValueError):
            parse_task_row("<invalid html")

    def test_missing_required_field(self):
        """Test handling missing task_id."""
        row = "<tr><td>Title</td></tr>"  # No task_id
        with pytest.raises(ValueError, match="task_id not found"):
            parse_task_row(row)

    def test_database_connection_lost(self, db_connection):
        """Test handling lost DB connection."""
        db_connection.close()  # Simulate connection loss

        db = TaskDatabase(db_connection)
        with pytest.raises(mysql.connector.Error):
            db.insert_task(sample_task)
```

## Performance Tests

### Mark slow tests
```python
@pytest.mark.slow
def test_parse_large_task_list(chrome_driver):
    """Test parsing 1000+ tasks."""
    import time

    start = time.time()
    tasks = parse_all_pages(chrome_driver)
    duration = time.time() - start

    assert len(tasks) > 1000
    assert duration < 300  # Should complete in < 5 minutes
```

### Skip slow tests by default
```bash
# pytest.ini
[pytest]
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests

# Запуск без slow tests
pytest -m "not slow"
```

## Integration Tests

### Database setup/teardown
```python
@pytest.fixture(scope='function')
def clean_database(db_connection):
    """Clean database before each test."""
    cursor = db_connection.cursor()
    cursor.execute("DELETE FROM tasks")
    db_connection.commit()
    yield
    cursor.execute("DELETE FROM tasks")
    db_connection.commit()

@pytest.mark.integration
def test_duplicate_task_handling(db_connection, clean_database):
    """Test that duplicate tasks update instead of insert."""
    db = TaskDatabase(db_connection)

    # First insert
    task1 = Task(task_id=123, title="Original", price=Decimal("10.00"))
    db.insert_task(task1)

    # Duplicate with updated price
    task2 = Task(task_id=123, title="Original", price=Decimal("15.00"))
    db.insert_task(task2)

    # Should have only 1 task with updated price
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*), price FROM tasks WHERE task_id = 123")
    count, price = cursor.fetchone()

    assert count == 1
    assert price == Decimal("15.00")
```

## Test Commands

### Makefile integration
```bash
# Запуск всех тестов
make test

# С покрытием
make test-cov

# Только быстрые тесты
make test-fast

# Только integration тесты
make test-integration
```

### pytest.ini configuration
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

addopts =
    --verbose
    --strict-markers
    --disable-warnings
    -ra

markers =
    slow: marks tests as slow
    integration: marks tests as integration tests
    unit: marks tests as unit tests
```

## Coverage Rules

### Исключения из coverage
```python
# .coveragerc
[run]
omit =
    tests/*
    setup.py
    */__pycache__/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
```

### Требовать минимальный coverage
```bash
# В Makefile
test-cov:
	pytest --cov=. --cov-report=html --cov-report=term --cov-fail-under=80
```

## Pre-commit Hook

### Автоматический запуск тестов
```bash
# .git/hooks/pre-commit
#!/bin/bash

echo "Running tests..."
make test-fast

if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
fi

echo "All tests passed."
exit 0
```

## CI/CD Integration

### GitHub Actions example
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.8

    - name: Install dependencies
      run: make install-dev

    - name: Run tests
      run: make test-cov

    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## Best Practices

1. **Тесты должны быть независимыми** - порядок выполнения не важен
2. **Тесты должны быть быстрыми** - unit tests < 1s каждый
3. **Тесты должны быть надёжными** - нет flaky tests
4. **Один assert на тест** - для unit tests (допустимо несколько для integration)
5. **Descriptive test names** - ясно что тестируется
6. **Test both success and failure paths**
7. **Mock external dependencies** - API calls, network, filesystem
8. **Clean up after tests** - database, files, processes
