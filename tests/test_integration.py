"""
Интеграционные тесты
"""
import logging

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from gogetlinks_parser import (
    format_telegram_message,
    format_status_changes_message,
    format_no_new_tasks_message,
    get_telegram_proxies,
    send_telegram_notification,
    send_status_changes_notification,
    send_no_new_tasks_notification,
    get_days_since_last_new_task,
    save_cookies,
    load_cookies,
    COOKIE_FILE,
    NO_NEW_TASKS_THRESHOLD_DAYS,
)


@pytest.fixture
def logger():
    """Logger fixture for tests."""
    return logging.getLogger("test")


@pytest.fixture
def sample_tasks():
    """Sample task list for Telegram tests."""
    return [
        {
            "task_id": 123,
            "title": "Test Task One",
            "domain": "example.com",
            "customer": "Client A",
            "price": Decimal("50.00"),
            "description": "Some description",
            "url": "https://example.com/page",
        },
        {
            "task_id": 456,
            "title": "Test Task Two",
            "domain": "site.org",
            "customer": "Client B",
            "price": Decimal("100.00"),
            "description": None,
            "url": None,
        },
    ]


@pytest.fixture
def telegram_config():
    """Telegram config fixture."""
    return {
        "telegram": {
            "enabled": True,
            "bot_token": "123456:ABC-DEF",
            "chat_id": "-100123456789",
            "proxy": "127.0.0.1:3128",
        }
    }


class TestTelegramMessage:
    """Тесты форматирования Telegram-сообщений"""

    def test_format_message_with_tasks(self, sample_tasks):
        """Тест форматирования сообщения с задачами."""
        message = format_telegram_message(sample_tasks)

        assert "Test Task One" in message
        assert "Test Task Two" in message
        assert "50 ₽" in message
        assert "100 ₽" in message
        assert "example.com" in message
        assert "Client A" in message

    def test_format_message_includes_link(self, sample_tasks):
        """Тест что ссылка на задачи включается в сообщение."""
        message = format_telegram_message(sample_tasks)

        assert "https://gogetlinks.net/webTask" in message

    def test_format_message_free_price(self):
        """Тест отображения бесплатных задач."""
        tasks = [
            {
                "task_id": 1,
                "title": "Free Task",
                "domain": "test.com",
                "customer": "client.com",
                "price": Decimal("0.00"),
            }
        ]
        message = format_telegram_message(tasks)

        assert "бесплатно" in message

    def test_format_message_html_escaping(self):
        """Тест экранирования HTML в сообщении."""
        tasks = [
            {
                "task_id": 1,
                "title": "Task <script>alert(1)</script>",
                "domain": "test.com",
                "customer": "User & Co",
                "price": Decimal("10.00"),
            }
        ]

        message = format_telegram_message(tasks)

        assert "<script>" not in message
        assert "&lt;script&gt;" in message
        assert "User &amp; Co" in message

    def test_format_message_truncation(self):
        """Тест обрезки длинного сообщения."""
        tasks = []
        for i in range(100):
            tasks.append({
                "task_id": i,
                "title": f"Very Long Task Title Number {i} " * 5,
                "domain": f"domain{i}.com",
                "customer": f"Customer {i}",
                "price": Decimal("99.99"),
                "description": "A" * 200,
            })

        message = format_telegram_message(tasks)

        assert len(message) <= 4096

    def test_format_message_single_task(self):
        """Тест форматирования одной задачи."""
        tasks = [
            {
                "task_id": 1,
                "title": "Single Task",
                "domain": "single.com",
                "customer": "Solo",
                "price": Decimal("25.00"),
            }
        ]

        message = format_telegram_message(tasks)

        assert "(1)" in message
        assert "Single Task" in message

    def test_format_status_changes_message(self):
        changes = [
            {
                "site": "example.com",
                "old_status": "Доступен",
                "new_status": "Отклонен, подробнее...",
            },
            {
                "site": "site.org",
                "old_status": "Скрыт",
                "new_status": "Доступен",
            },
        ]

        message = format_status_changes_message(changes)

        assert "Изменения статусов GoGetLinks (2)" in message
        assert "example.com" in message
        assert "Доступен" in message
        assert "Отклонен, подробнее..." in message
        assert "https://gogetlinks.net/mySites" in message


