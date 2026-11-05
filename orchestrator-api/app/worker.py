"""Local deterministic worker: PostgreSQL lease, host lock and independent deadline."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from uuid import uuid4

import psycopg

from .execution_store import ExecutionStore


logger = logging.getLogger(__name__)


class LeaseLost(RuntimeError):
    pass


class ExecutionCancelled(RuntimeError):
    pass


@contextmanager
def device_lock(directory: Path, host_id: str, serial: str):
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(f"{host_id}\0{serial}".encode()).hexdigest()
    with (directory / f"{identity}.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        try:
            yield handle.fileno()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class LeaseWatchdog:
    """Keeps running while a database call blocks the execution thread."""

    def __init__(self, deadline: float, abort):
        self.deadline = deadline
        self.abort = abort
        self.expired = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self):
        while not self.stopped.wait(0.05):
            if time.monotonic() >= self.deadline:
                self.expired.set()
                self.abort()
                return

    def extend(self, deadline):
        if not self.expired.is_set():
            self.deadline = deadline

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=2)


class Worker:
    def __init__(self, dsn: str, host_id: str, *, lock_root=Path("/tmp/emulytix-device-locks"),
                 artifact_root=Path("/storage/runs"), apk_dir=None, ttl_seconds=30, driver_factory=None):
        if not host_id or not 3 <= ttl_seconds <= 300:
            raise ValueError("A host_id and lease TTL between 3 and 300 seconds are required")
        if driver_factory is None:
            from .android_driver import AndroidDriver
            driver_factory = AndroidDriver
        self.store = ExecutionStore(dsn)
        self.host_id = host_id
        self.owner_id = f"worker-{uuid4()}"
        self.lock_root = Path(lock_root)
        self.artifact_root = Path(artifact_root)
        self.apk_dir = Path(apk_dir) if apk_dir else None
        self.ttl = ttl_seconds
        self.driver_factory = driver_factory
        self.stopping = threading.Event()

    def run_once(self) -> bool:
        for candidate in self.store.candidates(self.host_id):
            if self.stopping.is_set():
                return False
            with device_lock(self.lock_root, self.host_id, candidate["serial"]) as lock_fd:
                if lock_fd is None:
                    continue
                requested_at = time.monotonic()
                grant = self.store.claim(candidate["id"], self.owner_id, self.ttl, host_id=self.host_id)
                if grant is None:
                    continue
                self._execute(grant, lock_fd, requested_at)
                return True
        return False

    def _execute(self, grant, lock_fd, requested_at):
        execution_id, epoch = grant["execution_id"], grant["lease_epoch"]
        current = {"step": None, "journal": None}
        timing = {"poll": 0.0, "renew": requested_at + self.ttl / 3}
        results = []
        driver = None
        watchdog = LeaseWatchdog(requested_at + self.ttl - 0.5, lambda: driver.abort() if driver else None)

        def check(force=False):
            if watchdog.expired.is_set() or time.monotonic() >= watchdog.deadline:
                raise LeaseLost("Local lease deadline reached")
            if self.stopping.is_set():
                raise ExecutionCancelled("Worker stopping")
            now = time.monotonic()
            if not force and now - timing["poll"] < 0.2:
                return
            state = self.store.state(execution_id, self.owner_id, epoch)
            timing["poll"] = time.monotonic()
            if watchdog.expired.is_set() or not state["valid"]:
                raise LeaseLost("Lease is no longer valid")
            if state["cancel_requested"]:
                raise ExecutionCancelled("Cancellation requested")
            if now >= timing["renew"]:
                renewal_started = time.monotonic()
                if not self.store.renew(execution_id, self.owner_id, epoch, self.ttl):
                    raise LeaseLost("Lease renewal rejected")
                watchdog.extend(renewal_started + self.ttl - 0.5)
                timing["renew"] = renewal_started + self.ttl / 3

        def before_command(argv, effectful):
            check(force=True)
            if not effectful:
                return
            step = current["step"]
            # The immutable workflow identifies arguments; typed text is not duplicated in logs.
            journal = self.store.before_action(execution_id, self.owner_id, epoch, step["id"],
                {"transport": "adb", "operation": argv[3] if len(argv) > 3 else "adb", "effectful": effectful},
                bool(effectful and step.get("non_idempotent", False)))
            if journal is None:
                raise LeaseLost("Action intent rejected")
            current["journal"] = journal
            if watchdog.expired.is_set() or time.monotonic() >= watchdog.deadline:
                raise LeaseLost("Lease expired while persisting action intent")

        def after_command(status, evidence):
            journal = current["journal"]
            if journal is not None:
                if not self.store.finish_action(execution_id, self.owner_id, epoch, journal, status, evidence):
                    raise LeaseLost("Action confirmation rejected")
                current["journal"] = None

        with watchdog:
            try:
                driver = self.driver_factory(grant["serial"], before_command, check,
                    self.artifact_root / str(execution_id) / str(epoch), lock_fd=lock_fd,
                    apk_dir=self.apk_dir, after_command=after_command)
                steps = grant["workflow"]["steps"]
                for step in steps:
                    driver.validate_step(step)
                for step in steps:
                    check(force=True)
                    current["step"] = step
                    evidence = driver.execute_step(step)
                    results.append({"step_id": step["id"], **evidence})
                check(force=True)
                if not self.store.finish(execution_id, self.owner_id, epoch, "succeeded", evidence={"steps": results}):
                    raise LeaseLost("Execution completion rejected")
                logger.info(json.dumps({"event": "execution.finished", "execution_id": str(execution_id), "status": "succeeded"}))
            except ExecutionCancelled:
                if driver:
                    driver.abort()
                self.store.finish(execution_id, self.owner_id, epoch, "cancelled", evidence={"steps": results})
            except (LeaseLost, psycopg.Error):
                if driver:
                    driver.abort()
                # Ownership is uncertain: reconciliation quarantines the device after expiry.
                logger.warning(json.dumps({"event": "execution.lease_lost", "execution_id": str(execution_id)}))
            except Exception as exc:
                if driver:
                    driver.abort()
                if watchdog.expired.is_set():
                    return
                self.store.finish(execution_id, self.owner_id, epoch, "failed", error=str(exc)[:512],
                                  evidence={"steps": results, "failed_step": current["step"]["id"] if current["step"] else None})

    def run(self, once=False, poll_seconds=1.0):
        while not self.stopping.is_set():
            try:
                worked = self.run_once()
            except psycopg.Error:
                logger.warning(json.dumps({"event": "worker.database_unavailable"}))
                worked = False
            if once:
                return
            if not worked:
                self.stopping.wait(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    dsn, host_id = os.getenv("EMULYTIX_DATABASE_URL", ""), os.getenv("EMULYTIX_HOST_ID", "")
    if not dsn or not host_id:
        parser.error("EMULYTIX_DATABASE_URL and EMULYTIX_HOST_ID are required")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    worker = Worker(dsn, host_id, lock_root=Path(os.getenv("EMULYTIX_LOCK_ROOT", "/host-locks")),
                    artifact_root=Path(os.getenv("EMULYTIX_ARTIFACT_ROOT", "/storage/runs")),
                    apk_dir=os.getenv("EMULYTIX_APK_ROOT"), ttl_seconds=int(os.getenv("EMULYTIX_LEASE_TTL", "30")))
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: worker.stopping.set())
    worker.run(once=args.once)


if __name__ == "__main__":
    main()
