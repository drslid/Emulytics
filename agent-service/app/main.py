from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field


DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.4")
ALLOWED_MODELS = [
    item.strip()
    for item in os.getenv(
        "OPENAI_ALLOWED_MODELS",
        "gpt-5.4,gpt-5.4-mini,gpt-5.4-nano,gpt-4o-mini",
    ).split(",")
    if item.strip()
]

MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4",
        "tier": "frontier",
        "default": True,
        "reasoning": "high-quality planning and tool orchestration",
    },
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 Mini",
        "tier": "lower-cost",
        "default": False,
        "reasoning": "cheaper general-purpose planning",
    },
    {
        "id": "gpt-5.4-nano",
        "label": "GPT-5.4 Nano",
        "tier": "lowest-cost",
        "default": False,
        "reasoning": "very low-cost deterministic routing and light planning",
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o Mini",
        "tier": "economy",
        "default": False,
        "reasoning": "affordable small model for focused tasks",
    },
]


class PlanRequest(BaseModel):
    session_id: str
    prompt: str
    model: str = DEFAULT_MODEL
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    available_tools: list[str] = Field(default_factory=list)
    available_apks: list[str] = Field(default_factory=list)
    runtime_available: bool = False
    installed_packages: list[str] = Field(default_factory=list)
    openai_api_key: str | None = None


def allowed_models_catalog() -> list[dict[str, Any]]:
    return [entry for entry in MODEL_CATALOG if entry["id"] in ALLOWED_MODELS]


def heuristic_plan(payload: PlanRequest, reason: str) -> dict[str, Any]:
    lowered = payload.prompt.lower()
    steps: list[dict[str, Any]] = []

    if "install" in lowered and "apk" in lowered:
        file_name = payload.available_apks[0] if payload.available_apks else None
        steps.append({"tool": "install_latest_apk", "args": {"file_name": file_name}})

    uninstall_match = re.search(r"(?:uninstall|remove|delete)\s+([A-Za-z0-9._]+)", payload.prompt, re.IGNORECASE)
    if uninstall_match:
        steps.append({"tool": "uninstall_package", "args": {"package_name": uninstall_match.group(1)}})

    open_match = re.search(r"(?:open|launch)\s+([A-Za-z0-9._]+)", payload.prompt, re.IGNORECASE)
    if open_match:
        steps.append({"tool": "open_app", "args": {"package_name": open_match.group(1)}})

    if "home" in lowered:
        steps.append({"tool": "press_key", "args": {"keycode": "KEYCODE_HOME"}})
    if "back" in lowered:
        steps.append({"tool": "press_key", "args": {"keycode": "KEYCODE_BACK"}})
    if "recent" in lowered:
        steps.append({"tool": "press_key", "args": {"keycode": "KEYCODE_APP_SWITCH"}})
    if "screenshot" in lowered or "capture" in lowered:
        steps.append({"tool": "screenshot", "args": {}})

    if not steps:
        steps.append(
            {
                "tool": "manual_review",
                "args": {"reason": "No deterministic mapping found for the fallback planner."},
            }
        )

    return {
        "session_id": payload.session_id,
        "provider": "local-fallback",
        "summary": f"Fallback planner used. {reason}",
        "steps": steps,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def openai_plan(payload: PlanRequest) -> dict[str, Any]:
    api_key = payload.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return heuristic_plan(payload, "No OpenAI API key configured.")

    if payload.model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model '{payload.model}' is not allowed.")

    client = OpenAI(api_key=api_key)
    system_prompt = (
        "You are the Emulytix Android planner. "
        "Return only valid JSON with keys: summary, steps. "
        "Each step must be an object with keys: tool, args. "
        "Allowed tools are limited to the provided available_tools. "
        "Prefer deterministic tools. "
        "If Android runtime is unavailable, do not invent screen actions. "
        "If the user asks to install an APK and available_apks is non-empty, use install_latest_apk with the latest known file. "
        "If the user asks to remove an app, use uninstall_package with a concrete package name when available. "
        "If the request is ambiguous, return a single manual_review step."
    )
    user_prompt = json.dumps(
        {
            "prompt": payload.prompt,
            "runtime_available": payload.runtime_available,
            "available_tools": payload.available_tools,
            "available_apks": payload.available_apks,
            "installed_packages": payload.installed_packages[:200],
        }
    )

    response = client.responses.create(
        model=payload.model,
        reasoning={"effort": payload.reasoning_effort},
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = getattr(response, "output_text", "") or ""
    if not text:
        return heuristic_plan(payload, "OpenAI returned no text output.")

    try:
        parsed = extract_json_object(text)
    except Exception:
        return heuristic_plan(payload, "OpenAI output could not be parsed as JSON.")

    steps = parsed.get("steps")
    if not isinstance(steps, list) or not steps:
        return heuristic_plan(payload, "OpenAI returned an empty or invalid plan.")

    return {
        "session_id": payload.session_id,
        "provider": "openai",
        "model": payload.model,
        "summary": parsed.get("summary", "Structured plan generated by OpenAI."),
        "steps": steps,
    }


app = FastAPI(
    title="Emulytix Agent Service",
    description="Service de planification des actions en langage naturel.",
    version="0.2.0",
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "default_model": DEFAULT_MODEL,
        "configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.get("/models")
def models() -> dict[str, Any]:
    return {
        "default_model": DEFAULT_MODEL,
        "configured": bool(os.getenv("OPENAI_API_KEY")),
        "auth_mode": "api_key",
        "models": allowed_models_catalog(),
    }


@app.post("/plan")
def plan(payload: PlanRequest) -> dict[str, Any]:
    return openai_plan(payload)