class TestTelegramSending:
    """Тесты отправки Telegram-уведомлений"""

    @patch("gogetlinks_parser.requests.post")
    def test_send_notification_success(
        self, mock_post, sample_tasks, telegram_config, logger
    ):
        """Тест успешной отправки уведомления."""
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = send_telegram_notification(sample_tasks, telegram_config, logger)

        assert result is True
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["chat_id"] == "-100123456789"
        assert payload["parse_mode"] == "HTML"
        proxies = call_kwargs.kwargs.get("proxies") or call_kwargs[1].get("proxies")
        assert proxies == {
            "http": "http://127.0.0.1:3128",
            "https": "http://127.0.0.1:3128",
        }

    @patch("gogetlinks_parser.requests.post")
    def test_send_notification_api_error(
        self, mock_post, sample_tasks, telegram_config, logger
    ):
        """Тест обработки ошибки API."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "ok": False,
            "description": "Bad Request",
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = send_telegram_notification(sample_tasks, telegram_config, logger)

        assert result is False

    @patch("gogetlinks_parser.requests.post")
    def test_send_notification_network_error(
        self, mock_post, sample_tasks, telegram_config, logger
    ):
        """Тест обработки сетевой ошибки."""
        import requests

        mock_post.side_effect = requests.RequestException("Connection refused")

        result = send_telegram_notification(sample_tasks, telegram_config, logger)

        assert result is False

    def test_send_notification_disabled(self, sample_tasks, logger):
        """Тест что уведомление не отправляется если disabled."""
        config = {
            "telegram": {
                "enabled": False,
                "bot_token": "token",
                "chat_id": "chat",
            }
        }

        result = send_telegram_notification(sample_tasks, config, logger)

        assert result is False

    def test_send_notification_no_token(self, sample_tasks, logger):
        """Тест обработки отсутствующего токена."""
        config = {
            "telegram": {
                "enabled": True,
                "bot_token": "",
                "chat_id": "-100123",
            }
        }

        result = send_telegram_notification(sample_tasks, config, logger)

        assert result is False

    def test_send_notification_empty_tasks(self, telegram_config, logger):
        """Тест с пустым списком задач."""
        result = send_telegram_notification([], telegram_config, logger)

        assert result is False

    @patch("gogetlinks_parser.requests.post")
    def test_send_status_changes_notification_success(
        self, mock_post, telegram_config, logger
    ):
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        changes = [
            {
                "site": "example.com",
                "old_status": "Доступен",
                "new_status": "Скрыт",
            }
        ]
        result = send_status_changes_notification(changes, telegram_config, logger)

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["chat_id"] == "-100123456789"
        assert payload["parse_mode"] == "HTML"
        assert "example.com" in payload["text"]

    def test_send_status_changes_notification_empty(self, telegram_config, logger):
        result = send_status_changes_notification([], telegram_config, logger)
        assert result is False


class TestCookieSession:
    """Тесты сохранения и загрузки cookies."""

    def test_save_cookies_creates_file(self, logger, tmp_path):
        """Тест сохранения cookies в файл."""
        cookie_file = tmp_path / "test_cookies.pkl"
        mock_driver = Mock()
        mock_driver.get_cookies.return_value = [
            {"name": "session", "value": "abc123", "domain": ".gogetlinks.net"},
        ]

        with patch("gogetlinks_parser.COOKIE_FILE", str(cookie_file)):
            save_cookies(mock_driver, logger)

        assert cookie_file.exists()
        # Check permissions (0o600)
        import stat
        mode = cookie_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_save_cookies_content(self, logger, tmp_path):
        """Тест что cookies корректно сериализуются."""
        import pickle
        cookie_file = tmp_path / "test_cookies.pkl"
        cookies = [
            {"name": "sid", "value": "xyz", "domain": ".gogetlinks.net"},
            {"name": "auth", "value": "token", "domain": ".gogetlinks.net"},
        ]
        mock_driver = Mock()
        mock_driver.get_cookies.return_value = cookies

        with patch("gogetlinks_parser.COOKIE_FILE", str(cookie_file)):
            save_cookies(mock_driver, logger)

        with open(cookie_file, "rb") as f:
            loaded = pickle.load(f)
        assert len(loaded) == 2
        assert loaded[0]["name"] == "sid"

    def test_load_cookies_no_file(self, logger):
        """Тест загрузки когда файла нет."""
        mock_driver = Mock()

        with patch("gogetlinks_parser.COOKIE_FILE", "/nonexistent/cookies.pkl"):
            result = load_cookies(mock_driver, logger)

        assert result is False

    def test_load_cookies_success(self, logger, tmp_path):
        """Тест успешной загрузки cookies и восстановления сессии."""
        import pickle
        import os
        cookie_file = tmp_path / "test_cookies.pkl"
        cookies = [{"name": "session", "value": "abc", "domain": ".gogetlinks.net"}]
        with open(cookie_file, "wb") as f:
            pickle.dump(cookies, f)
        os.chmod(cookie_file, 0o600)

        mock_driver = Mock()
        with patch("gogetlinks_parser.COOKIE_FILE", str(cookie_file)), \
             patch("gogetlinks_parser.is_authenticated", return_value=True):
            result = load_cookies(mock_driver, logger)

        assert result is True
        mock_driver.add_cookie.assert_called_once_with(cookies[0])

    def test_load_cookies_expired_session(self, logger, tmp_path):
        """Тест когда cookies загрузились но сессия протухла."""
        import pickle
        import os
        cookie_file = tmp_path / "test_cookies.pkl"
        with open(cookie_file, "wb") as f:
            pickle.dump([{"name": "old", "value": "expired"}], f)
        os.chmod(cookie_file, 0o600)

        mock_driver = Mock()
        with patch("gogetlinks_parser.COOKIE_FILE", str(cookie_file)), \
             patch("gogetlinks_parser.is_authenticated", return_value=False):
            result = load_cookies(mock_driver, logger)

        assert result is False
        # Stale cookie file should be removed
        assert not cookie_file.exists()

    def test_load_cookies_insecure_permissions(self, logger, tmp_path):
        """Тест что файл с широкими правами отклоняется."""
        import pickle
        import os
        cookie_file = tmp_path / "test_cookies.pkl"
        with open(cookie_file, "wb") as f:
            pickle.dump([{"name": "x", "value": "y"}], f)
        os.chmod(cookie_file, 0o644)  # Too permissive

        mock_driver = Mock()
        with patch("gogetlinks_parser.COOKIE_FILE", str(cookie_file)):
            result = load_cookies(mock_driver, logger)

        assert result is False


@pytest.mark.integration
class TestFullParsingCycle:
    """Интеграционные тесты полного цикла парсинга"""

    @pytest.mark.slow
    def test_full_cycle_with_real_credentials(self):
        """End-to-end тест с реальными credentials."""
        pytest.skip("Требует реальные credentials и anti-captcha баланс")

    def test_authentication_flow(self):
        """Тест полного потока аутентификации."""
        # TODO: Тест с mock anti-captcha
        pass

    def test_parsing_and_storage_flow(self):
        """Тест парсинга и сохранения в БД."""
        # TODO: Тест с mock данными
        pass


@pytest.mark.integration
class TestErrorRecovery:
    """Тесты восстановления после ошибок"""

    def test_captcha_failure_retry(self):
        """Тест повтора при сбое капчи."""
        # TODO: Реализовать retry логику
        pass

    def test_database_reconnect(self):
        """Тест переподключения к БД при обрыве."""
        # TODO: Реализовать reconnect логику
        pass

    def test_graceful_shutdown(self):
        """Тест корректного завершения при ошибке."""
        # TODO: Реализовать cleanup в finally
        pass


class TestNoNewTasksAlert:
    """Тесты уведомления об отсутствии новых задач"""

    def test_format_message_contains_days(self):
        """Тест что количество дней включено в сообщение."""
        message = format_no_new_tasks_message(7)

        assert "7 дней" in message

    def test_format_message_contains_link(self):
        """Тест что ссылка на задачи включена в сообщение."""
        message = format_no_new_tasks_message(5)

        assert "https://gogetlinks.net/webTask" in message

    def test_format_message_with_mention(self):
        """Тест что mention включается в сообщение."""
        message = format_no_new_tasks_message(5, mention="@user1 @user2")

        assert "@user1 @user2" in message

    def test_format_message_without_mention(self):
        """Тест сообщения без mention."""
        message = format_no_new_tasks_message(5)

        assert message.endswith("</a>")

    @patch("gogetlinks_parser.requests.post")
    def test_send_notification_success(self, mock_post, telegram_config, logger):
        """Тест успешной отправки уведомления."""
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = send_no_new_tasks_notification(7, telegram_config, logger)

        assert result is True

    def test_get_telegram_proxies_default_proxy(self):
        config = {"telegram": {"proxy": ""}}

        proxies = get_telegram_proxies(config["telegram"])

        assert proxies == {
            "http": "http://127.0.0.1:3128",
            "https": "http://127.0.0.1:3128",
        }

    def test_get_telegram_proxies_custom_proxy(self):
        config = {"telegram": {"proxy": "squid.internal:3128"}}

        proxies = get_telegram_proxies(config["telegram"])

        assert proxies == {
            "http": "http://squid.internal:3128",
            "https": "http://squid.internal:3128",
        }

    @patch("gogetlinks_parser.requests.post")
    def test_send_notification_with_mention(self, mock_post, telegram_config, logger):
        """Тест что mention из конфига попадает в сообщение."""
        telegram_config["telegram"]["mention"] = "@admin"
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = send_no_new_tasks_notification(10, telegram_config, logger)

        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert "@admin" in payload["text"]

    def test_send_notification_disabled(self, telegram_config, logger):
        """Тест что уведомление не отправляется если Telegram выключен."""
        telegram_config["telegram"]["enabled"] = False

        result = send_no_new_tasks_notification(7, telegram_config, logger)

        assert result is False

    def test_get_days_returns_int(self, logger):
        """Тест что get_days_since_last_new_task возвращает int."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (3,)

        result = get_days_since_last_new_task(mock_conn, logger)

        assert result == 3

    def test_get_days_empty_table(self, logger):
        """Тест для пустой таблицы."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (None,)

        result = get_days_since_last_new_task(mock_conn, logger)

        assert result is None

    def test_get_days_db_error(self, logger):
        """Тест обработки ошибки БД."""
        import mysql.connector

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = mysql.connector.Error("conn lost")

        result = get_days_since_last_new_task(mock_conn, logger)

        assert result is None

    def test_threshold_constant(self):
        """Тест значения порога."""
        assert NO_NEW_TASKS_THRESHOLD_DAYS == 5
