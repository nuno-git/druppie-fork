# Autoscaling Test Suite

Automated tests for verifying HPA (Horizontal Pod Autoscaler) and Cluster Autoscaler behavior on Hetzner K3s.

## Prerequisites

1. **Cluster with autoscaling enabled** — HPA must be enabled in your Helm values:
   ```bash
   # Check current state
   kubectl get hpa -n druppie
   ```

2. **metrics-server** — Required for HPA to read CPU metrics:
   ```bash
   kubectl get deployment metrics-server -n kube-system
   ```

3. **hey** (for load tests only) — HTTP load generator:
   ```bash
   go install github.com/rakyll/hey@latest
   # or: brew install hey
   ```

4. **kubectl** — Scripts auto-detect the Hetzner cluster kubeconfig from `./kubeconfig` in the project root. No setup needed. To override:
   ```bash
   export KUBECONFIG=/path/to/other/kubeconfig
   ```

## Test Scripts

| Script | Purpose | Duration | When to Run |
|--------|---------|----------|-------------|
| `test-hpa.sh` | Quick HPA scale-up/scale-down smoke test | ~5 min | After enabling HPA, on deploy |
| `test-hpa-load.sh` | Full load test with CSV reporting | ~15 min | Before release, capacity planning |
| `test-cluster-autoscaler.sh` | Verifies new nodes provision for pending pods | ~10 min | After cluster setup, infrastructure changes |

### Quick HPA Smoke Test

```bash
# Test backend autoscaling (default)
./testing/autoscaling/test-hpa.sh

# Test frontend
./testing/autoscaling/test-hpa.sh --component frontend

# Custom namespace and timeout
./testing/autoscaling/test-hpa.sh --namespace prod --timeout 600
```

### Full Load Test

```bash
# Default: 100 concurrent requests for 3 minutes
./testing/autoscaling/test-hpa-load.sh

# Heavier load
./testing/autoscaling/test-hpa-load.sh --concurrency 200 --duration 300

# With explicit URL (for remote clusters)
./testing/autoscaling/test-hpa-load.sh --url https://druppie.example.com

# Results saved to testing/results/autoscaling/
```

### Cluster Autoscaler Test

```bash
# Default: scale from 1 to 2 nodes
./testing/autoscaling/test-cluster-autoscaler.sh

# Target more nodes
./testing/autoscaling/test-cluster-autoscaler.sh --target-nodes 4

# Wait for scale-down after test
./testing/autoscaling/test-cluster-autoscaler.sh --wait-scale-down
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All assertions passed |
| 1 | Scale-up failed or pre-flight check failed |
| 2 | Scale-up passed but scale-down failed |
| 3 | Pod scheduling failed (cluster autoscaler only) |

## Architecture

```
testing/autoscaling/
├── lib/
│   └── common.sh              # Shared functions (logging, k8s helpers, assertions)
├── test-hpa.sh                # Quick smoke test
├── test-hpa-load.sh           # Full load test with reporting
├── test-cluster-autoscaler.sh # Node provisioning test
└── README.md
```

## Current Autoscaling Configuration

| Component | HPA | Cluster Autoscaler | Resource Request |
|-----------|-----|--------------------|------------------|
| Backend | 2→10 pods @ 70% CPU | App pool: 1→10 nodes | 500m CPU, 512Mi |
| Frontend | 2→8 pods @ 70% CPU | App pool: 1→10 nodes | 100m CPU, 128Mi |

**HPA behavior**: Scale up +2 pods/60s, scale down -50%/60s, 300s stabilization window.

**Note**: HPA is currently disabled in `values-hetzner.yaml` (Phase 1). Enable it by applying `values-prod.yaml` or setting `autoscaling.backend.enabled: true`.

## Manual Verification Commands

```bash
# Watch HPA in real-time
kubectl get hpa -n druppie -w

# Watch autoscaling events
kubectl get events -n druppie --sort-by='.lastTimestamp' | grep -E "Scaled|HorizontalPodAutoscaler"

# Cluster Autoscaler logs
kubectl logs -f deployment/cluster-autoscaler -n kube-system

# Node resource usage
kubectl top nodes
kubectl top pods -n druppie
```
