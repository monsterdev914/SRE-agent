"""LLM-based root cause analysis over cluster snapshots."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from sre_agent.config import Settings
from sre_agent.diagnosis.models import Diagnosis, RemediationAction, RemediationKind
from sre_agent.observation.models import ClusterSnapshot

logger = logging.getLogger(__name__)

DIAGNOSIS_SYSTEM_PROMPT = """You are an expert SRE analyzing Kubernetes cluster state to detect and diagnose operational issues.
You will receive a structured snapshot of pods, events, deployments, and pod logs from a single namespace.
Your task is to:
1. Determine if there is an operational issue (e.g. CrashLoopBackOff, OOMKilled, ImagePullBackOff, failing readiness, deployment not progressing).
2. Identify the root cause with clear evidence from the provided data (pod phase, container state reason/message, events, logs).
3. Propose one or more remediation actions that would resolve the issue.

Output MUST be valid JSON matching this schema (no markdown code fence, no extra text):
{
  "has_issue": true or false,
  "summary": "One-line summary",
  "root_cause": "Detailed explanation of root cause",
  "evidence": ["evidence 1", "evidence 2"],
  "remediation_actions": [
    {
      "kind": "patch_deployment_env" | "patch_deployment_resources" | "patch_deployment_image_or_cmd" | "scale_deployment" | "delete_pod" | "custom_instruction",
      "description": "What to do",
      "target": "deployment/<name> or pod/<name> or null",
      "params": { "key": "value" } or {},
      "reason": "Why this fixes it"
    }
  ],
  "confidence": 0.0 to 1.0
}

Use remediation kind "patch_deployment_env" when the issue is missing or wrong environment variables (put env name/value pairs in params).
Use "patch_deployment_resources" for memory/CPU request or limit changes (params: memory_limit, memory_request, cpu_limit, cpu_request as strings e.g. "128Mi", "100m").
Use "patch_deployment_image_or_cmd" for wrong image or command/args (params: image, command, args as needed).
Use "delete_pod" to force recreate a pod (target: pod/<name>).
Use "custom_instruction" when the fix is something the operator must do manually (describe in description and reason).
If no issue is found, set has_issue to false, summary to "No issue detected", and leave remediation_actions empty.
"""


def _openai_client(settings: Settings) -> OpenAI:
    """Build OpenAI client from settings (supports OpenAI and compatible endpoints)."""
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "temperature": settings.temperature,
    }
    if settings.llm_provider == "openai_compatible" and settings.openai_base_url:
        return OpenAI(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key or "not-needed",
        )
    return OpenAI(api_key=settings.openai_api_key or "")


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract JSON from model output, tolerating markdown code blocks."""
    text = raw.strip()
    # Remove optional markdown code block
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
        else:
            text = text.lstrip("`").strip()
    return json.loads(text)


def _parse_remediation_kind(s: str) -> RemediationKind:
    """Map string to RemediationKind enum."""
    try:
        return RemediationKind(s)
    except ValueError:
        return RemediationKind.CUSTOM_INSTRUCTION


def diagnose(snapshot: ClusterSnapshot, settings: Settings) -> Diagnosis:
    """Run LLM-based diagnosis on a cluster snapshot and return structured Diagnosis."""
    client = _openai_client(settings)
    user_content = snapshot.to_diagnostic_text()

    response = client.chat.completions.create(
        model=settings.model,
        temperature=settings.temperature,
        messages=[
            {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        data = _parse_llm_json(raw)
    except json.JSONDecodeError as e:
        logger.warning("LLM returned invalid JSON, defaulting to no-issue: %s", e)
        return Diagnosis(
            has_issue=False,
            summary="Diagnosis could not be parsed; no automated remediation.",
            root_cause="",
            evidence=[],
            remediation_actions=[],
            confidence=0.0,
        )

    actions = []
    for a in data.get("remediation_actions") or []:
        if isinstance(a, dict):
            actions.append(
                RemediationAction(
                    kind=_parse_remediation_kind(str(a.get("kind", "custom_instruction"))),
                    description=str(a.get("description", "")),
                    target=a.get("target"),
                    params=a.get("params") or {},
                    reason=str(a.get("reason", "")),
                )
            )
    return Diagnosis(
        has_issue=bool(data.get("has_issue", False)),
        summary=str(data.get("summary", "")),
        root_cause=str(data.get("root_cause", "")),
        evidence=[str(x) for x in (data.get("evidence") or [])],
        remediation_actions=actions,
        confidence=float(data.get("confidence", 0.0)),
    )
