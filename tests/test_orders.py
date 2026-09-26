"""Tests for article orders (ddl.ggl_article_order) handoff to DDL.

Anchor parsing is checked on real `ggl_tasks.description` strings, taken from
the ddl database on 25.09.2026.
"""

from argparse import Namespace
from unittest.mock import Mock, patch

import pytest

from gogetlinks_parser import (
    DB_FULL_ORDERS_TABLE,
    EXIT_DATABASE_ERROR,
    EXIT_NOT_FOUND,
    EXIT_SUCCESS,
    ORDER_STUCK_ATTEMPTS,
    ORDER_STUCK_IDLE_MINUTES,
    cancel_order,
    format_order_anchor_failed_message,
    format_order_cancelled_message,
    format_order_multiple_anchors_message,
    format_order_ready_message,
    format_order_stuck_message,
    insert_article_order,
    main,
    parse_anchor,
    parse_cli_args,
    process_new_article_orders,
    process_orders,
    send_order_telegram_message,
)

import mysql.connector

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def logger():
    return Mock()


@pytest.fixture
def telegram_config():
    return {
        "telegram": {
            "enabled": True,
            "bot_token": "123:token",
            "chat_id": "-100500",
            "mention": "@owner",
            "proxy": "",
        }
    }


@pytest.fixture
def conn():
    """MySQL connection mock with independent plain/dict cursors."""
    connection = Mock()
    connection.plain_cursor = Mock()
    connection.plain_cursor.rowcount = 1
    connection.dict_cursor = Mock()

    def cursor(*args, **kwargs):
        if kwargs.get("dictionary"):
            return connection.dict_cursor
        return connection.plain_cursor

    connection.cursor.side_effect = cursor
    return connection


# =============================================================================
# parse_anchor: real descriptions
# =============================================================================


@pytest.mark.parametrize(
    "description,anchor,inflect",
    [
        # Обычный анкор, "в любом падеже" с пробелом перед скобкой
        (
            "[Анкор] подбор сотрудников в отдел по охране труда (в любом падеже )\n"
            "Размещайте ссылки в тексте обзора органично, склоняя анкоры.",
            "подбор сотрудников в отдел по охране труда",
            1,
        ),
        # Склонять нельзя, требований нет
        ("[Анкор] обмен ton (склонять анкор нельзя )", "обмен ton", 0),
        # Анкор-домен
        (
            "[Анкор] star-tex.ru (в любом падеже )\nСтатья должна касаться тематики.",
            "star-tex.ru",
            1,
        ),
        ("[Анкор] enervic.ru/products/ (в любом падеже )", "enervic.ru/products/", 1),
        # Анкор-URL
        (
            "[Анкор] https://smitup.ru/ege-russian (в любом падеже )",
            "https://smitup.ru/ege-russian",
            1,
        ),
        # Скобки внутри анкора не должны быть приняты за пометку
        (
            "[Анкор] Термокамеры (коптильные) для холодного и горячего копчения "
            "от ГК «НХЛ» (в любом падеже )",
            "Термокамеры (коптильные) для холодного и горячего копчения от ГК «НХЛ»",
            1,
        ),
        # Пометка отсутствует — считаем, что склонять нельзя
        ("[Анкор] женская норковая шуба", "женская норковая шуба", 0),
        # Дальше идёт [Комментарий] на той же строке
        (
            "[Анкор] Аренда номера (в любом падеже ) [Комментарий] Сайт оптимизатора "
            "прекратил существование.",
            "Аренда номера",
            1,
        ),
        # [Комментарий] на следующей строке
        (
            "[Анкор] грохота гис купить у производителя (в любом падеже )\n"
            "[Комментарий] Можно ссылку как-то органичнее вписать в текст?",
            "грохота гис купить у производителя",
            1,
        ),
        # Незнакомая пометка в скобках остаётся частью анкора
        (
            "[Анкор] отель официальный сайт 3 (акция)",
            "отель официальный сайт 3 (акция)",
            0,
        ),
    ],
)
def test_parse_anchor_real_strings(description, anchor, inflect):
    result = parse_anchor(description)

    assert result is not None
    assert result["anchor"] == anchor
    assert result["anchor_inflect"] == inflect
    assert result["multiple"] is False


