"""
Тесты модуля парсинга
"""
import logging

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from gogetlinks_parser import (
    parse_price,
    extract_task_id,
    parse_task_row,
    parse_task_details,
    sanitize_text,
)


@pytest.fixture
def logger():
    """Logger fixture for tests."""
    return logging.getLogger("test")


class TestPriceParser:
    """Тесты парсинга цен"""

    @pytest.mark.parametrize("input_price,expected", [
        ("$123.45", Decimal("123.45")),
        ("1,234.56", Decimal("1234.56")),
        ("$50.00", Decimal("50.00")),
        ("FREE", Decimal("0.00")),
        ("", Decimal("0.00")),
        ("N/A", Decimal("0.00")),
        ("0", Decimal("0")),
        ("$0.00", Decimal("0.00")),
        ("1000", Decimal("1000")),
        ("99.99 руб", Decimal("99.99")),
    ])
    def test_parse_price_robust(self, input_price, expected):
        """Тест парсинга различных форматов цен."""
        assert parse_price(input_price) == expected


class TestTaskIdExtraction:
    """Тесты извлечения ID задачи"""

    def test_extract_task_id_valid(self):
        """Тест извлечения валидного ID."""
        assert extract_task_id("col_row_123456") == 123456

    def test_extract_task_id_large(self):
        """Тест извлечения большого ID."""
        assert extract_task_id("col_row_9999999") == 9999999

    def test_extract_task_id_invalid_format(self):
        """Тест обработки невалидного формата."""
        with pytest.raises(ValueError, match="Invalid row ID format"):
            extract_task_id("invalid")

    def test_extract_task_id_non_numeric(self):
        """Тест обработки нечислового ID."""
        with pytest.raises(ValueError, match="Could not parse task_id"):
            extract_task_id("col_row_abc")


class TestTaskRowParser:
    """Тесты парсинга строки задачи"""

    def test_parse_task_row_success(self, sample_task_row, logger):
        """Тест успешного парсинга строки задачи."""
        task = parse_task_row(sample_task_row, logger)

        assert task is not None
        assert task["task_id"] == 123456
        assert task["domain"] == "example.com"
        assert task["customer"] == "Test Client"
        assert task["external_links"] == 5
        assert task["price"] == Decimal("50.00")

    def test_parse_task_row_no_id(self, logger):
        """Тест парсинга строки без ID."""
        row = Mock()
        row.get_attribute.return_value = None

        task = parse_task_row(row, logger)
        assert task is None

    def test_parse_task_row_few_cells(self, logger):
        """Тест парсинга строки с недостаточным числом ячеек."""
        row = Mock()
        row.get_attribute.return_value = "col_row_123"
        row.find_elements.return_value = [Mock(), Mock()]

        task = parse_task_row(row, logger)
        assert task is None


class TestTaskDetailsParser:
    """Тесты парсинга деталей задачи"""

    def test_parse_task_details_success(self, logger):
        """Тест парсинга деталей задачи из модалки."""
        from selenium.common.exceptions import NoSuchElementException

        driver = Mock()

        # Mock #copy_url input
        copy_url_input = Mock()
        copy_url_input.get_attribute.return_value = "http://example.com/page"

        # Mock block with title "Текст задания"
        block_title = Mock()
        block_title.text = "Текст задания"

        block_value = Mock()
        block_value.text = "Place link at top of article"

        task_block = Mock()
        task_block.find_element.side_effect = lambda by, sel: {
            ".block_title": block_title,
            ".params .block_value": block_value,
        }.get(sel, Mock())
        task_block.find_elements.return_value = []

        # Mock modal
        modal = Mock()

        def modal_find_element(by, selector):
            if selector == "#copy_url":
                return copy_url_input
            raise NoSuchElementException()

        modal.find_element.side_effect = modal_find_element
        modal.find_elements.return_value = [task_block]

        driver.find_element.return_value = modal

        with patch("gogetlinks_parser.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.return_value = modal

            details = parse_task_details(driver, 123, logger)

        assert details["url"] == "http://example.com/page"
        assert details["description"] is not None
        assert "Place link at top of article" in details["description"]

    def test_parse_task_details_timeout(self, logger):
        """Тест таймаута при открытии модалки."""
        from selenium.common.exceptions import TimeoutException

        driver = Mock()
        driver.execute_script.return_value = None

        with patch("gogetlinks_parser.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.side_effect = TimeoutException()

            details = parse_task_details(driver, 999, logger)

        assert details["description"] is None
        assert details["url"] is None
        assert details["requirements"] is None

    def test_parse_task_details_returns_all_keys(self, logger):
        """Тест что возвращаются все ожидаемые ключи."""
        driver = Mock()

        with patch("gogetlinks_parser.WebDriverWait") as mock_wait:
            from selenium.common.exceptions import TimeoutException
            mock_wait.return_value.until.side_effect = TimeoutException()

            details = parse_task_details(driver, 1, logger)

        expected_keys = {"description", "url", "requirements", "contacts", "deadline"}
        assert set(details.keys()) == expected_keys


class TestHTMLCleaning:
    """Тесты очистки HTML"""

    def test_sanitize_html_entities(self):
        """Тест декодирования HTML entities."""
        assert sanitize_text("Hello &amp; World") == "Hello & World"
        assert sanitize_text("&lt;b&gt;bold&lt;/b&gt;") == "<b>bold</b>"

    def test_sanitize_whitespace(self):
        """Тест нормализации пробелов."""
        assert sanitize_text("  hello   world  ") == "hello world"
        assert sanitize_text("line1\n  line2\t  line3") == "line1 line2 line3"

    def test_sanitize_empty(self):
        """Тест обработки пустой строки."""
        assert sanitize_text("") == ""
        assert sanitize_text("   ") == ""
