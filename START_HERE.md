# 🚀 START HERE - GPU Kubernetes Autoscaler Setup

## 📍 You Are Here

**Project:** MEGA_PROJECT_SEMVII - GPU-Enabled Kubernetes Autoscaler  
**Location:** `/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2`  
**System:** Ubuntu 22.04 with NVIDIA GTX 1050 Ti

---

## 📚 Documentation Files Available

I've created comprehensive guides for you:

| File | Purpose | When to Use |
|------|---------|-------------|
| **START_HERE.md** | This file - Quick overview | Start here! |
| **EXECUTION_CHECKLIST.md** | Complete checklist with checkboxes | Main execution guide |
| **STEP_BY_STEP_COMMANDS.txt** | Detailed commands with explanations | Detailed reference |
| **QUICK_COMMANDS.txt** | Essential commands only | Quick lookup |
| **EXECUTION_COMMANDS.sh** | Full bash script | Automated execution |
| **PROJECT_SUMMARY.txt** | Complete project documentation | Deep dive |

---

## ⚡ Quick Start (3 Steps)

### Step 1: Verify System (2 minutes)
```bash
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

**If this works, continue. If not, see troubleshooting below.**

---

### Step 2: Setup Python Environment (10 minutes)
```bash
# Create and activate virtual environment
sudo python3 -m venv /usr/local/pyenv
sudo chown -R $USER:$USER /usr/local/pyenv
source /usr/local/pyenv/bin/activate

# Install dependencies (takes 5-10 minutes)
pip install --upgrade pip
pip install nvidia-ml-py3 cupy-cuda12x fastapi uvicorn numpy requests psutil pydantic kubernetes httpx tenacity

# Verify GPU stack
python3 verify_gpu.py
```

**Expected:** All checks show ✅ PASS

---

### Step 3: Deploy and Run (20 minutes)
```bash
# Deploy to Kubernetes (takes 10-15 minutes first time)
python3 setup.py

# Open 3 monitoring terminals:
# Terminal 1: watch -n 1 nvidia-smi
# Terminal 2: watch -n 1 "kubectl get pods -n userscale && echo && kubectl get pods -n hpa"
# Terminal 3: python3 monitor.py

# Run demo workload (5 minutes)
python3 demo.py
```

**Expected:** GPU utilization increases, pods scale up, real metrics displayed

---

## 📋 Full Execution Path

For detailed step-by-step execution with checkboxes, open:
```bash
cat EXECUTION_CHECKLIST.md
```

Or view it in your IDE for a better experience.

---

## 🎯 What This Project Does

This is a **production-ready GPU-aware Kubernetes autoscaler** that:

1. **Monitors real GPU metrics** using nvidia-smi and pynvml
2. **Scales pods based on GPU utilization** (not just CPU)
3. **Compares two autoscaling approaches:**
   - **UserScale:** Custom GPU-aware autoscaler (scales on GPU %)
   - **HPA:** Standard Kubernetes HPA (scales on CPU %)
4. **Generates real GPU workload** using CuPy matrix operations
5. **Provides real-time monitoring** dashboard

---

## 🔍 Key Components

```
Project Structure:
├── verify_gpu.py          ← Run this FIRST to check GPU setup
├── setup.py               ← Deploys everything to Kubernetes
├── demo.py                ← Generates GPU workload (5 min test)
├── monitor.py             ← Real-time monitoring dashboard
├── Dockerfile.gpu         ← CUDA-enabled Docker image
├── app/
│   └── unified_app.py     ← FastAPI app with GPU metrics
├── scaler/
│   └── main.py            ← Custom GPU-aware autoscaler
└── k8s/
    ├── userscale-gpu.yaml ← GPU-aware deployment
    └── hpa-gpu.yaml       ← CPU-based HPA deployment
```

---

## ✅ Prerequisites Checklist

Before starting, ensure you have:

- [ ] **Native Ubuntu** (not WSL) - Required for GPU access
- [ ] **NVIDIA GPU** with CUDA support (GTX 1050 Ti detected)
- [ ] **NVIDIA Driver** installed (580.95.05 detected)
- [ ] **Docker** installed and running
- [ ] **NVIDIA Container Toolkit** installed
- [ ] **Minikube** installed (v1.34+)
- [ ] **kubectl** installed (v1.28+)
- [ ] **Python 3.8+** installed
- [ ] **At least 10GB free disk space** on root filesystem

---

## 🔧 Common Issues & Quick Fixes

### Issue 1: Docker GPU Test Fails
```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Issue 2: CuPy Installation Fails
```bash
# Make sure you have enough disk space
df -h /

# Try installing with verbose output
pip install -v cupy-cuda12x
```

