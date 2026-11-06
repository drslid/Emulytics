"""Small durable CRON dispatcher; runs in its own least-privilege container."""

import logging
import os
import signal
import threading

import psycopg

from .automation_store import AutomationStore
from .telemetry import service_heartbeat


logger = logging.getLogger(__name__)


def main():
    dsn = os.environ["EMULYTIX_DATABASE_URL"]
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store = AutomationStore(dsn)
    with service_heartbeat(dsn, "scheduler"):
        while not stopped.is_set():
            try:
                count = store.dispatch_due()
                if count:
                    logger.info("Submitted %s scheduled runs", count)
            except psycopg.Error as error:
                logger.error("Scheduler database unavailable (SQLSTATE %s)", error.sqlstate or "connection")
            except Exception:
                # No exception text: driver/request payloads and credentials are never logs.
                logger.error("Scheduler tick failed")
            stopped.wait(5)


if __name__ == "__main__":
    main()
