"""Tests for ggl_links sync and check functionality."""

import html
from argparse import Namespace
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from gogetlinks_parser import (
    parse_links_csv,
    sync_links_to_db,
    format_links_check_message,
    download_csv_export,
    check_links,
    send_links_check_notification,
    get_selenium_cookies_session,
    DB_FULL_LINKS_TABLE,
    TELEGRAM_MAX_MESSAGE_LENGTH,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def logger():
    return Mock()


@pytest.fixture
def paid_csv_text():
    return (
        '"Страница с обзором";"Дата оплаты"\n'
        '"https://example.com/page1";"23.02.2026"\n'
        '"https://example.com/page2";"15.03.2026"\n'
    )


@pytest.fixture
def wait_csv_text():
    return (
        '"Страница с обзором";"Осталось дней, дней"\n'
        '"https://example.com/wait1";"3"\n'
        '"https://example.com/wait2";"30"\n'
    )


@pytest.fixture
def mock_conn():
    conn = Mock()
    cursor = Mock()
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def telegram_config():
    return {
        "telegram": {
            "enabled": True,
            "bot_token": "test-token",
            "chat_id": "12345",
            "mention": "",
        }
    }


# =============================================================================
# parse_links_csv
# =============================================================================


class TestParseLinksCSV:
    def test_parse_paid_csv(self, paid_csv_text, logger):
        links = parse_links_csv(paid_csv_text, "paid", logger)

        assert len(links) == 2
        assert links[0]["url"] == "https://example.com/page1"
        assert links[0]["date_paid"] == "2026-02-23"
        assert links[0]["status"] == "paid"
        assert links[1]["url"] == "https://example.com/page2"
        assert links[1]["date_paid"] == "2026-03-15"

    def test_parse_wait_csv(self, wait_csv_text, logger):
        links = parse_links_csv(wait_csv_text, "wait_indexation", logger)

        assert len(links) == 2
        assert links[0]["url"] == "https://example.com/wait1"
        assert links[0]["date_paid"] is None
        assert links[0]["status"] == "wait_indexation"

    def test_empty_csv(self, logger):
        links = parse_links_csv("", "paid", logger)
        assert links == []

    def test_header_only_csv(self, logger):
        csv_text = '"Страница с обзором";"Дата оплаты"\n'
        links = parse_links_csv(csv_text, "paid", logger)
        assert links == []

    def test_skips_non_url_rows(self, logger):
        csv_text = (
            '"Header";"Date"\n'
            '"not-a-url";"01.01.2026"\n'
            '"https://valid.com/page";"01.01.2026"\n'
        )
        links = parse_links_csv(csv_text, "paid", logger)
        assert len(links) == 1
        assert links[0]["url"] == "https://valid.com/page"

    def test_skips_empty_rows(self, logger):
        csv_text = '"Header";"Date"\n\n"https://valid.com/page";"01.01.2026"\n\n'
        links = parse_links_csv(csv_text, "paid", logger)
        assert len(links) == 1

    def test_invalid_date_sets_none(self, logger):
        csv_text = '"Header";"Date"\n"https://example.com";"bad-date"\n'
        links = parse_links_csv(csv_text, "paid", logger)
        assert len(links) == 1
        assert links[0]["date_paid"] is None


# =============================================================================
# sync_links_to_db
# =============================================================================


class TestSyncLinksToDb:
    def test_insert_new_links(self, mock_conn, logger):
        cursor = mock_conn.cursor.return_value
        cursor.rowcount = 1  # INSERT (new row)

        links = [
            {"url": "https://example.com/1", "date_paid": "2026-01-01", "status": "paid"},
            {"url": "https://example.com/2", "date_paid": None, "status": "wait_indexation"},
        ]

        inserted, updated, deleted = sync_links_to_db(mock_conn, links, logger)

        assert inserted == 2
        assert updated == 0
        assert cursor.execute.call_count == 3  # 2 inserts + 1 delete

    def test_update_existing_links(self, mock_conn, logger):
        cursor = mock_conn.cursor.return_value
        cursor.rowcount = 2  # ON DUPLICATE KEY UPDATE

        links = [
            {"url": "https://example.com/1", "date_paid": "2026-01-01", "status": "paid"},
        ]

        inserted, updated, deleted = sync_links_to_db(mock_conn, links, logger)

        assert inserted == 0
        assert updated == 1

    def test_empty_links_list(self, mock_conn, logger):
        inserted, updated, deleted = sync_links_to_db(mock_conn, [], logger)
        assert (inserted, updated, deleted) == (0, 0, 0)

    def test_commits_on_success(self, mock_conn, logger):
        cursor = mock_conn.cursor.return_value
        cursor.rowcount = 1

        links = [{"url": "https://example.com", "date_paid": None, "status": "paid"}]
        sync_links_to_db(mock_conn, links, logger)

        mock_conn.commit.assert_called_once()

    def test_rollback_on_error(self, mock_conn, logger):
        import mysql.connector

        cursor = mock_conn.cursor.return_value
        cursor.execute.side_effect = mysql.connector.Error("DB error")

        links = [{"url": "https://example.com", "date_paid": None, "status": "paid"}]
        inserted, updated, deleted = sync_links_to_db(mock_conn, links, logger)

        assert (inserted, updated, deleted) == (0, 0, 0)
        mock_conn.rollback.assert_called_once()

    def test_delete_removed_links(self, mock_conn, logger):
        cursor = mock_conn.cursor.return_value
        cursor.rowcount = 1

        links = [{"url": "https://keep.com", "date_paid": None, "status": "paid"}]
        sync_links_to_db(mock_conn, links, logger)

        # Last execute should be DELETE with NOT IN
        last_call = cursor.execute.call_args_list[-1]
        assert "DELETE" in last_call[0][0]
        assert "NOT IN" in last_call[0][0]


# =============================================================================
# format_links_check_message
# =============================================================================


class TestFormatLinksCheckMessage:
    def test_basic_format(self):
        errors = [
            {"url": "https://example.com/page1", "code": 503},
            {"url": "https://example.com/page2", "code": 0},
        ]

        message = format_links_check_message(errors)

        assert "Проблемы с доступом оплаченных ссылок (2)" in message
        assert "https://example.com/page1 503" in message
        assert "https://example.com/page2 0" in message

    def test_html_escaping(self):
        errors = [{"url": "https://example.com/<script>", "code": 404}]
        message = format_links_check_message(errors)
        assert "<script>" not in message
        assert html.escape("https://example.com/<script>") in message

    def test_truncation(self):
        errors = [
            {"url": f"https://example.com/very-long-url-{i}", "code": 500}
            for i in range(500)
        ]
        message = format_links_check_message(errors)
        assert len(message) <= TELEGRAM_MAX_MESSAGE_LENGTH
        assert "обрезано" in message


# =============================================================================
# download_csv_export
# =============================================================================


class TestDownloadCsvExport:
    @patch("gogetlinks_parser.requests.Session")
    def test_successful_download(self, _mock_cls, logger):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.content = "url;date\nhttps://example.com;01.01.2026\n".encode("windows-1251")
        response.headers = {"Content-Type": "application/download"}
        session.post.return_value = response

        result = download_csv_export(session, "https://example.com/csv", {"url": "true"}, logger)

        assert result is not None
        assert "https://example.com" in result

    @patch("gogetlinks_parser.requests.Session")
    def test_html_response_returns_none(self, _mock_cls, logger):
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.content = b"<html>" * 3000
        response.headers = {"Content-Type": "text/html; charset=windows-1251"}
        session.post.return_value = response

        result = download_csv_export(session, "https://example.com/csv", {"url": "true"}, logger)

        assert result is None

    @patch("gogetlinks_parser.requests.Session")
    def test_request_error_returns_none(self, _mock_cls, logger):
        import requests

        session = Mock()
        session.post.side_effect = requests.RequestException("Connection error")

        result = download_csv_export(session, "https://example.com/csv", {"url": "true"}, logger)

        assert result is None


# =============================================================================
# check_links
# =============================================================================


class TestCheckLinks:
    def test_check_links_all_ok(self, mock_conn, telegram_config, logger):
        cursor_select = Mock()
        cursor_update = Mock()
        mock_conn.cursor.side_effect = [cursor_select, cursor_update]
        cursor_select.fetchall.return_value = [
            {"id": 1, "url": "https://example.com"},
        ]

        with patch("gogetlinks_parser.requests.head") as mock_head:
            mock_head.return_value = Mock(status_code=200)
            result = check_links(mock_conn, telegram_config, logger)

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_check_links_with_errors(self, mock_conn, telegram_config, logger):
        cursor_select = Mock()
        cursor_update = Mock()
        mock_conn.cursor.side_effect = [cursor_select, cursor_update]
        cursor_select.fetchall.return_value = [
            {"id": 1, "url": "https://example.com"},
            {"id": 2, "url": "https://broken.com"},
        ]

        with patch("gogetlinks_parser.requests.head") as mock_head, \
             patch("gogetlinks_parser.send_links_check_notification") as mock_notify:
            mock_head.side_effect = [
                Mock(status_code=200),
                Mock(status_code=503),
            ]
            result = check_links(mock_conn, telegram_config, logger)

        assert result is True
        mock_notify.assert_called_once()
        errors = mock_notify.call_args[0][0]
        assert len(errors) == 1
        assert errors[0]["code"] == 503

    def test_check_links_empty_table(self, mock_conn, telegram_config, logger):
        cursor = Mock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []

        result = check_links(mock_conn, telegram_config, logger)

        assert result is True

    def test_check_links_timeout_records_zero(self, mock_conn, telegram_config, logger):
        import requests

        cursor_select = Mock()
        cursor_update = Mock()
        mock_conn.cursor.side_effect = [cursor_select, cursor_update]
        cursor_select.fetchall.return_value = [
            {"id": 1, "url": "https://timeout.com"},
        ]

        with patch("gogetlinks_parser.requests.head") as mock_head, \
             patch("gogetlinks_parser.send_links_check_notification"):
            mock_head.side_effect = requests.RequestException("Timeout")
            result = check_links(mock_conn, telegram_config, logger)

        assert result is True
        # Should have updated with code=0
        update_call = cursor_update.execute.call_args
        assert update_call[0][1][0] == 0  # code


# =============================================================================
# send_links_check_notification
# =============================================================================


class TestSendLinksCheckNotification:
    def test_disabled_telegram(self, logger):
        config = {"telegram": {"enabled": False}}
        result = send_links_check_notification(
            [{"url": "https://example.com", "code": 503}], config, logger
        )
        assert result is False

    def test_empty_errors(self, telegram_config, logger):
        result = send_links_check_notification([], telegram_config, logger)
        assert result is False

    @patch("gogetlinks_parser.requests.post")
    def test_successful_send(self, mock_post, telegram_config, logger):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"ok": True}),
        )
        mock_post.return_value.raise_for_status = Mock()

        errors = [{"url": "https://example.com", "code": 503}]
        result = send_links_check_notification(errors, telegram_config, logger)

        assert result is True
        mock_post.assert_called_once()