def test_parse_anchor_multiple_takes_first():
    description = (
        "[Анкор] первый анкор (в любом падеже )\n"
        "[Анкор] второй анкор (склонять анкор нельзя )"
    )

    result = parse_anchor(description)

    assert result["anchor"] == "первый анкор"
    assert result["anchor_inflect"] == 1
    assert result["multiple"] is True


@pytest.mark.parametrize(
    "description",
    [
        None,
        "",
        "Нужна качественная статья с парой изображений.",  # нет маркера
        "[Анкор] (в любом падеже )",  # пустой анкор
        "[Анкор]    ",
    ],
)
def test_parse_anchor_not_parsed(description):
    assert parse_anchor(description) is None


def test_parse_anchor_truncates_to_column_width():
    description = "[Анкор] " + "а" * 600 + " (в любом падеже )"

    result = parse_anchor(description)

    assert len(result["anchor"]) == 500


# =============================================================================
# insert_article_order
# =============================================================================


@pytest.fixture
def article_task():
    return {
        "task_id": 25387793,
        "domain": "example.com",
        "title": "Статья",
        "price": 350,
        "url": "https://star-tex.ru/",
        "description": "[Анкор] star-tex.ru (в любом падеже )\nТолько одна ссылка.",
    }


def test_insert_article_order_created(conn, logger, article_task):
    parsed = parse_anchor(article_task["description"])
    conn.plain_cursor.rowcount = 1

    assert insert_article_order(conn, article_task, parsed, logger) is True

    query, params = conn.plain_cursor.execute.call_args[0]
    assert "INSERT IGNORE" in query
    assert DB_FULL_ORDERS_TABLE in query
    assert params == (
        25387793,
        "example.com",
        "https://star-tex.ru/",
        "star-tex.ru",
        1,
        article_task["description"],
        350,
    )
    conn.commit.assert_called_once()


def test_insert_article_order_duplicate(conn, logger, article_task):
    parsed = parse_anchor(article_task["description"])
    conn.plain_cursor.rowcount = 0

    assert insert_article_order(conn, article_task, parsed, logger) is False


def test_insert_article_order_db_error(conn, logger, article_task):
    parsed = parse_anchor(article_task["description"])
    conn.plain_cursor.execute.side_effect = mysql.connector.Error("no such table")

    assert insert_article_order(conn, article_task, parsed, logger) is None
    conn.rollback.assert_called_once()
    logger.error.assert_called()


# =============================================================================
# process_new_article_orders
# =============================================================================


def test_process_new_article_orders_only_articles(
    conn, logger, telegram_config, article_task
):
    note_task = dict(article_task, task_id=1, title="Заметка")
    context_task = dict(article_task, task_id=2, title="Контекстная ссылка")

    with patch("gogetlinks_parser.insert_article_order", return_value=True) as insert:
        created = process_new_article_orders(
            conn, [article_task, note_task, context_task], telegram_config, logger
        )

    assert created == 1
    assert insert.call_count == 1
    assert insert.call_args[0][1]["task_id"] == article_task["task_id"]


def test_process_new_article_orders_anchor_failed_notifies(
    conn, logger, telegram_config, article_task
):
    broken = dict(article_task, description="Нужна статья по тематике сайта")

    with patch("gogetlinks_parser.insert_article_order") as insert, patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=True
    ) as send:
        created = process_new_article_orders(conn, [broken], telegram_config, logger)

    assert created == 0
    insert.assert_not_called()
    send.assert_called_once()
    message = send.call_args[0][0]
    assert "анкор не распознан" in message
    assert "Нужна статья по тематике сайта" in message


def test_process_new_article_orders_reports_multiple_anchors(
    conn, logger, telegram_config, article_task
):
    multi = dict(
        article_task,
        description=(
            "[Анкор] первый (в любом падеже )\n[Анкор] второй (в любом падеже )"
        ),
    )

    with patch("gogetlinks_parser.insert_article_order", return_value=True), patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=True
    ) as send:
        created = process_new_article_orders(conn, [multi], telegram_config, logger)

    assert created == 1
    assert "несколько анкоров" in send.call_args[0][0]


