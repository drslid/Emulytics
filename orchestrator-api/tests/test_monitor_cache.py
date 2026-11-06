from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from app import monitor_routes
from app.monitor_metrics import database_metrics


def test_slow_collection_is_shared_for_two_seconds_after_completion(monkeypatch):
    clock = [100.0]
    entered, release = Event(), Event()
    samples = []

    def slow_snapshot(*_):
        entered.set()
        assert release.wait(5)
        clock[0] += 3
        sample = {"sample": len(samples) + 1}
        samples.append(sample)
        return sample

    monkeypatch.setattr(monitor_routes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(monitor_routes, "snapshot", slow_snapshot)
    cache = monitor_routes.SnapshotCache()
    store = SimpleNamespace(dsn="slow-isolated-test")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cache.get, store, "24h") for _ in range(4)]
        assert entered.wait(5)
        release.set()
        assert [future.result(timeout=5) for future in futures] == [{"sample": 1}] * 4
    clock[0] += 1.9
    assert cache.get(store, "24h") == {"sample": 1}
    clock[0] += 0.2
    assert cache.get(store, "24h") == {"sample": 2}


def test_stream_cache_shares_concurrent_samples_and_expires_without_stale_fallback(monkeypatch):
    clock = [100.0]
    entered, release = Event(), Event()
    calls = []

    def observe(store, window):
        calls.append((store.dsn, window))
        entered.set()
        assert release.wait(5)
        return {"sample": len(calls)}

    monkeypatch.setattr(monitor_routes.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(monitor_routes, "snapshot", observe)
    cache = monitor_routes.SnapshotCache()
    store = SimpleNamespace(dsn="isolated-test")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cache.get, store, "24h") for _ in range(4)]
        assert entered.wait(5)
        release.set()
        assert [future.result(timeout=5) for future in futures] == [{"sample": 1}] * 4
    assert len(calls) == 1
    assert cache.get(store, "1h") == {"sample": 2}
    clock[0] += 2
    assert cache.get(store, "24h") == {"sample": 3}

    def unavailable(*_):
        raise RuntimeError("private failure detail")

    monkeypatch.setattr(monitor_routes, "snapshot", unavailable)
    clock[0] += 2
    with pytest.raises(RuntimeError):
        cache.get(store, "24h")
    monkeypatch.setattr(monitor_routes, "snapshot", observe)
    assert cache.get(SimpleNamespace(dsn="another-isolated-test"), "24h") == {"sample": 4}


def test_optional_database_statistics_privilege_failure_rolls_back_only_savepoint(database_dsn):
    with psycopg.connect(database_dsn, row_factory=dict_row) as connection:
        connection.execute("SELECT 1")

        class DeniedStatistics:
            def transaction(self):
                return connection.transaction()

            def execute(self, query):
                assert "pg_stat_activity" in query
                return connection.execute("DO $$ BEGIN RAISE insufficient_privilege; END $$")

        assert database_metrics(DeniedStatistics()) == {}
        assert connection.execute("SELECT 1 AS still_readable").fetchone() == {"still_readable": 1}


def test_database_connection_count_requires_visibility_of_other_roles(database_dsn):
    role = sql.Identifier("monitor_test_" + uuid4().hex)
    with psycopg.connect(database_dsn, row_factory=dict_row) as connection:
        try:
            assert database_metrics(connection)["connections_used"] >= 1
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(role))
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
            hidden = connection.execute(
                "SELECT COUNT(*) AS hidden FROM pg_stat_activity WHERE backend_type IS NULL"
            ).fetchone()["hidden"]
            assert hidden >= 1
            limited = database_metrics(connection)
            assert limited["connections_used"] is None
            assert limited["connections_max"] > 0
            assert limited["size_bytes"] > 0

            connection.execute("RESET ROLE")
            connection.execute(sql.SQL("GRANT pg_read_all_stats TO {}").format(role))
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
            visible = connection.execute(
                "SELECT COUNT(*) AS visible FROM pg_stat_activity WHERE backend_type='client backend'"
            ).fetchone()["visible"]
            assert visible >= 1
            assert database_metrics(connection)["connections_used"] == visible
        finally:
            # The temporary role and grant exist only inside this disposable test transaction.
            connection.rollback()
