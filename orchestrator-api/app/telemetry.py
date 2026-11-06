"""Small persisted liveness signals, independent of long-running Android actions."""
import logging
import os
import socket
import threading
from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


def heartbeat(dsn, component, instance_id, host_id=None, status="ready", metrics=None):
    with psycopg.connect(dsn, connect_timeout=2) as connection:
        connection.execute("SET LOCAL statement_timeout = '2s'")
        connection.execute(
            "INSERT INTO service_heartbeats(component,instance_id,host_id,status,metrics) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT(component,instance_id) DO UPDATE SET host_id=EXCLUDED.host_id,status=EXCLUDED.status,"
            "metrics=EXCLUDED.metrics,last_seen_at=clock_timestamp()",
            (component, instance_id, host_id, status, Jsonb(metrics or {})),
        )


@contextmanager
def service_heartbeat(dsn, component, instance_id=None, host_id=None):
    stopped = threading.Event()
    identity = instance_id or socket.gethostname()
    def report():
        while not stopped.is_set():
            try:
                heartbeat(dsn, component, identity, host_id)
            except psycopg.Error:
                logger.warning('service.heartbeat_unavailable component=%s', component)
            stopped.wait(5)
    enabled = bool(dsn) and os.getenv("EMULYTIX_TELEMETRY_ENABLED", "false").lower() == "true"
    thread = threading.Thread(target=report, daemon=True, name=f"heartbeat-{component}") if enabled else None
    if thread:
        thread.start()
    try:
        yield
    finally:
        stopped.set()
        if thread:
            thread.join(timeout=3)
