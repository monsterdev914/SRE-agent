# SRE Agent

A small **SRE agent** that detects, diagnoses, and resolves operational issues in a Kubernetes cluster. It observes cluster state (pods, events, logs), uses an LLM to reason about root cause, applies remediation (e.g. patch env, resources, delete pod), and verifies that the issue is resolved.

## Features

- **Observe & diagnose**: Inspect pods, deployments, events, and pod logs; identify failure conditions and root cause via an LLM.
- **Remediate**: Apply corrective actions (patch deployment env/resources, delete pod, scale) through the Kubernetes API.
- **Verify**: Check that pods are running and ready after remediation.
- **Communicate**: Produce a clear report (what went wrong, how it was detected, what was done, why it fixes the issue).

## Chosen failure scenario

**CrashLoopBackOff due to missing environment variable.**

- A deployment runs a container that **exits with code 1** if the env var `REQUIRED_CONFIG` is not set.
- The pod goes into `CrashLoopBackOff`; Kubernetes events and pod logs show the failure.
- The agent infers the root cause and remediates by patching the deployment to add `REQUIRED_CONFIG`.

The scenario is realistic, easy to reproduce, and fully detectable from standard Kubernetes signals. Manifests and instructions live under [`scenarios/crash_loop/`](scenarios/crash_loop/).

## Requirements

- Python 3.11+
- Access to a Kubernetes cluster (`kubectl` configured, e.g. kind, minikube, or remote).
- OpenAI API key (or an OpenAI-compatible endpoint, e.g. Ollama) for the LLM.

## Installation

```bash
cd /path/to/SRE-agent
pip install -e .
```

Optional: use a virtualenv.

## Configuration

Settings are read from the environment (prefix `SRE_AGENT_`) or a `.env` file in the current directory.

| Variable | Description | Default |
|----------|-------------|---------|
| `SRE_AGENT_NAMESPACE` | Kubernetes namespace | `default` |
| `SRE_AGENT_OPENAI_API_KEY` | OpenAI API key | — |
| `SRE_AGENT_OPENAI_BASE_URL` | Base URL for compatible API | — |
| `SRE_AGENT_LLM_PROVIDER` | `openai` or `openai_compatible` | `openai` |
| `SRE_AGENT_MODEL` | Model name | `gpt-4o-mini` |
| `SRE_AGENT_DRY_RUN` | Only diagnose, do not remediate | `false` |

Example for a local Ollama:

```bash
export SRE_AGENT_LLM_PROVIDER=openai_compatible
export SRE_AGENT_OPENAI_BASE_URL=http://localhost:11434/v1
export SRE_AGENT_MODEL=llama3.2
# API key can be dummy for Ollama
export SRE_AGENT_OPENAI_API_KEY=not-needed
```

## How to run

1. **Deploy the broken scenario** (optional; use your own failing workload otherwise):

   ```bash
   kubectl apply -f scenarios/crash_loop/manifests/deployment-broken.yaml
   ```

2. **Run the agent** in the same namespace:

   ```bash
   export SRE_AGENT_NAMESPACE=sre-demo
   export SRE_AGENT_OPENAI_API_KEY=sk-...
   sre-agent -n sre-demo
   ```

   Or with explicit flags:

   ```bash
   sre-agent --namespace sre-demo --kubeconfig ~/.kube/config
   ```

3. **Dry run** (diagnose only, no remediation):

   ```bash
   sre-agent -n sre-demo --dry-run
   ```

Exit code: `0` if no issue or issue resolved, `1` if issue remains, `2` on error.

## Example output

```
╭────────────────────── SRE Agent Report ──────────────────────╮
│ # SRE Agent Report                                            │
│                                                               │
│ ## What went wrong                                            │
│ Pod crash-demo is in CrashLoopBackOff due to missing env var  │
│                                                               │
│ **Root cause:** The container exits with code 1 because       │
│ REQUIRED_CONFIG is not set (see logs: "FATAL: REQUIRED_CONFIG │
│ is not set").                                                 │
│                                                               │
│ **Evidence:**                                                  │
│ - Pod phase not Running; container state waiting, reason      │
│   CrashLoopBackOff                                            │
│ - Event: BackOff restarting failed container                  │
│ - Logs: FATAL: REQUIRED_CONFIG is not set                     │
│                                                               │
│ ## Actions taken                                              │
│ - **Patched deployment crash-demo with env REQUIRED_CONFIG**:  │
│   OK — Patched deployment crash-demo with env vars:            │
│   ['REQUIRED_CONFIG']                                         │
│                                                               │
│ ## Verification                                               │
│ All pods running and ready; deployments satisfied.            │
╰───────────────────────────────────────────────────────────────╯

Confidence: 95%
```

## Project layout

```
SRE-agent/
├── README.md                 # This file
├── DESIGN.md                 # Design and architecture notes
├── pyproject.toml            # Project and dependencies
├── src/
│   └── sre_agent/
│       ├── __init__.py
│       ├── config.py         # Settings (env, pydantic-settings)
│       ├── main.py           # CLI entrypoint
│       ├── agent/            # Orchestration
│       │   ├── orchestrator.py
│       │   └── prompts.py
│       ├── observation/      # Cluster state collection
│       │   ├── collector.py
│       │   └── models.py
│       ├── diagnosis/        # LLM-based root cause analysis
│       │   ├── analyzer.py
│       │   └── models.py
│       └── remediation/      # Apply fixes and verify
│           └── actions.py
├── scenarios/
│   └── crash_loop/           # CrashLoopBackOff (missing env) scenario
│       ├── README.md
│       └── manifests/
└── tests/
```

## Design note

See [DESIGN.md](DESIGN.md) for architecture, data flow, and trade-offs.
