# GPU-ENABLED KUBERNETES AUTOSCALER - EXECUTION CHECKLIST

## 📋 Pre-Execution Summary

**Project:** MEGA_PROJECT_SEMVII - GPU-Enabled Kubernetes Autoscaler  
**Location:** `/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2`  
**GPU:** NVIDIA GeForce GTX 1050 Ti (4GB)  
**Driver:** 580.95.05  
**System:** Ubuntu 22.04 (Native)

---

## 📁 Files Created for You

I've created 3 command reference files:

1. **EXECUTION_COMMANDS.sh** - Full bash script with all commands
2. **STEP_BY_STEP_COMMANDS.txt** - Detailed step-by-step guide with explanations
3. **QUICK_COMMANDS.txt** - Quick reference card for essential commands

---

## ✅ EXECUTION CHECKLIST

### Phase 1: Initial System Verification (5 minutes)

Run these commands to verify your system:

```bash
# Navigate to project
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"

# Check disk space
df -h / /home

# Verify GPU
nvidia-smi

# Check Docker
docker --version
docker ps

# Check Minikube
minikube version

# Check kubectl
kubectl version --client

# Check Python
python3 --version
pip3 --version
```

**Expected Results:**
- [ ] At least 10GB free disk space on root
- [ ] nvidia-smi shows GTX 1050 Ti
- [ ] Docker version 20.10+
- [ ] Minikube v1.34+
- [ ] kubectl v1.28+
- [ ] Python 3.8+

---

### Phase 2: NVIDIA Container Toolkit Test (2 minutes)

```bash
# Test Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

**Expected Result:**
- [ ] Shows GPU info inside container (same as host)

**If FAILS:** Install NVIDIA Container Toolkit:
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

### Phase 3: Setup Python Environment (10 minutes)

```bash
# Create virtual environment at /usr/local/pyenv
sudo python3 -m venv /usr/local/pyenv

# Change ownership
sudo chown -R $USER:$USER /usr/local/pyenv

# Activate
source /usr/local/pyenv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies (this takes 5-10 minutes, CuPy is ~500MB)
pip install nvidia-ml-py3 cupy-cuda12x fastapi uvicorn numpy requests psutil pydantic kubernetes httpx tenacity

# Verify
pip list | grep -E "nvidia-ml-py3|cupy"
```

**Expected Results:**
- [ ] Virtual environment created at /usr/local/pyenv
- [ ] Prompt shows (pyenv) prefix
- [ ] cupy-cuda12x installed (~12.3.0)
- [ ] nvidia-ml-py3 installed (~7.352.0)

---

### Phase 4: Verify GPU Stack (2 minutes)

```bash
# Make sure you're in the project directory and venv is active
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"
source /usr/local/pyenv/bin/activate

# Run GPU verification
python3 verify_gpu.py
```

**Expected Results:**
- [ ] ✅ nvidia-smi - PASS
- [ ] ✅ pynvml - PASS
- [ ] ✅ cupy - PASS
- [ ] ✅ docker-gpu - PASS

**If any FAIL, STOP and fix before proceeding!**

---

### Phase 5: Deploy to Kubernetes (15-20 minutes)

```bash
# Clean any existing cluster
minikube delete

# Run setup script (this takes 10-15 minutes on first run)
python3 setup.py
```

**What happens:**
1. Starts Minikube with GPU support
2. Builds Docker image with CUDA (5-10 minutes)
3. Deploys UserScale and HPA to Kubernetes
4. Sets up port forwarding

**Expected Results:**
- [ ] "Setup complete!" message
- [ ] No errors during build
- [ ] Port forwarding started on 8001 and 8002

**Verify deployment:**
```bash
# Check pods
kubectl get pods -n userscale
kubectl get pods -n hpa

# Wait for ready (if needed)
kubectl wait --for=condition=ready pod -l app=userscale-app -n userscale --timeout=300s
kubectl wait --for=condition=ready pod -l app=hpa-app -n hpa --timeout=300s

