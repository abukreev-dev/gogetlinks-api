"""
Тесты модуля базы данных
"""
import logging

import mysql.connector
import pytest
from unittest.mock import Mock, call
from gogetlinks_parser import (
    insert_or_update_task,
    task_has_details,
    extract_digits_only,
    save_sites_to_db,
)


class TestTaskHasDetails:
    """Тесты функции task_has_details"""

    def _make_conn(self, fetchone_result):
        """Хелпер: мок соединения с заданным результатом fetchone."""
        cursor = Mock()
        cursor.fetchone.return_value = fetchone_result
        conn = Mock()
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_returns_true_when_description_exists(self):
        """Задача с описанием → True (пропускаем модалку)."""
        conn, cursor = self._make_conn((1,))

        result = task_has_details(conn, 12345)

        assert result is True
        cursor.execute.assert_called_once()
        cursor.close.assert_called_once()

    def test_returns_false_when_no_description(self):
        """Задача без описания (новая) → False (парсим модалку)."""
        conn, cursor = self._make_conn(None)

        result = task_has_details(conn, 99999)

        assert result is False

    def test_returns_false_when_task_not_in_db(self):
        """Задача не в БД → False (парсим модалку)."""
        conn, cursor = self._make_conn(None)

        result = task_has_details(conn, 00000)

        assert result is False

    def test_cursor_closed_on_success(self):
        """Курсор закрывается даже при успешном результате."""
        conn, cursor = self._make_conn((1,))
        task_has_details(conn, 12345)
        cursor.close.assert_called_once()

    def test_cursor_closed_on_miss(self):
        """Курсор закрывается когда задача не найдена."""
        conn, cursor = self._make_conn(None)
        task_has_details(conn, 12345)
        cursor.close.assert_called_once()

    def test_query_uses_parameterized_placeholder(self):
        """SQL запрос использует параметризованный placeholder."""
        conn, cursor = self._make_conn(None)
        task_has_details(conn, 42)
        args = cursor.execute.call_args
        # Первый аргумент — SQL строка, второй — параметры
        sql, params = args[0]
        assert "%s" in sql
        assert params == (42,)


class TestMySitesHelpers:
    """Тесты helper-функций mySites."""

    def test_extract_digits_only_plain_number(self):
        assert extract_digits_only("12345") == 12345

    def test_extract_digits_only_with_labels(self):
        assert extract_digits_only("CF 20 / TF 11") == 2011

    def test_extract_digits_only_empty(self):
        assert extract_digits_only("N/A") is None
        assert extract_digits_only("") is None


class TestSaveSitesToDb:
    """Тесты сохранения метрик mySites."""

    def _make_conn(self):
        conn = Mock()
        cursor = Mock()
        cursor.fetchall.return_value = []
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_save_sites_to_db_updates_and_commits(self):
        logger = logging.getLogger("test")
        conn, cursor = self._make_conn()
        cursor.rowcount = 1
        # host, ggl_status, sqi, cf_tf, pr_cy, trust, traffic, indexation, referencing
        cursor.fetchall.return_value = [
            ("example.com", "Отклонен", 500, 2011, 20, 30, 1000, None, "Низкая"),
            ("site.org", "Отклонен", 100, 105, 10, 5, 50, None, "Низкая"),
        ]

        sites = [
            {
                "site": "example.com",
                "status": "Одобрен",
                "description": None,
                "traffic": 1000,
                "sqi": 500,
                "cf_tf": 2011,
                "trust": 30,
                "pr_cy": 20,
                "indexation": None,
                "referencing": "Низкая",
            },
            {
                "site": "site.org",
                "status": "Отклонен",
                "description": "Причина отказа",
                "traffic": 50,
                "sqi": 100,
                "cf_tf": 105,
                "trust": 5,
                "pr_cy": 10,
                "indexation": None,
                "referencing": "Низкая",
            },
        ]

        updated, status_changes, metric_changes = save_sites_to_db(conn, sites, logger)

        assert updated == 2
        assert metric_changes == []
        assert len(status_changes) == 1
        assert status_changes[0]["site"] == "example.com"
        assert status_changes[0]["old_status"] == "Отклонен"
        assert status_changes[0]["new_status"] == "Одобрен"

        # 1 select + 2 update
        assert cursor.execute.call_count == 3
        conn.commit.assert_called_once()
        cursor.close.assert_called_once()

        # Проверяем host в последнем параметре UPDATE.
        first_call_params = cursor.execute.call_args_list[1][0][1]
        second_call_params = cursor.execute.call_args_list[2][0][1]
        assert first_call_params[-1] == "example.com"
        assert second_call_params[-1] == "site.org"

    def test_save_sites_to_db_empty_sites(self):
        logger = logging.getLogger("test")
        conn, cursor = self._make_conn()

        updated, status_changes, metric_changes = save_sites_to_db(conn, [], logger)

        assert updated == 0
        assert status_changes == []
        assert metric_changes == []
        cursor.execute.assert_not_called()
        conn.commit.assert_not_called()

    def test_save_sites_to_db_rolls_back_on_db_error(self):
        logger = logging.getLogger("test")
        conn, cursor = self._make_conn()
        cursor.execute.side_effect = mysql.connector.Error("db error")

        sites = [
            {
                "site": "example.com",
                "status": "Одобрен",
                "description": None,
                "traffic": 1000,
                "sqi": 500,
                "cf_tf": 2011,
                "trust": 30,
                "pr_cy": 20,
                "indexation": None,
                "referencing": "Низкая",
            }
        ]

        updated, status_changes, metric_changes = save_sites_to_db(conn, sites, logger)

        assert updated == 0
        assert status_changes == []
        assert metric_changes == []
        conn.rollback.assert_called_once()
        cursor.close.assert_called_once()