def test_process_new_article_orders_no_notification_on_duplicate(
    conn, logger, telegram_config, article_task
):
    multi = dict(
        article_task,
        description=(
            "[Анкор] первый (в любом падеже )\n[Анкор] второй (в любом падеже )"
        ),
    )

    with patch("gogetlinks_parser.insert_article_order", return_value=False), patch(
        "gogetlinks_parser.send_order_telegram_message"
    ) as send:
        created = process_new_article_orders(conn, [multi], telegram_config, logger)

    assert created == 0
    send.assert_not_called()


# =============================================================================
# Message formatting
# =============================================================================


@pytest.fixture
def published_order():
    return {
        "id": 7,
        "task_id": 25387793,
        "domain": "example.com",
        "target_url": "https://star-tex.ru/",
        "anchor": "star-tex.ru",
        "anchor_inflect": 1,
        "price": 350,
        "status": "published",
        "article_url": "https://example.com/tkani-obzor/",
        "error": None,
        "attempts": 1,
    }


def test_format_order_ready_message(published_order):
    message = format_order_ready_message(published_order)

    assert "Заказ готов" in message
    assert "example.com" in message
    assert "350 ₽" in message
    assert "star-tex.ru" in message
    assert "https://star-tex.ru/" in message
    assert published_order["article_url"] in message
    assert str(published_order["task_id"]) in message


def test_format_order_ready_message_free_price(published_order):
    message = format_order_ready_message(dict(published_order, price=0))

    assert "бесплатно" in message


def test_format_order_ready_message_inflection(published_order):
    assert "можно склонять" in format_order_ready_message(published_order)
    assert "склонять нельзя" in format_order_ready_message(
        dict(published_order, anchor_inflect=0)
    )


def test_format_order_cancelled_message(published_order):
    message = format_order_cancelled_message(dict(published_order, status="cancelled"))

    assert "Заказ снят" in message
    assert "example.com" in message


def test_format_order_stuck_message(published_order):
    message = format_order_stuck_message(
        dict(published_order, status="working", attempts=4, error="no topic found")
    )

    assert "не выходит" in message
    assert "4" in message
    assert "no topic found" in message


def test_messages_escape_html(published_order):
    message = format_order_ready_message(
        dict(published_order, domain="<b>evil</b>", anchor="a & b")
    )

    assert "<b>evil</b>" not in message
    assert "&lt;b&gt;evil&lt;/b&gt;" in message
    assert "a &amp; b" in message


def test_format_order_anchor_failed_message_includes_full_task(article_task):
    message = format_order_anchor_failed_message(article_task)

    assert "анкор не распознан" in message
    assert article_task["description"].split("\n")[0] in message


def test_format_order_multiple_anchors_message(article_task):
    parsed = {"anchor": "первый", "anchor_inflect": 1, "multiple": True}

    message = format_order_multiple_anchors_message(article_task, parsed)

    assert "несколько анкоров" in message
    assert "первый" in message


# =============================================================================
# send_order_telegram_message
# =============================================================================


def test_send_order_telegram_message_ok(telegram_config, logger):
    response = Mock()
    response.json.return_value = {"ok": True}

    with patch("gogetlinks_parser.requests.post", return_value=response) as post:
        assert send_order_telegram_message("текст", telegram_config, logger) is True

    payload = post.call_args[1]["json"]
    assert payload["chat_id"] == "-100500"
    assert payload["parse_mode"] == "HTML"
    assert payload["text"].endswith("@owner")


def test_send_order_telegram_message_disabled(telegram_config, logger):
    telegram_config["telegram"]["enabled"] = False

    with patch("gogetlinks_parser.requests.post") as post:
        assert send_order_telegram_message("текст", telegram_config, logger) is False

    post.assert_not_called()


