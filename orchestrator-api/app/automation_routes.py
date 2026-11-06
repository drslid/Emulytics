"""Console recipe authoring and persisted schedule management."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from .automation_models import PreviewInput, PublishInput, RecipeInput, RecipeUpdate, ScheduleInput, ScheduleToggle
from .automation_store import AutomationStore, next_occurrences
from .run_routes import ControlRoute, Limit, Offset, Store


router = APIRouter(prefix="/console", tags=["Automations"], route_class=ControlRoute)


def _actor(request: Request):
    user = getattr(request.state, "auth_user", None)
    return UUID(str(user["id"])) if user else None


@router.get("/recipes")
def recipes(request: Request, store: Store, limit: Limit = 100, offset: Offset = 0):
    user = getattr(request.state, "auth_user", None)
    drafts = not user or "workflows.write" in user["permissions"]
    return AutomationStore(store.dsn).list_recipes(limit, offset, include_drafts=drafts)


@router.post("/recipes", status_code=201)
def create_recipe(payload: RecipeInput, request: Request, store: Store):
    return AutomationStore(store.dsn).create_recipe(payload, _actor(request))


@router.patch("/recipes/{recipe_id}")
def update_recipe(recipe_id: UUID, payload: RecipeUpdate, request: Request, store: Store):
    value = RecipeInput(**payload.model_dump(exclude={"revision"}, by_alias=True))
    return AutomationStore(store.dsn).update_recipe(recipe_id, payload.revision, value, _actor(request))


@router.post("/recipes/{recipe_id}/publish")
def publish_recipe(recipe_id: UUID, payload: PublishInput, request: Request, store: Store):
    return AutomationStore(store.dsn).publish_recipe(recipe_id, payload.revision, _actor(request))


@router.post("/schedules/preview")
def preview_schedule(payload: PreviewInput, store: Store):
    return {"cron": payload.cron, "timezone": payload.timezone, "next_runs": next_occurrences(payload.cron, payload.timezone),
            "dst_policy": "skip_nonexistent_first_fold_only"}


@router.get("/schedules")
def schedules(store: Store, limit: Limit = 100, offset: Offset = 0):
    return AutomationStore(store.dsn).list_schedules(limit, offset)


@router.post("/schedules", status_code=201)
def create_schedule(payload: ScheduleInput, request: Request, store: Store):
    actor = _actor(request)
    if actor is None:
        raise HTTPException(403, "Schedules require an authenticated execution owner")
    return AutomationStore(store.dsn).create_schedule(payload, actor)


@router.patch("/schedules/{schedule_id}")
def toggle_schedule(schedule_id: UUID, payload: ScheduleToggle, request: Request, store: Store):
    return AutomationStore(store.dsn).set_schedule_enabled(schedule_id, payload.enabled, _actor(request))


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: UUID, request: Request, store: Store):
    AutomationStore(store.dsn).delete_schedule(schedule_id, _actor(request))
    return Response(status_code=204)