class TestDatabaseOperations:
    """Тесты операций с базой данных"""

    def test_task_exists_true(self, mock_database):
        """Тест проверки существования задачи (существует)"""
        # TODO: Реализовать task_exists()
        pass

    def test_task_exists_false(self, mock_database):
        """Тест проверки существования задачи (не существует)"""
        # TODO: Реализовать task_exists()
        pass

    def test_insert_task_new(self, mock_database):
        """Тест вставки новой задачи"""
        # TODO: Реализовать insert_task()
        pass

    def test_insert_task_duplicate(self, mock_database):
        """Тест вставки дублирующейся задачи (должна обновиться)"""
        # TODO: Реализовать insert_task() с ON DUPLICATE KEY UPDATE
        pass

    def test_update_task(self, mock_database):
        """Тест обновления существующей задачи"""
        # TODO: Реализовать update_task()
        pass

    def test_get_new_tasks(self, mock_database):
        """Тест получения новых задач (is_new=1)"""
        # TODO: Реализовать get_new_tasks()
        pass


class TestDatabaseConnection:
    """Тесты подключения к базе данных"""

    def test_connect_to_database_success(self, mock_config):
        """Тест успешного подключения"""
        # TODO: Реализовать connect_to_database()
        pass

    def test_connect_to_database_failure(self, mock_config):
        """Тест обработки ошибки подключения"""
        # TODO: Реализовать обработку ошибок подключения
        pass

    def test_ensure_schema_exists(self, mock_database):
        """Тест создания схемы если не существует"""
        # TODO: Реализовать ensure_schema()
        pass


class TestDatabaseDeduplication:
    """Тесты дедупликации в базе данных"""

    def test_unique_constraint_prevents_duplicates(self):
        """Тест что UNIQUE INDEX предотвращает дубликаты"""
        # TODO: Интеграционный тест с реальной БД
        pass

    def test_on_duplicate_key_update(self):
        """Тест ON DUPLICATE KEY UPDATE логики"""
        # TODO: Интеграционный тест с реальной БД
        pass


class TestInsertOrUpdateTaskKeepsDetails:
    """Детали задачи не затираются прогоном, который пропустил модалку."""

    DETAIL_FIELDS = (
        "description",
        "url",
        "requirements",
        "contacts",
        "deadline",
    )

    def _make_task(self, **overrides):
        task = {
            "task_id": 12345,
            "domain": "a.ru",
            "customer": "buyer",
            "customer_url": None,
            "external_links": 1,
            "title": "Статья",
            "time_passed": "1 час",
            "price": 350.0,
            "description": None,
            "url": None,
            "requirements": None,
            "contacts": None,
            "deadline": None,
        }
        task.update(overrides)
        return task

    def _execute_sql(self, task):
        cursor = Mock()
        cursor.rowcount = 2
        conn = Mock()
        conn.cursor.return_value = cursor
        logger = logging.getLogger("test")

        insert_or_update_task(conn, task, logger)

        return cursor.execute.call_args[0][0]

    def test_detail_fields_wrapped_in_coalesce(self):
        """ON DUPLICATE KEY UPDATE сохраняет прежнее значение при NULL.

        Регрессия: прогон, где модалка пропущена (task_has_details → True),
        передаёт детали как None. С `description = VALUES(description)`
        уже разобранное описание затиралось, и заказ по такой задаче
        построить было нельзя.
        """
        sql = self._execute_sql(self._make_task())

        for field in self.DETAIL_FIELDS:
            assert (
                f"{field} = COALESCE(VALUES({field}), {field})" in sql
            ), f"{field} затирается NULL-ом"

    def test_list_fields_still_overwritten(self):
        """Поля из списка задач обновляются как раньше: они всегда приходят."""
        sql = self._execute_sql(self._make_task())

        for field in ("price", "time_passed", "external_links"):
            assert f"{field} = VALUES({field})" in sql
            assert f"COALESCE(VALUES({field})" not in sql

    def test_skipped_run_passes_none_for_details(self):
        """Прогон без модалки передаёт None — отсюда и затирание."""
        cursor = Mock()
        cursor.rowcount = 2
        conn = Mock()
        conn.cursor.return_value = cursor

        logger = logging.getLogger("test")
        insert_or_update_task(conn, self._make_task(), logger)

        params = cursor.execute.call_args[0][1]
        assert params[8:13] == (None, None, None, None, None)