### Issue 3: Minikube Won't Start
```bash
# Delete and recreate
minikube delete
minikube start --driver=docker --gpus=all --memory=4096 --cpus=2
```

### Issue 4: Pods Stuck in Pending
```bash
# Check what's wrong
kubectl describe pod <pod-name> -n userscale

# Check GPU device plugin
kubectl get pods -n kube-system | grep nvidia
```

---

## 📊 Expected Results

When everything works correctly:

### During Demo:
- **GPU Utilization:** Increases from ~5% to 60-90%
- **Temperature:** Rises to 60-75°C
- **Memory Usage:** Increases to 500-1500 MB
- **Pod Scaling:** 1 → 5-10 replicas
- **Scaling Speed:** UserScale < 30s, HPA ~60s

### Final Report:
- Real GPU metrics (no "simulated" flags)
- UserScale scales faster than HPA
- GPU-based scaling more responsive
- All health checks passing

---

## 🎓 Understanding the Flow

```
1. verify_gpu.py
   └─> Checks: nvidia-smi, pynvml, cupy, docker-gpu
       └─> All PASS? Continue ✅

2. setup.py
   └─> Starts Minikube with GPU support
   └─> Builds CUDA Docker image (10-15 min)
   └─> Deploys UserScale + HPA to Kubernetes
   └─> Sets up port forwarding (8001, 8002)
       └─> Pods running? Continue ✅

3. demo.py (in main terminal)
   └─> Generates GPU workload for 5 minutes
   └─> Tracks scaling behavior
   └─> Shows comparison report
       └─> GPU utilized? Pods scaled? Success ✅

4. monitor.py (in separate terminal)
   └─> Real-time dashboard
   └─> Shows GPU metrics every 5 seconds
   └─> Tracks scaling events
```

---

## 🚦 Execution Order

```bash
# 1. Navigate to project
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"

# 2. Setup Python environment
sudo python3 -m venv /usr/local/pyenv
sudo chown -R $USER:$USER /usr/local/pyenv
source /usr/local/pyenv/bin/activate
pip install --upgrade pip
pip install nvidia-ml-py3 cupy-cuda12x fastapi uvicorn numpy requests psutil pydantic kubernetes httpx tenacity

# 3. Verify GPU
python3 verify_gpu.py

# 4. Deploy
python3 setup.py

# 5. Monitor (open 3 terminals)
# Terminal 1: watch -n 1 nvidia-smi
# Terminal 2: watch -n 1 "kubectl get pods -n userscale && echo && kubectl get pods -n hpa"
# Terminal 3: python3 monitor.py

# 6. Run demo (main terminal)
python3 demo.py

# 7. Cleanup when done
python3 setup.py --cleanup
```

---

## 📞 Need Help?

1. **Check verify_gpu.py output** - Shows exactly what's wrong
2. **Read EXECUTION_CHECKLIST.md** - Step-by-step with troubleshooting
3. **Check logs:**
   ```bash
   kubectl logs -n userscale -l app=userscale-app --tail=100
   kubectl logs -n userscale -l app=userscale-scaler --tail=100
   ```
4. **Check events:**
   ```bash
   kubectl get events -n userscale --sort-by='.lastTimestamp'
   ```

---

## 🎯 Success Indicators

You'll know it's working when:

✅ `verify_gpu.py` shows all PASS  
✅ `setup.py` completes without errors  
✅ `kubectl get pods -n userscale` shows Running pods  
✅ `curl http://localhost:8001/healthz` returns healthy  
✅ `nvidia-smi` shows GPU utilization increasing during demo  
✅ Pods scale from 1 to multiple replicas  
✅ `demo.py` shows real metrics (no "simulated")  

---

## 🏁 Ready to Start?

**Recommended approach:**

1. Open **EXECUTION_CHECKLIST.md** in your IDE
2. Follow each phase with checkboxes
3. Keep **QUICK_COMMANDS.txt** open for reference
4. Run commands one by one
5. Verify each step before proceeding

**Quick approach (if experienced):**

1. Run `python3 verify_gpu.py`
2. Run `python3 setup.py`
3. Run `python3 demo.py`

---

**Let's begin! Open EXECUTION_CHECKLIST.md and start with Phase 1.**

---

*Generated for: MEGA_PROJECT_SEMVII GPU-Enabled Kubernetes Autoscaler*  
*System: Ubuntu 22.04 | GPU: NVIDIA GTX 1050 Ti | Driver: 580.95.05*
