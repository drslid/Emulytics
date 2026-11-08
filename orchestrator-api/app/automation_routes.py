"""Console recipe authoring and persisted schedule management."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from .automation_models import GoalInput, PreviewInput, PublishInput, RecipeInput, RecipeUpdate, ScheduleInput, ScheduleToggle, WorkflowRecipeInput
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


@router.post('/recipes/generate')
def generate_recipe(payload: GoalInput, request: Request, store: Store):
    import json
    from .auth import AuthConfig, SESSION_COOKIE, auth_enabled
    from .journey_generation import local_goal, validate_generated_recipe
    from .journey_provider import JourneyProvider
    local = local_goal(payload.instructions)
    if local:
        return local
    if not auth_enabled():
        raise HTTPException(503, 'La génération libre exige une connexion personnelle ChatGPT.')
    provider = JourneyProvider(AuthConfig.load())
    user = provider.current_user(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(401, 'Connexion personnelle requise')
    provider.limit('journey-generation', str(user['id']), request.client.host if request.client else 'unknown', maximum=10)
    output = provider.generate(request.cookies.get(SESSION_COOKIE), payload.instructions)
    if (not isinstance(output, dict) or type(output.get('supported')) is not bool
            or not isinstance(output.get('reason'), str) or len(output['reason']) > 1000):
        raise HTTPException(422, 'La génération a produit une réponse invalide. Reformulez votre objectif.')
    if not output['supported']:
        raise HTTPException(422, {'code': 'unsupported_goal'})
    try:
        steps = json.loads(output['steps_json'])
        if not isinstance(steps, list) or not steps or steps[-1].get('action') not in {'screenshot', 'read_device_info'}:
            raise ValueError()
        if any(step.get('action') not in {'open_app', 'open_url', 'screenshot', 'press_key', 'ensure_package', 'open_settings', 'read_device_info'} for step in steps):
            raise ValueError()
        if any(step.get('action') == 'press_key' and step.get('args', {}).get('keycode') not in {'KEYCODE_HOME', 'KEYCODE_BACK'} for step in steps):
            raise ValueError()
        value = validate_generated_recipe({'name': output['name'], 'steps': steps, 'recovery_budget': 0}, payload.instructions)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(422, 'La génération ne fournit pas un parcours vérifiable. Précisez le résultat attendu.') from None
    return {'recipe': value, 'source': 'chatgpt', 'expected_result': output['reason'], 'requires_test': True,
            'capabilities': ['installed_apps', 'chrome', 'wikipedia', 'android_settings', 'android_version']}


@router.post("/recipes/from-workflow")
def recipe_from_workflow(payload: WorkflowRecipeInput, request: Request, store: Store):
    return AutomationStore(store.dsn).recipe_from_workflow(
        payload.workflow_id, payload.version, _actor(request), name=payload.name, instructions=payload.instructions,
    )


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
