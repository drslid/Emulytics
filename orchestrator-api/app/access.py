"""Small, shared authorization policy; UI capabilities never grant authority."""

import re
import unicodedata
import hashlib

from psycopg.types.json import Jsonb


READ_PERMISSIONS = {'devices.read', 'workflows.read', 'runs.read', 'schedules.read', 'monitor.read'}
ROLE_PERMISSIONS = {
    'admin': READ_PERMISSIONS | {'devices.write', 'workflows.write', 'workflows.publish', 'runs.execute', 'runs.cancel', 'schedules.write', 'logs.read', 'users.manage'},
    'builder': READ_PERMISSIONS | {'workflows.write', 'workflows.publish', 'runs.execute', 'runs.cancel', 'schedules.write'},
    'operator': READ_PERMISSIONS | {'devices.write', 'runs.execute', 'runs.cancel', 'schedules.write'},
    'viewer': READ_PERMISSIONS,
    'auditor': READ_PERMISSIONS | {'logs.read'},
}


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def normalize_username(value: str) -> str:
    """Keep the entered display label, derive a stable login even for non-Latin input."""
    value = value.strip()
    normalized = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    normalized = re.sub(r'[^a-z0-9_.-]+', '-', normalized).strip('_.-')[:64]
    if len(normalized) < 3:
        normalized = 'user-' + hashlib.sha256(value.casefold().encode()).hexdigest()[:10]
    return normalized


def required_permission(method: str, path: str) -> str | None:
    """Unknown routes are denied; new control routes must declare a capability here."""
    read = method in {'GET', 'HEAD'}
    account_methods = {
        '/console/account/security': {'GET', 'HEAD'},
        '/console/account/profile': {'GET', 'HEAD', 'PATCH'},
        '/console/account/password': {'POST'},
        '/console/account/two-factor/start': {'POST'},
        '/console/account/two-factor/enrollment': {'GET', 'HEAD', 'DELETE'},
        '/console/account/two-factor/enrollment/qr': {'GET', 'HEAD'},
        '/console/account/two-factor/confirm': {'POST'},
        '/console/account/recovery-codes': {'POST'},
    }
    if path in account_methods:
        return 'self' if method in account_methods[path] else None
    if path == '/auth/me':
        return 'self'
    if path == '/devices' or path == '/console/fleet':
        return 'devices.read' if read else 'devices.write'
    if re.fullmatch(r'/console/devices/[^/]+/screen', path):
        return 'devices.read' if read else None
    if re.fullmatch(r'/console/executions/[^/]+/screen', path):
        return 'runs.read' if read else None
    if path == '/workflows' or re.fullmatch(r'/workflows/[^/]+/versions/[0-9]+', path):
        return 'workflows.read' if read else 'workflows.publish'
    if path == '/console/recipes/from-workflow':
        return 'workflows.write' if method == 'POST' else None
    if path.startswith('/console/recipes'):
        return 'workflows.read' if read else 'workflows.publish' if path.endswith('/publish') else 'workflows.write'
    if path.startswith('/console/schedules'):
        return 'schedules.read' if read or path.endswith('/preview') else 'schedules.write'
    if path == '/runs':
        return 'runs.read' if read else 'runs.execute'
    if re.fullmatch(r'/runs/[^/]+/cancel', path):
        return 'runs.cancel'
    if re.fullmatch(r'/runs/[^/]+(?:/events)?', path) or re.fullmatch(r'/executions/[^/]+/actions', path):
        return 'runs.read' if read else None
    if re.fullmatch(r'/console/executions/[^/]+/captures/[^/]+', path):
        return 'runs.read' if read else None
    if path == '/console/summary' or path in {'/console/monitor', '/console/monitor/stream'}:
        return 'monitor.read' if read else None
    if path == '/console/logs':
        return 'logs.read' if read else None
    if path == '/console/users':
        return 'users.manage' if method in {'GET', 'HEAD', 'POST'} else None
    if re.fullmatch(r'/console/users/[^/]+', path):
        return 'users.manage' if method in {'GET', 'HEAD', 'PATCH'} else None
    if re.fullmatch(r'/console/users/[^/]+/(?:reset-password|reset-2fa|force-password-change|revoke-sessions)', path):
        return 'users.manage' if method == 'POST' else None
    if path in {'/docs', '/openapi.json', '/redoc'}:
        return 'users.manage' if read else None
    return None


# Only operational metadata with a reviewed shape can enter the journal. In particular
# request bodies, arguments, passwords, tokens and TOTP seeds are never audit metadata.
AUDIT_METADATA = {'role', 'previous_role', 'active', 'permission', 'status_code', 'workflow_id', 'workflow_version', 'device_count', 'revision', 'schedule_id', 'run_id'}


def audit_event(connection, actor_id, action: str, entity_id: str | None = None,
                metadata: dict | None = None, severity: str = 'info', category: str = 'security') -> None:
    safe = {key: value for key, value in (metadata or {}).items()
            if key in AUDIT_METADATA and (value is None or isinstance(value, (str, bool, int, float)))}
    connection.execute(
        'INSERT INTO audit_log(actor_id,action,entity_id,severity,category,metadata) VALUES(%s,%s,%s,%s,%s,%s)',
        (actor_id, action, entity_id, severity, category, Jsonb(safe)),
    )