# =============================================================================
# get_selenium_cookies_session
# =============================================================================


class TestGetSeleniumCookiesSession:
    def test_transfers_cookies(self, logger):
        driver = Mock()
        driver.get_cookies.return_value = [
            {"name": "session", "value": "abc123", "domain": ".example.com"},
            {"name": "token", "value": "xyz", "domain": ".example.com"},
        ]
        driver.execute_script.return_value = "Mozilla/5.0 Test"

        session = get_selenium_cookies_session(driver, logger)

        assert session.cookies.get("session") == "abc123"
        assert session.cookies.get("token") == "xyz"
        assert session.headers["User-Agent"] == "Mozilla/5.0 Test"


# =============================================================================
# CLI args
# =============================================================================


class TestCliArgs:
    def test_sync_links_flag(self):
        from gogetlinks_parser import parse_cli_args

        args = parse_cli_args(["--sync-links"])
        assert args.sync_links is True
        assert args.check_links is False

    def test_check_links_flag(self):
        from gogetlinks_parser import parse_cli_args

        args = parse_cli_args(["--check-links"])
        assert args.check_links is True
        assert args.sync_links is False

    def test_both_flags(self):
        from gogetlinks_parser import parse_cli_args

        args = parse_cli_args(["--sync-links", "--check-links", "--skip-tasks", "--skip-sites"])
        assert args.sync_links is True
        assert args.check_links is True
        assert args.skip_tasks is True
        assert args.skip_sites is True
