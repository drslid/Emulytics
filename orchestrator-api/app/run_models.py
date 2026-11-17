"""Contracts for durable run submission; these models do not execute Android actions."""

import math
import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Version = Annotated[int, Field(ge=1, le=2_147_483_647)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_postgres_json(self) -> Self:
        # Recursive JsonValue does not inherit the model's scalar constraints.
        pending = [self.model_dump(mode="python", by_alias=True)]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                if "\x00" in value:
                    raise ValueError("JSON strings cannot contain NUL")
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError("JSON strings must contain valid Unicode scalar values") from None
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("JSON numbers must be finite")
        return self


class DeviceRegistration(Contract):
    @model_validator(mode="before")
    @classmethod
    def normalize_names(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        original = value.get("device_id")
        if isinstance(original, str):
            label = original.strip()
            slug = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
            # Preserve valid existing identities, including case, when reading DeviceView.
            # Human labels accept punctuation as well as spaces and non-Latin scripts.
            friendly = any(c.isspace() for c in label) or slug != label or "display_name" in value
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", label) and friendly:
                normalized = re.sub(r"[^a-z0-9_.:-]+", "-", slug.lower()).strip("_.:-")[:128]
                value["device_id"] = normalized or "device-" + hashlib.sha256(label.encode()).hexdigest()[:12]
            else:
                value["device_id"] = label
            value.setdefault("display_name", label)
        if isinstance(value.get("display_name"), str):
            value["display_name"] = value["display_name"].strip()
        for key in ("host_id", "serial"):
            if isinstance(value.get(key), str):
                value[key] = value[key].strip()
        return value

    device_id: Identifier
    display_name: Annotated[str, Field(min_length=1, max_length=160)] = ""
    host_id: Identifier
    serial: Identifier
    kind: Literal["physical", "emulator"]


class WorkflowStep(Contract):
    id: Identifier
    action: Literal["press_key", "open_app", "tap", "swipe", "type_text", "screenshot", "ensure_package", "open_url", "open_settings", "read_device_info"]
    args: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    selectors: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=8)
    timeout_ms: int = Field(default=10_000, ge=1, le=300_000)
    assertion: dict[str, JsonValue] = Field(alias="assert", min_length=1, max_length=16)
    non_idempotent: bool = False
    recovery_budget: int = Field(default=0, ge=0, le=5)
    recovery_actions: list[str] = Field(default_factory=list, max_length=10)
    verify_after_crash: dict[str, JsonValue] | None = None
    when: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def require_effect_verification(self) -> Self:
        if self.non_idempotent and not self.verify_after_crash:
            raise ValueError("Non-idempotent steps require verify_after_crash")
        return self


class NaturalCard(Contract):
    id: Identifier
    instruction: Annotated[str, Field(min_length=1, max_length=1500)]
    verification: Annotated[str, Field(min_length=1, max_length=1500)] | None = None

    @field_validator("instruction", "verification", mode="before")
    @classmethod
    def trim_text(cls, value, info):
        if isinstance(value, str):
            value = value.strip()
            if info.field_name == "verification" and not value:
                return None
        return value


def _unique_card_ids(cards: list[NaturalCard]) -> list[NaturalCard]:
    if len({card.id for card in cards}) != len(cards):
        raise ValueError("Card IDs must be unique")
    return cards


NaturalCards = Annotated[list[NaturalCard], Field(min_length=1, max_length=14), AfterValidator(_unique_card_ids)]


class WorkflowRegistration(Contract):
    workflow_id: Identifier
    version: Version
    steps: list[WorkflowStep] = Field(min_length=1, max_length=14)
    recovery_budget: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def unique_steps(self) -> Self:
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        return self


class RunSubmission(Contract):
    workflow_id: Identifier
    workflow_version: Version
    device_ids: list[Identifier] = Field(min_length=1, max_length=100)
    max_concurrency: int = Field(ge=1, le=100)
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S+$")]
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError("Device IDs must be unique")
        if self.max_concurrency > len(self.device_ids):
            raise ValueError("max_concurrency cannot exceed the device count")
        return self


RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "needs_review", "waiting_auth"]
ExecutionStatus = Literal[
    "queued", "leased", "running", "recovering", "verifying_state", "waiting_auth",
    "needs_review", "succeeded", "failed", "cancelled",
]


class DeviceView(DeviceRegistration):
    status: Literal["registered"]
    created_at: datetime


class WorkflowView(WorkflowRegistration):
    created_at: datetime
    deleted_at: datetime | None = None
    name: str | None = None
    instructions: str | None = None
    cards: NaturalCards | None = None


class ExecutionView(BaseModel):
    id: UUID
    run_id: UUID
    device_id: str
    status: ExecutionStatus
    attempt: int
    created_at: datetime
    updated_at: datetime
    lease_epoch: int | None = None
    error: str | None = None
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class RunSummary(BaseModel):
    id: UUID
    workflow_id: str
    workflow_version: int
    device_ids: list[str]
    max_concurrency: int
    status: RunStatus
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime


class RunDetail(RunSummary):
    run_id: UUID
    parameters: dict[str, JsonValue]
    idempotency_key: str
    executions: list[ExecutionView]


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int


class RunEvent(BaseModel):
    run_id: UUID
    sequence: int
    type: str
    payload: dict[str, JsonValue]
    created_at: datetime


class EventPage(BaseModel):
    items: list[RunEvent]
    limit: int
    after: int


class ActionView(BaseModel):
    id: UUID
    execution_id: UUID
    step_id: str
    lease_epoch: int
    action: dict[str, JsonValue]
    non_idempotent: bool
    status: Literal["intent", "done", "failed", "cancelled", "uncertain"]
    evidence: dict[str, JsonValue]
    started_at: datetime
    finished_at: datetime | None
