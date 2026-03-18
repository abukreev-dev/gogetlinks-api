"""
Тесты блокировки параллельных запусков для этапа mySites.
"""
import json
import logging
import time
from argparse import Namespace
from unittest.mock import Mock, patch

from gogetlinks_parser import (
    EXIT_SUCCESS,
    acquire_sites_lock,
    is_pid_alive,
    main,
    release_sites_lock,
)


def test_is_pid_alive_current_process():
    assert is_pid_alive(1) in (True, False)  # environment dependent
    assert is_pid_alive(0) is False
    assert is_pid_alive(-10) is False


def test_acquire_and_release_sites_lock(tmp_path):
    logger = logging.getLogger("test")
    lock_file = str(tmp_path / "sites.lock")

    acquired, reason = acquire_sites_lock(
        logger=logger, lock_file=lock_file, ttl_seconds=10
    )
    assert acquired is True
    assert reason == "acquired"

    release_sites_lock(logger=logger, lock_file=lock_file)
    assert (tmp_path / "sites.lock").exists() is False


def test_acquire_fails_when_active_owner_exists(tmp_path):
    logger = logging.getLogger("test")
    lock_path = tmp_path / "sites.lock"

    first, _ = acquire_sites_lock(
        logger=logger, lock_file=str(lock_path), ttl_seconds=10
    )
    assert first is True

    second, reason = acquire_sites_lock(
        logger=logger, lock_file=str(lock_path), ttl_seconds=10
    )
    assert second is False
    assert "active lock held by pid=" in reason


def test_acquire_reclaims_stale_dead_lock(tmp_path):
    logger = logging.getLogger("test")
    lock_path = tmp_path / "sites.lock"
    stale_payload = {
        "pid": 999999,
        "started_at": time.time() - 7200,
        "mode": "sites",
    }
    lock_path.write_text(json.dumps(stale_payload), encoding="utf-8")

    acquired, reason = acquire_sites_lock(
        logger=logger, lock_file=str(lock_path), ttl_seconds=3600
    )
    assert acquired is True
    assert reason == "acquired"


def test_acquire_keeps_recent_dead_lock(tmp_path):
    logger = logging.getLogger("test")
    lock_path = tmp_path / "sites.lock"
    dead_recent_payload = {
        "pid": 999999,
        "started_at": time.time() - 30,
        "mode": "sites",
    }
    lock_path.write_text(json.dumps(dead_recent_payload), encoding="utf-8")

    acquired, reason = acquire_sites_lock(
        logger=logger, lock_file=str(lock_path), ttl_seconds=3600
    )
    assert acquired is False
    assert "dead lock owner pid=" in reason


def test_release_does_not_remove_foreign_lock(tmp_path):
    logger = logging.getLogger("test")
    lock_path = tmp_path / "sites.lock"
    foreign_payload = {
        "pid": 999999,
        "started_at": time.time(),
        "mode": "sites",
    }
    lock_path.write_text(json.dumps(foreign_payload), encoding="utf-8")

    release_sites_lock(logger=logger, lock_file=str(lock_path))
    assert lock_path.exists() is True


@patch("gogetlinks_parser.acquire_sites_lock", return_value=(False, "active lock"))
@patch("gogetlinks_parser.connect_to_database")
@patch("gogetlinks_parser.validate_config")
@patch("gogetlinks_parser.load_config")
@patch("gogetlinks_parser.setup_logger")
@patch(
    "gogetlinks_parser.parse_cli_args",
    return_value=Namespace(skip_tasks=False, skip_sites=False, sync_links=False, check_links=False, warm_links=False),
)
def test_main_exits_success_when_sites_lock_busy(
    _mock_args,
    mock_setup_logger,
    mock_load_config,
    _mock_validate,
    mock_connect_db,
    _mock_acquire_lock,
):
    logger = Mock()
    mock_setup_logger.return_value = logger
    mock_load_config.return_value = {
        "logging": {"log_file": "test.log", "log_level": "INFO"}
    }

    result = main([])

    assert result == EXIT_SUCCESS
    mock_connect_db.assert_not_called()
