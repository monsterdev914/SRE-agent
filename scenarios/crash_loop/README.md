# CrashLoopBackOff scenario (missing env var)

This scenario deploys an app that **exits immediately** unless a required environment variable is set. The pod goes into `CrashLoopBackOff`; the SRE agent should detect the root cause from events/logs and remediate by patching the deployment with the missing env var.

## Quick start

1. Create a cluster (e.g. kind or minikube) and ensure `kubectl` is configured.
2. Deploy the **broken** manifest (no `REQUIRED_CONFIG`):
   ```bash
   kubectl apply -f manifests/deployment-broken.yaml
   ```
3. Confirm the pod is crashing:
   ```bash
   kubectl get pods -n sre-demo
   kubectl logs -n sre-demo -l app=crash-demo --tail=20
   ```
4. Run the agent (from repo root, with `OPENAI_API_KEY` or compatible LLM set):
   ```bash
   pip install -e .
   export SRE_AGENT_NAMESPACE=sre-demo
   sre-agent -n sre-demo
   ```
5. The agent should diagnose "missing REQUIRED_CONFIG" and patch the deployment; pods should become Ready.

## Manifests

- **deployment-broken.yaml** – Deployment that starts a container which exits with code 1 if `REQUIRED_CONFIG` is unset. Results in CrashLoopBackOff.
- **deployment-fixed.yaml** – Same deployment with `REQUIRED_CONFIG` set (for reference or manual fix).

## Reproducibility

After testing, reset with:
```bash
kubectl delete namespace sre-demo
kubectl apply -f manifests/crash_loop/deployment-broken.yaml
kubectl apply -f manifests/crash_loop/deployment-fixed.yaml
kubectl apply -f manifests/crash_loop/oom_deployment.yaml
kubectl apply -f manifests/crash_loop/namespace.yaml
```
