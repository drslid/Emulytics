import io
import json
from datetime import datetime

import pytest

from app import process_metrics, telemetry


def test_process_samples_report_cpu_cores_current_rss_and_first_sample_unknown(monkeypatch):
    wall = iter([10.0, 10.0, 14.0])
    cpu = iter([2.0, 8.0])
    rss = iter([8192, 4096])
    monkeypatch.setattr(process_metrics.time, "monotonic", lambda: next(wall))
    monkeypatch.setattr(process_metrics.time, "process_time", lambda: next(cpu))
    monkeypatch.setattr(process_metrics, "_read_process_start_seconds", lambda: None)
    monkeypatch.setattr(process_metrics, "_read_rss_bytes", lambda: next(rss))
    collector = process_metrics.ProcessMetrics()
    first, second = collector.sample(), collector.sample()
    assert first["cpu_cores"] is None
    assert first["sample_interval_seconds"] is None
    assert second["cpu_cores"] == 1.5
    assert second["sample_interval_seconds"] == 4.0
    assert second["memory_rss_bytes"] == 4096
    assert second["uptime_seconds"] == 4.0
    assert second["scope"] == "process"
    assert datetime.fromisoformat(second["observed_at"]).utcoffset().total_seconds() == 0
    assert set(second) == {"scope", "cpu_cores", "memory_rss_bytes", "uptime_seconds", "sample_interval_seconds", "observed_at"}


@pytest.mark.parametrize("wall,cpu", [(10.0, 2.0), (9.0, 2.0), (12.0, 0.5), (float("nan"), 2.0), (float("inf"), 2.0), (12.0, float("nan")), (12.0, float("inf")), (-1.0, 2.0)])
def test_invalid_clock_samples_never_emit_nonfinite_or_negative_cpu(monkeypatch, wall, cpu):
    walls, cpus = iter([10.0, 10.0, wall]), iter([1.0, cpu])
    monkeypatch.setattr(process_metrics.time, "monotonic", lambda: next(walls))
    monkeypatch.setattr(process_metrics.time, "process_time", lambda: next(cpus))
    monkeypatch.setattr(process_metrics, "_read_process_start_seconds", lambda: None)
    monkeypatch.setattr(process_metrics, "_read_rss_bytes", lambda: None)
    collector = process_metrics.ProcessMetrics()
    collector.sample()
    sample = collector.sample()
    assert sample["cpu_cores"] is None
    assert sample["uptime_seconds"] >= 0
    json.dumps(sample, allow_nan=False)


@pytest.mark.parametrize("statm,expected", [("200 3 0 0 0 0 0\n", 12288), ("200 0", 0), ("200 -1", None), ("200 nan", None), ("200 inf", None), ("200", None), ("garbage", None), ("200 " + str(2**64), None)])
def test_rss_uses_current_resident_pages_and_rejects_invalid_proc_values(monkeypatch, statm, expected):
    monkeypatch.setattr(process_metrics.os, "sysconf", lambda key: 4096)
    monkeypatch.setattr(process_metrics, "open", lambda *args, **kwargs: io.StringIO(statm), raising=False)
    assert process_metrics._read_rss_bytes() == expected


def test_proc_reads_are_bounded_and_do_not_collect_commandline_or_environment(monkeypatch):
    reads = []

    class ProcFile(io.StringIO):
        def read(self, size=-1):
            assert 0 < size <= 4096
            return super().read(size)

    def proc_open(path, *args, **kwargs):
        reads.append(path)
        assert path in {"/proc/self/stat", "/proc/self/statm"}
        if path.endswith("statm"):
            return ProcFile("100 2")
        return ProcFile("123 (private process name) " + " ".join(["0"] * 19 + ["600"]))

    monkeypatch.setattr(process_metrics, "open", proc_open, raising=False)
    monkeypatch.setattr(process_metrics.os, "sysconf", lambda key: 100 if key == "SC_CLK_TCK" else 4096)
    monkeypatch.setattr(process_metrics.time, "clock_gettime", lambda _: 12.25)
    monkeypatch.setattr(process_metrics.time, "CLOCK_BOOTTIME", 7, raising=False)
    sample = process_metrics.ProcessMetrics().sample()
    assert sample["uptime_seconds"] == 6.25
    assert sample["memory_rss_bytes"] == 8192
    assert set(reads) == {"/proc/self/stat", "/proc/self/statm"}
    assert "private process name" not in json.dumps(sample)
    assert "/proc/" not in json.dumps(sample)


