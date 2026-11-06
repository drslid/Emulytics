"""Persistent editable drafts and schedules. Scheduling never talks to a device."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter, CroniterBadCronError, CroniterBadDateError
from fastapi import HTTPException
import psycopg
from psycopg.types.json import Jsonb

from .access import audit_event, permissions_for
from .android_driver import AndroidDriver, DriverError
from .automation_models import RecipeInput, ScheduleInput
from .run_models import RunSubmission, WorkflowRegistration
from .run_store import RunStore, fingerprint


def next_occurrences(expression: str, zone: str, after: datetime | None = None, count: int = 5) -> list[datetime]:
    """Five-field wall-clock CRON; skip absent DST times, first fold only.

    Generate naive local candidates, then validate them against the IANA zone.
    This makes DST policy explicit instead of relying on implicit fold behavior.
    CPU work is bounded even for impossible dates or hostile expressions.
    """
    expression = " ".join(expression.split())
    randomized = any(word.upper() in {"R", "H"} for word in re.findall(r"[A-Za-z]+", expression))
    if len(expression) > 120 or len(expression.split()) != 5 or not 1 <= count <= 5 or randomized:
        raise HTTPException(422, "Use a five-field CRON expression")
    try:
        tz = ZoneInfo(zone)
        base = after or datetime.now(timezone.utc)
        if base.tzinfo is None:
            raise ValueError("A timezone-aware starting time is required")
        base = base.astimezone(timezone.utc)
        iterator = croniter(expression, base.astimezone(tz).replace(tzinfo=None), max_years_between_matches=8)
        result = []
        for _ in range(5000):
            local = iterator.get_next(datetime)
            instant = local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
            if instant > base and instant.astimezone(tz).replace(tzinfo=None) == local:
                result.append(instant)
                if len(result) == count:
                    return result
    except (ZoneInfoNotFoundError, CroniterBadCronError, CroniterBadDateError, ValueError, OverflowError):
        pass
    raise HTTPException(422, "Invalid CRON expression or IANA timezone; no occurrence in the next eight years")


def _recipe_view(row: dict) -> dict:
    return {**{key: value for key, value in row.items() if key != "published_revision"},
            "status": "published" if row["published_revision"] == row["revision"] else "draft"}


class AutomationStore(RunStore):
    @staticmethod
    def _definition(recipe: RecipeInput) -> dict:
        return recipe.model_dump(mode="json", by_alias=True, include={"steps", "recovery_budget"})

    def create_recipe(self, recipe: RecipeInput, actor_id: UUID | None) -> dict:
        recipe_id = uuid4()
        slug = unicodedata.normalize("NFKD", recipe.name).encode("ascii", "ignore").decode().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:70] or "workflow"
        with self.connect() as connection:
            row = connection.execute(
                "INSERT INTO automation_recipes(id,workflow_id,name,instructions,definition,created_by) "
                "VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (recipe_id, f"{slug}-{recipe_id.hex[:12]}", recipe.name, recipe.instructions, Jsonb(self._definition(recipe)), actor_id),
            ).fetchone()
            audit_event(connection, actor_id, "recipe.created", str(recipe_id), {"revision": 1}, category="automation")
            return _recipe_view(row)

    def recipe_from_workflow(self, workflow_id: str, version: int, actor_id: UUID | None,
                             *, name: str | None = None, instructions: str | None = None) -> dict:
        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM automation_recipes WHERE workflow_id=%s", (workflow_id,)).fetchone()
            if existing is not None:
                return _recipe_view(existing)
            source = connection.execute(
                "SELECT w.definition,p.name,p.instructions FROM workflows w "
                "LEFT JOIN automation_publications p ON p.workflow_id=w.workflow_id AND p.version=w.version "
                "WHERE w.workflow_id=%s AND w.version=%s", (workflow_id, version),
            ).fetchone()
            if source is None:
                raise HTTPException(404, "Workflow version not found")
            latest = connection.execute("SELECT MAX(version) AS version FROM workflows WHERE workflow_id=%s", (workflow_id,)).fetchone()["version"]
            definition = {"steps": source["definition"]["steps"], "recovery_budget": source["definition"].get("recovery_budget", 0)}
            row = connection.execute(
                "INSERT INTO automation_recipes(id,workflow_id,name,instructions,definition,latest_version,created_by) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workflow_id) DO NOTHING RETURNING *",
                (uuid4(), workflow_id, source["name"] if source["name"] is not None else name or workflow_id[:120],
                 source["instructions"] if source["instructions"] is not None else instructions or "", Jsonb(definition), latest, actor_id),
            ).fetchone()
            if row is None:
                # Another editor opened this workflow first; keep that draft intact.
                row = connection.execute("SELECT * FROM automation_recipes WHERE workflow_id=%s", (workflow_id,)).fetchone()
            else:
                audit_event(connection, actor_id, "recipe.created", str(row["id"]),
                            {"workflow_id": workflow_id, "workflow_version": version, "revision": 1}, category="automation")
            return _recipe_view(row)

    def list_recipes(self, limit: int, offset: int, *, include_drafts: bool = True) -> dict:
        # Readers cannot retrieve unpublished instructions or unpublished draft definitions.
        # Executable catalog /workflows remains the source for operator/viewer roles.
        if not include_drafts:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM automation_recipes ORDER BY updated_at DESC,id LIMIT %s OFFSET %s", (limit, offset)).fetchall()
            total = connection.execute("SELECT count(*) AS n FROM automation_recipes").fetchone()["n"]
            return {"items": [_recipe_view(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def update_recipe(self, recipe_id: UUID, revision: int, recipe: RecipeInput, actor_id: UUID | None) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "UPDATE automation_recipes SET name=%s,instructions=%s,definition=%s,revision=revision+1,updated_at=clock_timestamp() "
                "WHERE id=%s AND revision=%s RETURNING *",
                (recipe.name, recipe.instructions, Jsonb(self._definition(recipe)), recipe_id, revision),
            ).fetchone()
            if row is None:
                exists = connection.execute("SELECT 1 FROM automation_recipes WHERE id=%s", (recipe_id,)).fetchone()
                raise HTTPException(409 if exists else 404, "Draft changed; reload before saving" if exists else "Recipe not found")
            audit_event(connection, actor_id, "recipe.updated", str(recipe_id), {"revision": row["revision"]}, category="automation")
            return _recipe_view(row)

    def publish_recipe(self, recipe_id: UUID, revision: int, actor_id: UUID | None) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM automation_recipes WHERE id=%s FOR UPDATE", (recipe_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Recipe not found")
            if row["revision"] != revision:
                raise HTTPException(409, "Draft changed; reload before publishing")
            if row["published_revision"] == revision:
                return _recipe_view(row)
            latest = connection.execute("SELECT MAX(version) AS version FROM workflows WHERE workflow_id=%s", (row["workflow_id"],)).fetchone()["version"]
            version = max(row["latest_version"] or 0, latest or 0) + 1
            definition = WorkflowRegistration(workflow_id=row["workflow_id"], version=version, **row["definition"]).model_dump(mode="json", by_alias=True)
            try:
                for step in definition["steps"]:
                    AndroidDriver.validate_step(step)
                    if step.get("verify_after_crash") is not None:
                        AndroidDriver.validate_assertion(step["verify_after_crash"])
                    if step.get("recovery_actions"):
                        raise DriverError("Recovery actions require a configured recovery provider")
                    if step.get("when") is None:
                        step.pop("when", None)
            except DriverError as error:
                raise HTTPException(422, str(error)) from None
            try:
                connection.execute(
                    "INSERT INTO workflows(workflow_id,version,definition,content_hash) VALUES(%s,%s,%s,%s)",
                    (row["workflow_id"], version, Jsonb(definition), fingerprint(definition)),
                )
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409, "Workflow changed; retry publishing a new version") from None
            connection.execute(
                "INSERT INTO automation_publications(workflow_id,version,name,instructions) VALUES(%s,%s,%s,%s)",
                (row["workflow_id"], version, row["name"], row["instructions"]),
            )
            row = connection.execute(
                "UPDATE automation_recipes SET latest_version=%s,published_revision=revision,updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (version, recipe_id),
            ).fetchone()
            audit_event(connection, actor_id, "recipe.published", str(recipe_id), {"workflow_id": row["workflow_id"], "workflow_version": version, "revision": revision}, category="automation")
            return _recipe_view(row)

    @staticmethod
    def _authorized_owner(connection, owner_id: UUID | None) -> bool:
        if owner_id is None:
            return False
        owner = connection.execute(
            "SELECT active,role,totp_enabled,password_change_required FROM auth_users WHERE id=%s FOR SHARE", (owner_id,),
        ).fetchone()
        return bool(owner and owner["active"] and owner["totp_enabled"] and not owner["password_change_required"] and "runs.execute" in permissions_for(owner["role"]))

    def create_schedule(self, schedule: ScheduleInput, actor_id: UUID) -> dict:
        schedule_id = UUID(schedule.request_id) if schedule.request_id else uuid4()
        values = schedule.model_dump(exclude={"request_id"})

        def replay(row):
            if row["created_by"] != actor_id or any(row[key] != value for key, value in values.items()):
                raise HTTPException(409, "Schedule request ID was already used with different content or owner")
            return row

        with self.connect() as connection:
            previous = connection.execute("SELECT * FROM automation_schedules WHERE id=%s", (schedule_id,)).fetchone()
            if previous is not None:
                return replay(previous)
            if not self._authorized_owner(connection, actor_id):
                raise HTTPException(403, "An active authenticated execution owner is required")
            next_run = next_occurrences(schedule.cron, schedule.timezone, count=1)[0]
            if not connection.execute("SELECT 1 FROM workflows WHERE workflow_id=%s AND version=%s", (schedule.workflow_id, schedule.workflow_version)).fetchone():
                raise HTTPException(404, "Workflow version not found")
            found = connection.execute("SELECT device_id FROM devices WHERE device_id=ANY(%s)", (schedule.device_ids,)).fetchall()
            if len(found) != len(schedule.device_ids):
                raise HTTPException(404, "One or more devices are not registered")
            row = connection.execute(
                "INSERT INTO automation_schedules(id,name,workflow_id,workflow_version,device_ids,max_concurrency,cron,timezone,enabled,created_by,next_run_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING *",
                (schedule_id, schedule.name, schedule.workflow_id, schedule.workflow_version, Jsonb(schedule.device_ids), schedule.max_concurrency,
                 schedule.cron, schedule.timezone, schedule.enabled, actor_id, next_run),
            ).fetchone()
            if row is None:
                return replay(connection.execute("SELECT * FROM automation_schedules WHERE id=%s", (schedule_id,)).fetchone())
            audit_event(connection, actor_id, "schedule.created", str(row["id"]), {"workflow_id": schedule.workflow_id, "workflow_version": schedule.workflow_version, "device_count": len(schedule.device_ids)}, category="automation")
            return row

    def list_schedules(self, limit: int, offset: int) -> dict:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM automation_schedules ORDER BY created_at DESC,id LIMIT %s OFFSET %s", (limit, offset)).fetchall()
            total = connection.execute("SELECT count(*) AS n FROM automation_schedules").fetchone()["n"]
            return {"items": rows, "total": total, "limit": limit, "offset": offset}

    def set_schedule_enabled(self, schedule_id: UUID, enabled: bool, actor_id: UUID | None) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM automation_schedules WHERE id=%s FOR UPDATE", (schedule_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Schedule not found")
            if enabled and not self._authorized_owner(connection, row["created_by"]):
                raise HTTPException(409, "Schedule owner no longer has permission to execute")
            # Resume starts at the next future occurrence; paused slots are never replayed.
            next_run = next_occurrences(row["cron"], row["timezone"], count=1)[0] if enabled and not row["enabled"] else row["next_run_at"]
            updated = connection.execute(
                "UPDATE automation_schedules SET enabled=%s,next_run_at=%s,last_error=NULL,updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (enabled, next_run, schedule_id),
            ).fetchone()
            audit_event(connection, actor_id, "schedule.resumed" if enabled else "schedule.paused", str(schedule_id), category="automation")
            return updated

    def delete_schedule(self, schedule_id: UUID, actor_id: UUID | None) -> None:
        with self.connect() as connection:
            row = connection.execute("DELETE FROM automation_schedules WHERE id=%s RETURNING id", (schedule_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Schedule not found")
            audit_event(connection, actor_id, "schedule.deleted", str(schedule_id), category="automation")

    def _after_submission(self, schedule: dict, run: dict) -> None:
        """Fault-injection boundary: run commit happened, schedule cursor did not."""

    def dispatch_due(self, limit: int = 20) -> int:
        submitted = 0
        with self.connect() as connection:
            due = connection.execute(
                "SELECT * FROM automation_schedules WHERE enabled AND next_run_at<=clock_timestamp() "
                "ORDER BY next_run_at,id LIMIT %s FOR UPDATE SKIP LOCKED", (max(1, min(limit, 100)),),
            ).fetchall()
            for row in due:
                if not self._authorized_owner(connection, row["created_by"]):
                    connection.execute("UPDATE automation_schedules SET enabled=false,last_error='owner_not_authorized',updated_at=clock_timestamp() WHERE id=%s", (row["id"],))
                    audit_event(connection, row["created_by"], "schedule.blocked", str(row["id"]), severity="warning", category="automation")
                    continue
                due_key = row["next_run_at"].astimezone(timezone.utc).isoformat()
                payload = RunSubmission(workflow_id=row["workflow_id"], workflow_version=row["workflow_version"], device_ids=row["device_ids"],
                                        max_concurrency=row["max_concurrency"], idempotency_key=f"schedule:{row['id']}:{due_key}")
                try:
                    # Separate committed transaction: replay of this exact due slot survives
                    # a process crash before the schedule cursor transaction commits.
                    run = RunStore(self.dsn).submit_run(payload)
                except (HTTPException, psycopg.Error):
                    connection.execute("UPDATE automation_schedules SET last_error='dispatch_failed',updated_at=clock_timestamp() WHERE id=%s", (row["id"],))
                    continue
                self._after_submission(row, run)
                now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
                next_run = next_occurrences(row["cron"], row["timezone"], now, count=1)[0]
                connection.execute(
                    "UPDATE automation_schedules SET next_run_at=%s,last_run_id=%s,last_error=NULL,updated_at=clock_timestamp() WHERE id=%s",
                    (next_run, run["id"], row["id"]),
                )
                audit_event(connection, row["created_by"], "schedule.dispatched", str(row["id"]), {"run_id": str(run["id"]), "workflow_id": row["workflow_id"], "workflow_version": row["workflow_version"]}, category="automation")
                submitted += 1
        return submitted
