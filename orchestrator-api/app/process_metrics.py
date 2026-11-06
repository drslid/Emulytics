"""Bounded, local observations of this Python process, excluding child processes.

CPU is consumed cores over the sampling interval; RSS is current resident memory.
Linux uptime uses the process start tick and boot clock. Without those facilities,
uptime is elapsed time since this collector was created, rather than host uptime.
"""
import math
import os
import time
from datetime import datetime, timezone


def _nonnegative_finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _read_rss_bytes():
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
            return None
        with open("/proc/self/statm", encoding="ascii") as source:
            resident_pages = int(source.read(256).split()[1])
        rss = resident_pages * page_size
        return rss if 0 <= rss <= 2**63 - 1 else None
    except (OSError, ValueError, IndexError, TypeError, UnicodeError):
        return None


def _read_process_start_seconds():
    if not hasattr(time, "CLOCK_BOOTTIME"):
        return None
    try:
        ticks_per_second = os.sysconf("SC_CLK_TCK")
        if not isinstance(ticks_per_second, int) or isinstance(ticks_per_second, bool) or ticks_per_second <= 0:
            return None
        with open("/proc/self/stat", encoding="ascii") as source:
            # The comm field can contain spaces and parentheses; field 22 follows it.
            start_ticks = int(source.read(4096).rsplit(")", 1)[1].split()[19])
        return _nonnegative_finite(start_ticks / ticks_per_second)
    except (OSError, ValueError, IndexError, TypeError, OverflowError, UnicodeError):
        return None


class ProcessMetrics:
    def __init__(self):
        self._started_at = _nonnegative_finite(time.monotonic())
        self._process_started_at = _read_process_start_seconds()
        self._previous = None

    def sample(self):
        now = _nonnegative_finite(time.monotonic())
        cpu = _nonnegative_finite(time.process_time())
        interval, cores = None, None
        if now is not None and cpu is not None and self._previous is not None:
            previous_wall, previous_cpu = self._previous
            elapsed = _nonnegative_finite(now - previous_wall)
            if elapsed is not None and elapsed > 0:
                interval = elapsed
                cores = _nonnegative_finite((cpu - previous_cpu) / elapsed)
        self._previous = (now, cpu) if now is not None and cpu is not None else None
        if self._started_at is None:
            self._started_at = now
        uptime = _nonnegative_finite(now - self._started_at) if now is not None and self._started_at is not None else None
        if self._process_started_at is not None:
            try:
                observed_uptime = _nonnegative_finite(time.clock_gettime(time.CLOCK_BOOTTIME) - self._process_started_at)
                if observed_uptime is not None:
                    uptime = observed_uptime
            except (OSError, ValueError, OverflowError):
                pass
        return {
            "scope": "process",
            "cpu_cores": cores,
            "memory_rss_bytes": _read_rss_bytes(),
            "uptime_seconds": uptime if uptime is not None else 0.0,
            "sample_interval_seconds": interval,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
