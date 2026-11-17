"""Read the minimum Android facts needed to plan against an optional device."""

import re

from fastapi import HTTPException

from .apk_catalog import PACKAGE_NAME_PATTERN
from .emulator_store import PRESETS
from .run_store import RunStore


def journey_context(store: RunStore, device_id: str | None) -> dict:
    context = {'reference_apps': {name: package for name, package, _ in PRESETS.values()}}
    if device_id is None:
        return context
    with store.connect() as connection:
        record = connection.execute(
            "SELECT d.kind AS device_kind, CASE WHEN m.state IN ('running','ready') AND r.status='succeeded' "
            "AND l.owner_id IS NULL AND NOT COALESCE(l.quarantined,false) THEN m.installed_packages END AS installed_packages "
            "FROM devices d LEFT JOIN managed_emulators m USING(device_id) LEFT JOIN runs r ON r.id=m.last_run_id "
            "LEFT JOIN device_leases l USING(device_id) WHERE d.device_id=%s",
            (device_id,),
        ).fetchone()
    if record is None:
        raise HTTPException(404, 'Device not found')
    observed = record['installed_packages']
    packages = None
    if isinstance(observed, list):
        packages = sorted({package for package in observed if isinstance(package, str) and len(package) <= 200
                           and re.fullmatch(PACKAGE_NAME_PATTERN, package)})[:24]
    return {**context, 'device_kind': record['device_kind'], 'installed_packages': packages}
