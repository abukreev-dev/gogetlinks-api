"""
Тесты уведомлений об изменении метрик /mySites
"""

import logging

import pytest
from unittest.mock import Mock, patch

from gogetlinks_parser import (
    METRIC_DEFAULT_THRESHOLDS,
    METRIC_TRAFFIC_DEFAULT_PERCENT,
    detect_metric_changes,
    extract_referencing_label,
    format_metric_changes_message,
    get_metric_direction,
    is_metric_change_significant,
    save_sites_to_db,
    send_metric_changes_notification,
)

THRESHOLDS = METRIC_DEFAULT_THRESHOLDS
TRAFFIC_PERCENT = METRIC_TRAFFIC_DEFAULT_PERCENT


def significant(metric, old, new):
    return is_metric_change_significant(metric, old, new, THRESHOLDS, TRAFFIC_PERCENT)


class TestMetricSignificance:
    def test_sqi_below_threshold_ignored(self):
        assert significant("sqi", 20, 25) is False

    def test_sqi_at_threshold_reported(self):
        assert significant("sqi", 20, 30) is True

    @pytest.mark.parametrize(
        "old,new,expected",
        [
            (19, 20, False),
            (20, 19, False),
            (28, 29, False),
            (29, 30, True),
            (28, 30, True),
            (29, 31, True),
            (30, 31, False),
            (31, 30, False),
            (30, 30, False),
            (19, 21, True),
            (21, 19, True),
            (30, 28, True),
        ],
    )
    def test_cf_tf_threshold_and_goal(self, old, new, expected):
        assert significant("cf_tf", old, new) is expected

    def test_cf_tf_old_config_cannot_enable_single_point_noise(self):
        assert not is_metric_change_significant("cf_tf", 19, 20, {"cf_tf": 1}, 30)

    def test_cf_tf_goal_overrides_custom_threshold(self):
        assert is_metric_change_significant("cf_tf", 29, 30, {"cf_tf": 5}, 30)

    def test_equal_values_ignored(self):
        assert significant("trust", 5, 5) is False

    def test_metric_appeared_reported(self):
        assert significant("pr_cy", None, 12) is True

    def test_metric_disappeared_ignored(self):
        # Пустая ячейка — артефакт парсинга, а не падение показателя.
        assert significant("pr_cy", 12, None) is False

    def test_indexation_in_percent_points(self):
        assert significant("indexation", 70, 73) is False
        assert significant("indexation", 70, 76) is True

    def test_referencing_any_change_reported(self):
        assert significant("referencing", "Низкая", "Оптимальная") is True
        assert significant("referencing", "Низкая", "Низкая") is False

    def test_traffic_compared_in_percent(self):
        assert significant("traffic", 1000, 1200) is False
        assert significant("traffic", 1000, 1400) is True

    def test_traffic_from_zero(self):
        assert significant("traffic", 0, 50) is True
        assert significant("traffic", 0, 0) is False


class TestDetectMetricChanges:
    def test_returns_none_when_nothing_changed(self):
        old = {"sqi": 20, "cf_tf": 19, "pr_cy": 12, "trust": 5}
        site = {"sqi": 20, "cf_tf": 19, "pr_cy": 12, "trust": 5}

        assert (
            detect_metric_changes("example.com", old, site, THRESHOLDS, TRAFFIC_PERCENT)
            is None
        )

    def test_collects_only_significant_metrics(self):
        old = {"sqi": 20, "cf_tf": 19, "trust": 5, "traffic": 1000}
        site = {"sqi": 40, "cf_tf": 19, "trust": 3, "traffic": 1050}

        result = detect_metric_changes(
            "example.com", old, site, THRESHOLDS, TRAFFIC_PERCENT
        )

        assert result["site"] == "example.com"
        metrics = [change["metric"] for change in result["changes"]]
        assert metrics == ["sqi", "trust"]
        assert result["changes"][0]["old"] == "20"
        assert result["changes"][0]["new"] == "40"


class TestMetricDirection:
    def test_numeric_increase_is_up(self):
        assert get_metric_direction("sqi", 20, 40) == "up"

    def test_numeric_decrease_is_down(self):
        assert get_metric_direction("trust", 5, 3) == "down"

    def test_referencing_never_marked(self):
        assert get_metric_direction("referencing", "Низкая", "Оптимальная") is None

    def test_first_appearance_not_marked(self):
        assert get_metric_direction("pr_cy", None, 12) is None

    def test_detect_metric_changes_includes_direction(self):
        old = {"sqi": 20, "trust": 5}
        site = {"sqi": 40, "trust": 3}

        result = detect_metric_changes(
            "example.com", old, site, THRESHOLDS, TRAFFIC_PERCENT
        )

        directions = {c["metric"]: c["direction"] for c in result["changes"]}
        assert directions == {"sqi": "up", "trust": "down"}


class TestReferencingLabel:
    def test_known_labels(self):
        assert extract_referencing_label("Низкая") == "Низкая"
        assert extract_referencing_label("  Оптимальная  ") == "Оптимальная"

    def test_unknown_text(self):
        assert extract_referencing_label("N/A") is None
        assert extract_referencing_label("") is None


