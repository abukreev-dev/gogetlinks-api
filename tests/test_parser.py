"""
Тесты модуля парсинга
"""
import logging

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from selenium.common.exceptions import TimeoutException, WebDriverException

from gogetlinks_parser import (
    has_advertiser_text,
    parse_price,
    extract_task_id,
    parse_task_row,
    parse_task_details,
    sanitize_text,
    is_anti_bot_blocked,
    navigate_with_retry,
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
        ("500 Р", Decimal("500")),    # uppercase Cyrillic Р (U+0420) from gogetlinks
        ("0 Р", Decimal("0")),        # zero price with uppercase Р
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


class TestAdvertiserText:
    """Признак «Текст предоставлен рекламодателем» в ячейке действий."""

    @staticmethod
    def _tooltip(head="", body=""):
        el = Mock()
        el.get_attribute.side_effect = lambda name: {
            "data-tooltip-head": head,
            "data-tooltip-body": body,
        }.get(name)
        return el

    def _cell(self, *tooltips):
        cell = Mock()
        cell.find_elements.return_value = list(tooltips)
        return cell

    def test_detected_by_tooltip_head(self, logger):
        cell = self._cell(
            self._tooltip(body="Написать первое сообщение"),
            self._tooltip(
                head="Текст предоставлен рекламодателем",
                body="Готовый текст по заданию предоставлен рекламодателем.",
            ),
        )

        assert has_advertiser_text(cell, logger) is True

    def test_absent_on_regular_task(self, logger):
        cell = self._cell(
            self._tooltip(body="Написать первое сообщение"),
            self._tooltip(body="Отклонить"),
            self._tooltip(body="Выполнено"),
        )

        assert has_advertiser_text(cell, logger) is False

    def test_delete_link_task_is_not_advertiser_text(self, logger):
        """Тултип задания на снятие ссылки не должен считаться признаком."""
        cell = self._cell(
            self._tooltip(
                head="Задание на удаление ссылки",
                body="Задание на удаление ссылки отменить нельзя.",
            )
        )

        assert has_advertiser_text(cell, logger) is False

    def test_no_tooltips(self, logger):
        assert has_advertiser_text(self._cell(), logger) is False

    def test_lookup_failure_is_not_fatal(self, logger):
        cell = Mock()
        cell.find_elements.side_effect = WebDriverException("boom")

        assert has_advertiser_text(cell, logger) is False

    def test_parse_task_row_sets_flag(self, sample_task_row, logger):
        """Строка без седьмой ячейки — признака нет."""
        task = parse_task_row(sample_task_row, logger)

        assert task is not None
        assert task["advertiser_text"] is False


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


class TestAntiBotDetection:
    """Тесты детекта антибот-блокировки."""

    def test_detects_403_url(self):
        driver = Mock()
        driver.current_url = "https://gogetlinks.net/403.php"
        driver.page_source = "<html></html>"
        assert is_anti_bot_blocked(driver) is True

    def test_detects_qrator_marker(self):
        driver = Mock()
        driver.current_url = "https://gogetlinks.net/"
        driver.page_source = "<html><body>QRATOR protection</body></html>"
        assert is_anti_bot_blocked(driver) is True

    def test_returns_false_for_normal_page(self):
        driver = Mock()
        driver.current_url = "https://gogetlinks.net/"
        driver.page_source = "<html><a href='/user/signIn'>Войти</a></html>"
        assert is_anti_bot_blocked(driver) is False


class TestNavigateWithRetry:
    """Тесты навигации с ретраями"""

    def test_returns_true_on_first_attempt(self, mock_driver, logger):
        """Успешная загрузка с первой попытки — один вызов get()"""
        assert navigate_with_retry(mock_driver, "https://example.com", logger) is True
        assert mock_driver.get.call_count == 1

    def test_retries_after_timeout_and_succeeds(self, mock_driver, logger):
        """Зависшая загрузка не роняет прогон — вторая попытка проходит"""
        mock_driver.get.side_effect = [TimeoutException("hung"), None]

        with patch("gogetlinks_parser.time.sleep"):
            result = navigate_with_retry(mock_driver, "https://example.com", logger)

        assert result is True
        assert mock_driver.get.call_count == 2

    def test_returns_false_when_all_attempts_fail(self, mock_driver, logger):
        """После исчерпания попыток возвращается False, исключение не всплывает"""
        mock_driver.get.side_effect = WebDriverException("down")

        with patch("gogetlinks_parser.time.sleep"):
            result = navigate_with_retry(
                mock_driver, "https://example.com", logger, attempts=3
            )

        assert result is False
        assert mock_driver.get.call_count == 3

    def test_respects_attempts_argument(self, mock_driver, logger):
        """Количество попыток задаётся аргументом"""
        mock_driver.get.side_effect = TimeoutException("hung")

        with patch("gogetlinks_parser.time.sleep"):
            navigate_with_retry(mock_driver, "https://example.com", logger, attempts=1)

        assert mock_driver.get.call_count == 1
