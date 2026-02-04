# Design note: SRE Agent

## Goal

Build a **simple** agent that, given a Kubernetes cluster (local or remote), can:

1. **Observe** cluster state (pods, events, deployments, logs).
2. **Diagnose** failure conditions and root cause (with LLM-assisted reasoning).
3. **Remediate** by applying corrective actions via the Kubernetes API.
4. **Verify** that the issue is resolved and **communicate** a clear report.

The scope is deliberately limited: no UI, no learning loops, no production-grade auth/scale. The focus is on problem-solving approach, clean design, and effective use of AI for diagnosis and remediation.

## Architecture

High-level flow:

```
  Observe          Diagnose           Remediate          Verify
  ───────          ────────           ─────────          ───────
  Cluster    →     LLM-based    →     K8s API      →     Health
  snapshot         root cause         patches            check
                   + actions
```

- **Observation** is pure data collection: no AI. We gather a bounded snapshot (one namespace: pods, events, deployments, and logs only for non-healthy pods) and serialize it to a structured text representation for the LLM.
- **Diagnosis** is LLM-only: one prompt with the snapshot and strict JSON output (has_issue, summary, root_cause, evidence, remediation_actions, confidence). We parse that into a `Diagnosis` model and map suggested actions to an enum (e.g. `patch_deployment_env`, `patch_deployment_resources`, `delete_pod`).
- **Remediation** is deterministic code: for each suggested action we call the Kubernetes API (patch deployment env/resources, delete pod, etc.). No LLM in the loop here to keep behavior predictable and auditable.
- **Verification** is a simple health check: all pods in the namespace Running and Ready, deployments with ready_replicas == desired.

This keeps **AI in the loop only for interpretation and planning**; execution and verification are standard Kubernetes client calls, which makes the system easier to reason about and test.

## Design choices

### Layered structure

- **observation**: models for Pod/Event/Deployment summaries and a `ClusterSnapshot`; one collector that uses the official Kubernetes Python client. Snapshot is namespace-scoped to keep scope small and avoid token explosion.
- **diagnosis**: one function that takes `ClusterSnapshot` + settings and returns a `Diagnosis` (Pydantic). Prompts are in code; the LLM is instructed to return JSON that we parse and validate.
- **remediation**: one module that takes a `RemediationAction` and executes it (patch env, patch resources, delete pod, etc.). All actions are explicit and implemented in code; we do not generate arbitrary kubectl commands.
- **agent**: orchestrator runs observe → diagnose → (optionally) remediate → verify and builds a text report from templates.

This separation makes it easy to test observation and remediation with a real cluster or mocks, and to swap or tune the diagnosis prompt/model without touching the rest.

### Failure scenario

We chose **CrashLoopBackOff due to a missing required environment variable** because:

- It is **realistic** (misconfiguration is a common cause of crashes).
- It is **easy to reproduce** (one deployment YAML; no external services).
- It is **clearly detectable**: pod phase, container state reason/message, events (BackOff, Failed), and pod logs all point to “container exits because REQUIRED_CONFIG is not set.”
- Remediation is **well-defined**: add the env var to the deployment (we support `patch_deployment_env` and the LLM returns the right action and params).

Other scenarios (OOMKilled, ImagePullBackOff, wrong image) could be added with the same pipeline; the only change would be manifests and possibly new remediation action types.

### LLM usage

- **Single shot**: we do one diagnosis call per run. We do not iterate with the LLM on “try again if verification failed” in this minimal version, to keep complexity and latency low.
- **Structured output**: we require JSON and parse it into Pydantic. We tolerate markdown code fences and strip them before parsing. On parse failure we return a safe “no issue” diagnosis so the agent does not crash.
- **Confidence**: we ask for a confidence score and surface it in the report; we do not use it to gate remediation in the current implementation.

### Safety and operability

- **Dry run**: `--dry-run` (or `SRE_AGENT_DRY_RUN=true`) runs observe and diagnose only; no patches or deletes. Useful to see what the agent would do.
- **Bounded remediation**: we apply at most `max_remediation_attempts` (default 2) actions per run to avoid runaway changes.
- **Explicit action kinds**: remediation is limited to a fixed set (patch deployment env/resources/image-or-cmd, scale, delete pod, custom_instruction). We do not execute free-form shell or arbitrary YAML.

## Possible extensions

- **More remediation types**: e.g. patch ConfigMap/Secret and rollout restart.
- **Retry loop**: if verification fails after remediation, optionally re-observe and re-diagnose (with a cap on attempts).
- **Multiple namespaces or label selectors**: currently we scope to one namespace to keep snapshots small and costs predictable.
- **Caching / idempotency**: avoid re-patching if the same fix was already applied (e.g. by comparing desired vs current env).

## Dependencies

- **kubernetes**: official Python client for cluster access.
- **openai**: client for OpenAI (and compatible) APIs.
- **pydantic / pydantic-settings**: structured config and models.
- **rich**: formatted CLI output.

All are common, well-maintained libraries suitable for a small, senior-level implementation.