class TestFormatMetricChangesMessage:
    @pytest.mark.parametrize(
        "host,marked",
        [
            ("alcargo.ru", True),
            ("ALCARGO.RU", True),
            ("example.com", False),
            ("fake-alcargo.ru", False),
        ],
    )
    def test_priority_domain_crown(self, host, marked):
        message = format_metric_changes_message([{"site": host, "changes": []}])

        assert (f"<b>{host}</b> 👑" in message) is marked
        assert ("👑" in message) is marked

    def test_message_contains_sites_and_metrics(self):
        changes = [
            {
                "site": "example.com",
                "changes": [
                    {
                        "metric": "sqi",
                        "label": "ИКС",
                        "old": "20",
                        "new": "40",
                        "direction": "up",
                    },
                    {
                        "metric": "trust",
                        "label": "Траст",
                        "old": "5",
                        "new": "3",
                        "direction": "down",
                    },
                ],
            }
        ]

        message = format_metric_changes_message(changes)

        assert "example.com" in message
        assert "🟢 ИКС: 20 → <b>40</b>" in message
        assert "🔴 Траст: 5 → <b>3</b>" in message
        assert "1 сайт(ов), 2 показател(ей)" in message

    def test_message_no_mark_without_direction(self):
        changes = [
            {
                "site": "example.com",
                "changes": [
                    {
                        "metric": "referencing",
                        "label": "Ссылочность",
                        "old": "Низкая",
                        "new": "Оптимальная",
                        "direction": None,
                    }
                ],
            }
        ]

        message = format_metric_changes_message(changes)

        assert "• Ссылочность: Низкая → <b>Оптимальная</b>" in message

    def test_long_message_truncated(self):
        changes = [
            {
                "site": f"site{i}.ru",
                "changes": [
                    {"metric": "sqi", "label": "ИКС", "old": "20", "new": "40"}
                ],
            }
            for i in range(500)
        ]

        message = format_metric_changes_message(changes)

        assert len(message) <= 4096
        assert "обрезано" in message


class TestSendMetricChangesNotification:
    @pytest.fixture
    def config(self):
        return {
            "telegram": {
                "enabled": True,
                "bot_token": "token",
                "chat_id": "-100",
                "proxy": "",
            },
            "metrics": {"enabled": True},
        }

    @pytest.fixture
    def logger(self):
        return logging.getLogger("test")

    @patch("gogetlinks_parser.requests.post")
    def test_sends_message(self, mock_post, config, logger):
        mock_post.return_value = Mock(
            json=Mock(return_value={"ok": True}), raise_for_status=Mock()
        )
        changes = [
            {
                "site": "example.com",
                "changes": [
                    {"metric": "sqi", "label": "ИКС", "old": "20", "new": "40"}
                ],
            }
        ]

        assert send_metric_changes_notification(changes, config, logger) is True
        mock_post.assert_called_once()

    def test_skipped_when_metrics_disabled(self, config, logger):
        config["metrics"]["enabled"] = False
        changes = [{"site": "example.com", "changes": [{"metric": "sqi"}]}]

        assert send_metric_changes_notification(changes, config, logger) is False

    def test_skipped_when_no_changes(self, config, logger):
        assert send_metric_changes_notification([], config, logger) is False


class TestSaveSitesMetricChanges:
    def test_gradual_growth_saved_but_only_goal_notified(self):
        logger = logging.getLogger("test")
        reported = []
        for old, new in [(27, 28), (28, 29), (29, 30)]:
            conn, cursor = self._make_conn(
                [("alcargo.ru", "Доступен", None, old, None, None, None, None, None)]
            )
            site = {"site": "alcargo.ru", "status": "Доступен", "cf_tf": new}

            updated, _, changes = save_sites_to_db(
                conn, [site], logger, {"thresholds": {"cf_tf": 1}}
            )

            assert updated == 1
            assert cursor.execute.call_args_list[1][0][1][4] == new
            reported.extend(changes)

        assert len(reported) == 1
        message = format_metric_changes_message(reported)
        assert "<b>alcargo.ru</b> 👑" in message
        assert "TF/CF: 29 → <b>30</b>" in message

    def _make_conn(self, rows):
        conn = Mock()
        cursor = Mock()
        cursor.rowcount = 1
        cursor.fetchall.return_value = rows
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_metric_change_detected_and_saved(self):
        logger = logging.getLogger("test")
        # host, status, sqi, cf_tf, pr_cy, trust, traffic, indexation, referencing
        conn, cursor = self._make_conn(
            [("example.com", "Доступен", 20, 19, 12, 5, 1000, None, "Низкая")]
        )
        sites = [
            {
                "site": "example.com",
                "status": "Доступен",
                "description": None,
                "sqi": 40,
                "cf_tf": 19,
                "pr_cy": 12,
                "trust": 5,
                "traffic": 1000,
                "indexation": None,
                "referencing": "Оптимальная",
            }
        ]

        updated, status_changes, metric_changes = save_sites_to_db(
            conn, sites, logger, {"thresholds": THRESHOLDS, "traffic_percent": 30}
        )

        assert updated == 1
        assert status_changes == []
        assert len(metric_changes) == 1
        metrics = [change["metric"] for change in metric_changes[0]["changes"]]
        assert metrics == ["sqi", "referencing"]

        # Новые колонки уходят в UPDATE.
        update_params = cursor.execute.call_args_list[1][0][1]
        assert update_params[-4:] == (12, None, "Оптимальная", "example.com")

    def test_unknown_host_produces_no_metric_change(self):
        logger = logging.getLogger("test")
        conn, _ = self._make_conn([])
        sites = [
            {
                "site": "newsite.ru",
                "status": "Доступен",
                "description": None,
                "sqi": 40,
                "cf_tf": 19,
                "pr_cy": 12,
                "trust": 5,
                "traffic": 1000,
                "indexation": None,
                "referencing": "Низкая",
            }
        ]

        _, _, metric_changes = save_sites_to_db(conn, sites, logger)

        assert metric_changes == []
