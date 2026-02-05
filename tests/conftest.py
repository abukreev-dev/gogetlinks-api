"""
Pytest fixtures для тестов
"""
import pytest
from unittest.mock import Mock


@pytest.fixture
def mock_config():
    """Мок конфигурации для тестов"""
    return {
        'gogetlinks': {
            'username': 'test@example.com',
            'password': 'test_password'
        },
        'anticaptcha': {
            'api_key': 'test_api_key'
        },
        'database': {
            'host': 'localhost',
            'port': 3306,
            'database': 'gogetlinks_test',
            'user': 'test_user',
            'password': 'test_password'
        },
        'output': {
            'print_tasks': False
        },
        'logging': {
            'level': 'INFO',
            'file': 'test.log'
        }
    }


@pytest.fixture
def mock_driver():
    """Мок Selenium WebDriver для тестов"""
    driver = Mock()
    driver.page_source = "<html><body>Test</body></html>"
    driver.current_url = "https://gogetlinks.net"
    return driver


@pytest.fixture
def mock_database():
    """Мок базы данных для тестов"""
    db = Mock()
    cursor = Mock()
    db.cursor.return_value = cursor
    return db


@pytest.fixture
def sample_task_row():
    """Пример HTML строки с задачей для парсинга"""
    row = Mock()
    row.get_attribute.return_value = "col_row_123456"

    cells = []
    for _ in range(6):
        cell = Mock()
        cells.append(cell)

    # Настройка ячеек
    cells[0].find_element.return_value.text = "example.com"  # domain
    cells[1].find_element.return_value.text = "Test Client"  # customer
    cells[1].find_element.return_value.get_attribute.return_value = "https://gogetlinks.net/client/123"
    cells[2].text = "5"  # external_links
    cells[4].text = "2 часа назад"  # time_passed
    cells[5].text = "$50.00"  # price

    row.find_elements.return_value = cells
    return row
