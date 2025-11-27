# GPU-Aware Autoscaling Research Project

Kubernetes-based comparison of GPU-aware autoscaling vs CPU-based HPA using NVIDIA GPU workloads.

## Project Overview

**Workload**: GPU Matrix Multiplication (CuPy)
- Matrix size: 1000-2000x2000
- Iterations: 20-100 per request
- Operations: 4 matrix multiplications + 8 element-wise operations
- Generates 60-95% GPU utilization under load

**Experiments**: Two 90-second tests
1. **HPA**: Standard Kubernetes CPU-based autoscaling
2. **UserScale**: Custom GPU-aware autoscaling (GPU%, latency, concurrent requests)

## Quick Start

### Prerequisites
- NVIDIA GPU with driver installed
- k3s running
- GPU Operator deployed
- Port forwarding active (8001, 8002)

### Run Experiments

```bash
# Run both experiments (HPA + UserScale, 90s each)
python3 run_files/demo.py

# Analyze results
python3 run_files/analyze_results.py
```

### Results

All results saved to `results/`:
- `hpa_results.json` - HPA experiment data
- `userscale_results.json` - UserScale experiment data
- `comparison.json` - Side-by-side comparison

## Metrics Collected

- **Pods**: min, max, average count
- **GPU**: average and max utilization %
- **CPU**: average utilization %
- **Latency**: average, min, max (ms)
- **Requests**: total count and success rate
- **Scaling Events**: number of scale up/down operations

## Architecture

### Components
- **app/unified_app.py**: FastAPI app with GPU matrix workload
- **scaler/main.py**: Custom GPU-aware autoscaler
- **k8s/**: Kubernetes manifests (userscale, HPA, GPU config)
- **run_files/demo.py**: Automated experiment runner
- **run_files/analyze_results.py**: Result analyzer

### Scaling Logic

**UserScale (GPU-Aware)**:
- GPU > 80%: Scale up by 3
- GPU > 60%: Scale up by 2
- GPU > 50%: Scale up by 1
- GPU < 20% + low latency: Scale down
- Latency > 1000ms: Aggressive scale up
- Checks every 3 seconds

**HPA (CPU-Based)**:
- Target: 40% CPU utilization
- Scale up: 100% increase or +5 pods
- Scale down: 50% decrease or -2 pods
- Checks every 10-30 seconds

## Project Structure

```
.
├── app/
│   ├── unified_app.py          # FastAPI GPU workload app
│   └── requirements.txt
├── scaler/
│   ├── main.py                 # Custom GPU-aware scaler
│   └── requirements.txt
├── k8s/
│   ├── userscale-gpu.yaml      # UserScale deployment
│   ├── hpa-gpu.yaml            # HPA deployment
│   └── gpu-timeslice-config.yaml
├── run_files/
│   ├── demo.py                 # Automated experiment runner
│   ├── analyze_results.py      # Result analyzer
│   ├── download_dependencies.py
│   ├── setup.py
│   ├── watch_gpu_metrics.py
│   └── watch_scaling.py
├── results/                    # Experiment results
├── Dockerfile.gpu
├── docker-entrypoint.sh
└── README.md
```

## Hardware Configuration

Optimized for:
- GPU: NVIDIA GTX 1650 Mobile (4GB)
- CPU: 12 threads
- RAM: 7GB
- vGPUs: 6 (time-sliced)
- Max pods: 6

## Expected Results

**UserScale**:
- Higher GPU utilization (60-90%)
- Faster scaling response (3s intervals)
- More scaling events
- GPU-aware decisions

**HPA**:
- Lower GPU utilization (40-70%)
- Slower scaling response (10-30s)
- Fewer scaling events
- CPU-only decisions

## Troubleshooting

```bash
# Check pods
kubectl get pods -n userscale

# Check GPU availability
kubectl describe node | grep nvidia.com/gpu

# Check scaler logs
kubectl logs -n userscale -l app=userscale-scaler -f

# Restart port forwarding
pkill -f 'kubectl port-forward'
kubectl port-forward -n userscale svc/userscale-app 8001:8000 &
kubectl port-forward -n userscale svc/hpa-app 8002:8000 &
```

## Research Questions

1. Does GPU-aware scaling improve GPU utilization?
2. How does scaling responsiveness compare?
3. What is the latency impact?
4. Which approach is more resource-efficient?
5. How do scaling patterns differ under load?

## Key Findings

Run experiments to discover:
- GPU utilization differences
- Scaling speed comparison
- Resource efficiency
- Latency characteristics
- Scaling behavior patterns

---

**Ready to run**: `python3 run_files/demo.py`