def test_send_order_telegram_message_api_error(telegram_config, logger):
    response = Mock()
    response.json.return_value = {"ok": False, "description": "chat not found"}

    with patch("gogetlinks_parser.requests.post", return_value=response):
        assert send_order_telegram_message("текст", telegram_config, logger) is False


# =============================================================================
# process_orders
# =============================================================================


def test_process_orders_notifies_and_marks(
    conn, logger, telegram_config, published_order
):
    cancelled = dict(published_order, id=8, task_id=111, status="cancelled")

    with patch(
        "gogetlinks_parser.fetch_orders",
        side_effect=[[published_order], [cancelled], []],
    ), patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=True
    ) as send, patch(
        "gogetlinks_parser.mark_order_notified", return_value=True
    ) as mark:
        counters = process_orders(conn, telegram_config, logger)

    assert counters == {"ready": 1, "cancelled": 1, "stuck": 0}
    assert send.call_count == 2
    assert [c[0][1] for c in mark.call_args_list] == [7, 8]


def test_process_orders_keeps_notified_at_when_send_fails(
    conn, logger, telegram_config, published_order
):
    with patch(
        "gogetlinks_parser.fetch_orders", side_effect=[[published_order], [], []]
    ), patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=False
    ), patch(
        "gogetlinks_parser.mark_order_notified"
    ) as mark:
        counters = process_orders(conn, telegram_config, logger)

    assert counters["ready"] == 0
    mark.assert_not_called()


def test_process_orders_stuck_reported_once(
    conn, logger, telegram_config, published_order, tmp_path
):
    stuck = dict(
        published_order,
        status="working",
        attempts=ORDER_STUCK_ATTEMPTS,
        error="generation failed",
    )
    state_file = str(tmp_path / "stuck.json")

    with patch("gogetlinks_parser.ORDER_STUCK_STATE_FILE", state_file), patch(
        "gogetlinks_parser.fetch_orders", side_effect=[[], [], [stuck]]
    ), patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=True
    ) as send:
        first = process_orders(conn, telegram_config, logger)

    with patch("gogetlinks_parser.ORDER_STUCK_STATE_FILE", state_file), patch(
        "gogetlinks_parser.fetch_orders", side_effect=[[], [], [stuck]]
    ), patch(
        "gogetlinks_parser.send_order_telegram_message", return_value=True
    ) as send_again:
        second = process_orders(conn, telegram_config, logger)

    assert first["stuck"] == 1
    assert send.call_count == 1
    assert second["stuck"] == 0
    send_again.assert_not_called()


def test_process_orders_stuck_query_uses_threshold(
    conn, logger, telegram_config, tmp_path
):
    with patch(
        "gogetlinks_parser.ORDER_STUCK_STATE_FILE", str(tmp_path / "stuck.json")
    ), patch("gogetlinks_parser.fetch_orders", return_value=[]) as fetch:
        process_orders(conn, telegram_config, logger)

    where_clauses = [c[0][1] for c in fetch.call_args_list]
    assert "status = 'published' AND notified_at IS NULL" in where_clauses
    assert "status = 'cancelled' AND notified_at IS NULL" in where_clauses
    assert fetch.call_args_list[2][0][2] == (
        ORDER_STUCK_ATTEMPTS,
        ORDER_STUCK_IDLE_MINUTES,
    )


def test_process_orders_stuck_query_requires_idle_order(
    conn, logger, telegram_config, tmp_path
):
    """Одних попыток мало: DDL тратит 3 штатно на переделку текста.

    Заказ считается застрявшим только если он ещё и перестал двигаться,
    иначе «заказ не выходит» уходит по заказу, который через минуту
    опубликуется (живой случай: заказ 25394998, 3 попытки, опубликован).
    """
    state = str(tmp_path / "stuck.json")
    with patch("gogetlinks_parser.ORDER_STUCK_STATE_FILE", state), patch(
        "gogetlinks_parser.fetch_orders", return_value=[]
    ) as fetch:
        process_orders(conn, telegram_config, logger)

    stuck_where = fetch.call_args_list[2][0][1]
    assert "status = 'working'" in stuck_where
    assert "attempts >= %s" in stuck_where
    assert "updated_at < NOW() - INTERVAL %s MINUTE" in stuck_where


