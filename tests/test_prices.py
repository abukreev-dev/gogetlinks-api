"""Tests for the site price experiment (trust-9 domains, /mySites site card)."""

from argparse import Namespace
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from selenium.common.exceptions import NoSuchElementException

from gogetlinks_parser import (
    DB_FULL_PRICE_EXPERIMENT_TABLE,
    EXIT_SUCCESS,
    PRICE_CONTROL_GROUP,
    PRICE_EXPERIMENT_GROUPS,
    assign_price_groups,
    main,
    parse_cli_args,
    parse_site_row,
    price_problems,
    split_price_groups,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def logger():
    return Mock()


@pytest.fixture
def conn():
    """MySQL connection mock with independent plain/dict cursors."""
    connection = Mock()
    connection.plain_cursor = Mock()
    connection.dict_cursor = Mock()

    def cursor(*args, **kwargs):
        if kwargs.get("dictionary"):
            return connection.dict_cursor
        return connection.plain_cursor

    connection.cursor.side_effect = cursor
    return connection


def _domain(host, target="gensite", sales=0, revenue=0, traffic=0):
    return {
        "host": host,
        "target": target,
        "sales": sales,
        "revenue": Decimal(revenue),
        "traffic": traffic,
    }


def _prices(paper, post, link, off=()):
    prices = {"paper": Decimal(paper), "post": Decimal(post), "link": Decimal(link)}
    for key in ("paper", "post", "link"):
        prices[f"not_{key}"] = key in off
    return prices


# =============================================================================
# split_price_groups
# =============================================================================


def test_split_puts_site_target_into_control():
    domains = [_domain("a.ru", target="site"), _domain("b.ru")]

    groups = {d["host"]: d for d in split_price_groups(domains)}

    assert groups["a.ru"]["group"] == PRICE_CONTROL_GROUP
    assert groups["a.ru"]["target_price"] is None
    assert groups["b.ru"]["target_price"] in PRICE_EXPERIMENT_GROUPS


def test_split_makes_equal_groups():
    domains = [_domain(f"d{i}.ru", sales=i) for i in range(39)]

    assignment = split_price_groups(domains)

    sizes = {
        price: sum(1 for d in assignment if d["target_price"] == price)
        for price in PRICE_EXPERIMENT_GROUPS
    }
    assert sizes == {500: 13, 450: 13, 400: 13}


def test_split_snake_balances_sales():
    """Сильные домены не уходят все в одну группу: раздача змейкой."""
    domains = [_domain(f"d{i}.ru", sales=s) for i, s in enumerate([9, 8, 7, 6, 5, 4])]

    assignment = split_price_groups(domains)

    sales = {
        price: sum(d["sales"] for d in assignment if d["target_price"] == price)
        for price in PRICE_EXPERIMENT_GROUPS
    }
    # 9+4, 8+5, 7+6
    assert sales == {500: 13, 450: 13, 400: 13}


# =============================================================================
# price_problems
# =============================================================================


def test_control_below_minimum_reported():
    row = {"target_price": None}

    problems = price_problems(row, _prices(1000, 500, 900))

    assert problems == ["Заметка 500 ₽"]


def test_control_ignores_disabled_type():
    row = {"target_price": None}

    assert price_problems(row, _prices(1000, 100, 900, off=("post",))) == []


def test_group_requires_all_three_prices():
    row = {"target_price": 450}

    assert price_problems(row, _prices(450, 450, 450)) == []
    assert price_problems(row, _prices(450, 500, 450)) == ["Заметка 500 ₽ (нужно 450)"]


# =============================================================================
# parse_site_row: site_id from "Настроить"
# =============================================================================


def _site_row(href):
    cells = [Mock(text="x") for _ in range(10)]
    link = Mock()
    link.get_attribute.return_value = href
    if href is None:
        cells[0].find_element.side_effect = NoSuchElementException()
    else:
        cells[0].find_element.return_value = link

    row = Mock()
    row.find_elements.return_value = cells
    row.find_element.return_value = Mock(text="fin61.ru")
    return row


def test_parse_site_row_reads_site_id():
    site = parse_site_row(
        _site_row("https://gogetlinks.net/editSiteInfo/index/site_id/309236")
    )

    assert site["site"] == "fin61.ru"
    assert site["site_id"] == 309236


def test_parse_site_row_without_settings_link():
    site = parse_site_row(_site_row(None))

    assert site["site_id"] is None


# =============================================================================
# assign_price_groups
# =============================================================================


def test_assign_runs_only_once(conn, logger):
    conn.dict_cursor.fetchone.return_value = {"cnt": 48}

    assert assign_price_groups(conn, logger) == []
    assert conn.dict_cursor.execute.call_count == 1


def test_assign_inserts_every_domain(conn, logger):
    conn.dict_cursor.fetchone.return_value = {"cnt": 0}
    conn.dict_cursor.fetchall.return_value = [
        _domain("a.ru", target="site"),
        _domain("b.ru", sales=3),
        _domain("c.ru", sales=2),
        _domain("d.ru", sales=1),
    ]

    assignment = assign_price_groups(conn, logger)

    assert len(assignment) == 4
    inserts = [
        c for c in conn.dict_cursor.execute.call_args_list if "INSERT" in c[0][0]
    ]
    assert len(inserts) == 4
    assert DB_FULL_PRICE_EXPERIMENT_TABLE in inserts[0][0][0]
    conn.commit.assert_called_once()


# =============================================================================
# CLI / main routing
# =============================================================================


def test_cli_prices_flags():
    args = parse_cli_args(["--prices-apply"])

    assert args.prices_apply is True
    assert args.confirm is False


def _args(**overrides):
    base = dict(
        skip_tasks=False,
        skip_sites=False,
        sync_links=False,
        check_links=False,
        warm_links=False,
        orders=False,
        cancel_order=None,
        prices_assign=False,
        prices_read=False,
        prices_apply=False,
        confirm=False,
        prices_report=False,
    )
    base.update(overrides)
    return Namespace(**base)


@pytest.fixture
def main_patches():
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
        "gogetlinks_parser.load_cookies", return_value=True
    ), patch(
        "gogetlinks_parser.is_anti_bot_blocked", return_value=False
    ), patch(
        "gogetlinks_parser.acquire_sites_lock", return_value=(True, "")
    ) as lock, patch(
        "gogetlinks_parser.release_sites_lock"
    ), patch(
        "gogetlinks_parser.parse_task_list"
    ) as tasks, patch(
        "gogetlinks_parser.parse_my_sites"
    ) as sites:
        yield {"driver": driver, "lock": lock, "tasks": tasks, "sites": sites}


def test_main_prices_report_is_db_only(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args", return_value=_args(prices_report=True)
    ), patch("gogetlinks_parser.prices_report") as report:
        assert main([]) == EXIT_SUCCESS

    report.assert_called_once()
    main_patches["driver"].assert_not_called()
    main_patches["lock"].assert_not_called()


def test_main_prices_apply_skips_regular_stages(main_patches):
    with patch(
        "gogetlinks_parser.parse_cli_args",
        return_value=_args(prices_apply=True, confirm=True),
    ), patch("gogetlinks_parser.apply_experiment_prices") as apply:
        assert main([]) == EXIT_SUCCESS

    assert apply.call_args.kwargs["confirm"] is True
    main_patches["lock"].assert_called_once()
    main_patches["tasks"].assert_not_called()
    main_patches["sites"].assert_not_called()