# Test endpoints
curl http://localhost:8001/healthz
curl http://localhost:8002/healthz
```

**Expected Results:**
- [ ] All pods in "Running" state
- [ ] Health checks return {"status": "healthy"}

---

### Phase 6: Setup Monitoring (Open 3 Terminals)

**Terminal 1 - GPU Monitoring:**
```bash
watch -n 1 nvidia-smi
```

**Terminal 2 - Pod Monitoring:**
```bash
watch -n 1 "kubectl get pods -n userscale && echo && kubectl get pods -n hpa"
```

**Terminal 3 - Real-time Dashboard:**
```bash
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"
source /usr/local/pyenv/bin/activate
python3 monitor.py
```

**Expected Results:**
- [ ] Terminal 1 shows GPU at low utilization (~5-10%)
- [ ] Terminal 2 shows 1 pod each for userscale and hpa
- [ ] Terminal 3 shows live metrics dashboard

---

### Phase 7: Run Demo Workload (5 minutes)

**In main terminal:**
```bash
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"
source /usr/local/pyenv/bin/activate
python3 demo.py
```

**What to observe:**
- **Terminal 1 (nvidia-smi):** GPU utilization increases to 60-90%
- **Terminal 2 (pods):** Pods scale from 1 to 5-10 replicas
- **Terminal 3 (monitor):** Real-time metrics showing scaling behavior

**Expected Results:**
- [ ] Demo runs for 5 minutes (300 seconds)
- [ ] GPU utilization increases significantly
- [ ] UserScale scales faster than HPA
- [ ] Final report shows comparison
- [ ] No "simulated" flags in output

---

### Phase 8: Validation (5 minutes)

```bash
# Check final GPU state
nvidia-smi

# Check final pod counts
kubectl get pods -n userscale
kubectl get pods -n hpa

# Check HPA status
kubectl get hpa -n hpa -o wide

# Check scaler logs
kubectl logs -n userscale -l app=userscale-scaler --tail=100

# Check metrics endpoint
curl http://localhost:8001/metrics | jq .

# Verify real GPU metrics (no "simulated")
curl http://localhost:8001/metrics | grep -i gpu
```

**Expected Results:**
- [ ] GPU utilization elevated
- [ ] Multiple replicas running
- [ ] HPA shows scaling activity
- [ ] Scaler logs show GPU-based decisions
- [ ] Metrics show real GPU values

---

### Phase 9: Cleanup (2 minutes)

```bash
# Stop monitoring terminals (Ctrl+C in each)

# Run cleanup
python3 setup.py --cleanup

# Stop Minikube (optional)
minikube stop

# Delete cluster (optional)
minikube delete
```

**Expected Results:**
- [ ] All Kubernetes resources deleted
- [ ] Port forwarding stopped
- [ ] Cluster stopped/deleted

---

## 🎯 Success Criteria

Your setup is successful if:

✅ **GPU Recognition:**
- nvidia-smi shows GTX 1050 Ti
- Docker can access GPU
- Pods can use GPU

✅ **Deployment:**
- All pods reach Running state
- Health checks pass
- Port forwarding works

✅ **Workload:**
- GPU utilization reaches 60-90%
- Pods scale from 1 to 5-10 replicas
- UserScale scales faster than HPA

✅ **Metrics:**
- All metrics show real values
- No "simulated" flags
- Temperature increases to 60-75°C
- Memory usage increases

---

## 🔧 Troubleshooting Quick Reference

### Docker GPU Test Fails
```bash
# Reinstall NVIDIA Container Toolkit
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Pods Stuck in Pending
```bash
kubectl describe pod <pod-name> -n userscale
kubectl get events -n userscale --sort-by='.lastTimestamp'
```

### Port Forwarding Fails
```bash
pkill -f 'kubectl port-forward'
kubectl port-forward -n userscale svc/userscale-app 8001:8000 &
kubectl port-forward -n hpa svc/hpa-app 8002:8000 &
```

### Docker Build Fails
```bash
docker system prune -af
python3 setup.py
```

### Minikube Issues
```bash
minikube delete
minikube start --driver=docker --gpus=all --memory=4096 --cpus=2
```

---

## 📊 Expected Performance Metrics

With GTX 1050 Ti (4GB):

- **Matrix size 1000:** 50-100ms per operation
- **GPU utilization:** 60-90% under load
- **Memory usage:** 500-1500 MB
- **Temperature:** 60-75°C under sustained load
- **Scaling time:** UserScale < 30s, HPA ~60s

---

## 📝 Notes

- All installations go to **root filesystem** (/usr/local/pyenv)
- Use **sudo** for system-level operations
- **First Docker build** takes 10-15 minutes (downloads CUDA base image)
- **CuPy installation** takes 5-10 minutes (~500MB download)
- Keep monitoring terminals open during demo for best visibility

---

## 🚀 Quick Start (If Everything is Already Installed)

```bash
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"
source /usr/local/pyenv/bin/activate
python3 verify_gpu.py
python3 setup.py
python3 demo.py
```

---

## 📚 Reference Files

- **PROJECT_SUMMARY.txt** - Complete project documentation
- **STEP_BY_STEP_COMMANDS.txt** - Detailed command guide
- **QUICK_COMMANDS.txt** - Quick reference
- **EXECUTION_GUIDE.md** - Original execution guide

---

**Ready to start? Begin with Phase 1!**