# =============================================================================
# cancel_order
# =============================================================================


def test_cancel_order_sets_cancel(conn, logger):
    conn.dict_cursor.fetchone.return_value = {"id": 7, "status": "working"}
    conn.plain_cursor.rowcount = 1

    assert cancel_order(conn, 25387793, logger) is True

    query, params = conn.plain_cursor.execute.call_args[0]
    assert "status = 'cancel'" in query
    assert "notified_at = NULL" in query
    assert params == (7,)
    conn.commit.assert_called_once()


def test_cancel_order_missing(conn, logger):
    conn.dict_cursor.fetchone.return_value = None

    assert cancel_order(conn, 1, logger) is False
    conn.plain_cursor.execute.assert_not_called()


@pytest.mark.parametrize("status", ["cancel", "cancelled"])
def test_cancel_order_already_cancelled(conn, logger, status):
    conn.dict_cursor.fetchone.return_value = {"id": 7, "status": status}

    assert cancel_order(conn, 1, logger) is False
    conn.plain_cursor.execute.assert_not_called()


def test_cancel_order_db_error(conn, logger):
    conn.dict_cursor.execute.side_effect = mysql.connector.Error("boom")

    assert cancel_order(conn, 1, logger) is None


# =============================================================================
# CLI
# =============================================================================


def test_cli_orders_flag():
    args = parse_cli_args(["--orders"])

    assert args.orders is True
    assert args.cancel_order is None


def test_cli_cancel_order_flag():
    args = parse_cli_args(["--cancel-order", "25387793"])

    assert args.cancel_order == 25387793
    assert args.orders is False


def test_exit_not_found_code():
    assert EXIT_NOT_FOUND == 6


# =============================================================================
# main() routing: order modes are DB-only
# =============================================================================


def _order_args(**overrides):
    base = dict(
        skip_tasks=False,
        skip_sites=False,
        sync_links=False,
        check_links=False,
        warm_links=False,
        orders=False,
        cancel_order=None,
    )
    base.update(overrides)
    return Namespace(**base)


@pytest.fixture
def main_patches():
    """Patch everything main() needs except the order stages."""
    with patch("gogetlinks_parser.setup_logger", return_value=Mock()), patch(
        "gogetlinks_parser.load_config",
        return_value={"logging": {"log_file": "test.log", "log_level": "INFO"}},
    ), patch("gogetlinks_parser.validate_config"), patch(
        "gogetlinks_parser.connect_to_database"
    ), patch(
        "gogetlinks_parser.close_database"
    ), patch(
        "gogetlinks_parser.initialize_driver"
    ) as driver, patch(
        "gogetlinks_parser.acquire_sites_lock", return_value=(True, "")
    ) as lock:
        yield {"driver": driver, "lock": lock}


def test_main_orders_skips_selenium(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args", return_value=_order_args(orders=True)
    ), patch("gogetlinks_parser.process_orders") as process:
        result = main([])

    assert result == EXIT_SUCCESS
    process.assert_called_once()
    main_patches["driver"].assert_not_called()
    main_patches["lock"].assert_not_called()


def test_main_cancel_order_calls_cancel(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args",
        return_value=_order_args(cancel_order=25387793),
    ), patch("gogetlinks_parser.cancel_order", return_value=True) as cancel, patch(
        "gogetlinks_parser.process_orders"
    ) as process:
        result = main([])

    assert result == EXIT_SUCCESS
    assert cancel.call_args[0][1] == 25387793
    process.assert_not_called()
    main_patches["driver"].assert_not_called()


def test_main_cancel_order_not_found(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args", return_value=_order_args(cancel_order=1)
    ), patch("gogetlinks_parser.cancel_order", return_value=False):
        assert main([]) == EXIT_NOT_FOUND


def test_main_cancel_order_db_error(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args", return_value=_order_args(cancel_order=1)
    ), patch("gogetlinks_parser.cancel_order", return_value=None):
        assert main([]) == EXIT_DATABASE_ERROR
