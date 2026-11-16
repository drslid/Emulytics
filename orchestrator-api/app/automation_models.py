"""Editable recipes and frozen, timezone-aware execution schedules."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from .run_models import Contract, Identifier, Version, WorkflowStep


class RecipeInput(Contract):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    instructions: Annotated[str, Field(max_length=8000)] = ""
    steps: list[WorkflowStep] = Field(min_length=1, max_length=14)
    recovery_budget: int = Field(default=0, ge=0, le=20)

    @field_validator("name", "instructions", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_step_ids(self) -> Self:
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        return self


class RecipeUpdate(RecipeInput):
    revision: int = Field(ge=1, le=2_147_483_647)


class GoalInput(Contract):
    instructions: Annotated[str, Field(min_length=8, max_length=8000)]
    provider: Literal['openai', 'ollama', 'deepseek'] | None = None

    @field_validator('instructions', mode='before')
    @classmethod
    def trim_goal(cls, value):
        return value.strip() if isinstance(value, str) else value


class WorkflowRecipeInput(Contract):
    workflow_id: Identifier
    version: Version
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    instructions: Annotated[str | None, Field(max_length=8000)] = None

    @field_validator("name", "instructions", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class PublishInput(Contract):
    revision: int = Field(ge=1, le=2_147_483_647)


class PreviewInput(Contract):
    cron: Annotated[str, Field(min_length=1, max_length=120)]
    timezone: Annotated[str, Field(min_length=1, max_length=100)] = "Europe/Paris"

    @field_validator("cron", "timezone", mode="before")
    @classmethod
    def trim_text(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class ScheduleInput(PreviewInput):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    workflow_id: Identifier
    workflow_version: Version
    device_ids: list[Identifier] = Field(min_length=1, max_length=100)
    max_concurrency: int = Field(ge=1, le=100)
    enabled: bool = True
    request_id: Annotated[str | None, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")] = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError("Device IDs must be unique")
        if self.max_concurrency > len(self.device_ids):
            raise ValueError("max_concurrency cannot exceed the device count")
        return self


class ScheduleToggle(Contract):
    enabled: bool
