"""Structured outputs from the diagnosis layer."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RemediationKind(str, Enum):
    """Supported remediation action types."""

    PATCH_DEPLOYMENT_ENV = "patch_deployment_env"
    PATCH_DEPLOYMENT_RESOURCES = "patch_deployment_resources"
    PATCH_DEPLOYMENT_IMAGE_OR_CMD = "patch_deployment_image_or_cmd"
    SCALE_DEPLOYMENT = "scale_deployment"
    DELETE_POD = "delete_pod"
    CUSTOM_INSTRUCTION = "custom_instruction"


class RemediationAction(BaseModel):
    """A single suggested remediation step."""

    kind: RemediationKind
    description: str = Field(..., description="Human-readable description of the action")
    target: str | None = Field(default=None, description="Target resource, e.g. deployment/myapp")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action parameters, e.g. env vars, resource limits",
    )
    reason: str = Field(default="", description="Why this action is expected to fix the issue")


class Diagnosis(BaseModel):
    """Result of root-cause analysis."""

    has_issue: bool = Field(..., description="Whether an operational issue was detected")
    summary: str = Field(..., description="One-line summary of the issue (or 'No issue detected')")
    root_cause: str = Field(
        default="",
        description="Explanation of the root cause (e.g. missing env var, OOMKilled, CrashLoopBackOff reason)",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Specific evidence from cluster state (pod status, events, logs)",
    )
    remediation_actions: list[RemediationAction] = Field(
        default_factory=list,
        description="Ordered list of suggested remediation steps",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the diagnosis (0-1)",
    )