def test_unavailable_proc_metrics_stay_unknown_and_do_not_disclose_errors(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("private path and secret token")
    monkeypatch.setattr(process_metrics, "open", unavailable, raising=False)
    sample = process_metrics.ProcessMetrics().sample()
    assert sample["memory_rss_bytes"] is None
    assert sample["cpu_cores"] is None
    assert sample["uptime_seconds"] >= 0
    assert "private" not in json.dumps(sample)


@pytest.mark.parametrize("page_size", [0, -1, True, "4096", float("nan"), float("inf")])
def test_invalid_page_size_does_not_produce_a_memory_measurement(monkeypatch, page_size):
    monkeypatch.setattr(process_metrics.os, "sysconf", lambda key: page_size)
    monkeypatch.setattr(process_metrics, "open", lambda *args, **kwargs: io.StringIO("100 2"), raising=False)
    assert process_metrics._read_rss_bytes() is None


def test_cpu_sampling_recovers_after_an_unavailable_clock(monkeypatch):
    walls, cpus = iter([10.0, 10.0, 11.0, 12.0, 14.0]), iter([1.0, float("nan"), 2.0, 2.0])
    monkeypatch.setattr(process_metrics.time, "monotonic", lambda: next(walls))
    monkeypatch.setattr(process_metrics.time, "process_time", lambda: next(cpus))
    monkeypatch.setattr(process_metrics, "_read_process_start_seconds", lambda: None)
    monkeypatch.setattr(process_metrics, "_read_rss_bytes", lambda: None)
    collector = process_metrics.ProcessMetrics()
    assert collector.sample()["cpu_cores"] is None
    assert collector.sample()["cpu_cores"] is None
    assert collector.sample()["cpu_cores"] is None
    last = collector.sample()
    assert last["cpu_cores"] == 0.0
    assert last["sample_interval_seconds"] == 2.0


def _one_heartbeat(monkeypatch, provider, *, fail_write=False):
    class OneReport:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, timeout):
            self.set()

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def join(self, timeout):
            pass

    reports = []
    def capture(*args, **kwargs):
        reports.append(kwargs["metrics"])
        if fail_write:
            raise telemetry.psycopg.OperationalError("private database password")

    monkeypatch.setenv("EMULYTIX_TELEMETRY_ENABLED", "true")
    monkeypatch.setattr(telemetry.threading, "Event", OneReport)
    monkeypatch.setattr(telemetry.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(telemetry, "heartbeat", capture)
    with telemetry.service_heartbeat("unused-test-dsn", "worker", metrics_provider=provider):
        pass
    return reports[0]


def test_heartbeat_composes_resources_with_existing_adb_metrics_without_mutating_provider(monkeypatch):
    provider_metrics = {"adb_status": "ready", "devices": [{"serial": "test-serial", "status": "device"}]}
    metrics = _one_heartbeat(monkeypatch, lambda: provider_metrics)
    assert metrics["adb_status"] == "ready"
    assert metrics["devices"] == provider_metrics["devices"]
    assert metrics["resources"]["scope"] == "process"
    assert "resources" not in provider_metrics


def test_provider_failure_keeps_resources_without_inventing_adb_readiness(monkeypatch, caplog):
    def failed_provider():
        raise RuntimeError("private ADB payload and password")
    metrics = _one_heartbeat(monkeypatch, failed_provider, fail_write=True)
    assert set(metrics) == {"resources"}
    assert "service.probe_unavailable component=worker" in caplog.text
    assert "service.heartbeat_unavailable component=worker" in caplog.text
    assert "private" not in caplog.text


def test_disabled_heartbeat_does_not_collect_resources(monkeypatch):
    monkeypatch.setenv("EMULYTIX_TELEMETRY_ENABLED", "false")
    def unexpected_collection():
        raise AssertionError("Disabled telemetry must not read process metrics")
    monkeypatch.setattr(telemetry, "ProcessMetrics", unexpected_collection)
    with telemetry.service_heartbeat("unused-test-dsn", "api"):
        pass
