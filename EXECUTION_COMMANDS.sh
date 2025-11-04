#!/bin/bash
################################################################################
# GPU-ENABLED KUBERNETES AUTOSCALER - COMPLETE SETUP SCRIPT
# Execute each section step-by-step and verify output
################################################################################

echo "================================================================================"
echo "PHASE 1: SYSTEM VERIFICATION"
echo "================================================================================"

echo -e "\n[1.1] Check Disk Space"
df -h / /home

echo -e "\n[1.2] Verify GPU with nvidia-smi"
nvidia-smi

echo -e "\n[1.3] Check Docker Version"
docker --version

echo -e "\n[1.4] Check Docker Status"
docker ps

echo -e "\n[1.5] Check Minikube Version"
minikube version

echo -e "\n[1.6] Check kubectl Version"
kubectl version --client

echo -e "\n[1.7] Check Python Version"
python3 --version

echo -e "\n[1.8] Check pip Version"
pip3 --version

echo "================================================================================"
echo "PHASE 2: NVIDIA CONTAINER TOOLKIT VERIFICATION"
echo "================================================================================"

echo -e "\n[2.1] Test Docker GPU Access"
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi

echo -e "\n[2.2] Check NVIDIA Docker Runtime"
docker info | grep -i nvidia

echo "================================================================================"
echo "PHASE 3: INSTALL/VERIFY DEPENDENCIES"
echo "================================================================================"

echo -e "\n[3.1] Update Package Lists (requires sudo)"
sudo apt-get update

echo -e "\n[3.2] Install Python3-pip if needed"
sudo apt-get install -y python3-pip python3-venv

echo -e "\n[3.3] Install Docker if needed (skip if already installed)"
# Uncomment if Docker needs installation:
# curl -fsSL https://get.docker.com -o get-docker.sh
# sudo sh get-docker.sh
# sudo usermod -aG docker $USER
# newgrp docker

echo -e "\n[3.4] Install NVIDIA Container Toolkit if needed"
# Uncomment if needed:
# distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
# curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
# curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
# sudo apt-get update
# sudo apt-get install -y nvidia-container-toolkit
# sudo systemctl restart docker

echo -e "\n[3.5] Install Minikube if needed"
# Uncomment if needed:
# curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
# sudo install minikube-linux-amd64 /usr/local/bin/minikube

echo -e "\n[3.6] Install kubectl if needed"
# Uncomment if needed:
# curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
# sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

echo "================================================================================"
echo "PHASE 4: SETUP GLOBAL PYTHON VIRTUAL ENVIRONMENT"
echo "================================================================================"

echo -e "\n[4.1] Create Virtual Environment at /usr/local/pyenv"
sudo python3 -m venv /usr/local/pyenv

echo -e "\n[4.2] Change Ownership to Current User"
sudo chown -R $USER:$USER /usr/local/pyenv

echo -e "\n[4.3] Activate Virtual Environment"
source /usr/local/pyenv/bin/activate

echo -e "\n[4.4] Upgrade pip"
pip install --upgrade pip

echo -e "\n[4.5] Install Python Dependencies"
pip install nvidia-ml-py3 cupy-cuda12x fastapi uvicorn numpy requests psutil pydantic kubernetes httpx tenacity

echo -e "\n[4.6] Verify Installations"
pip list | grep -E "nvidia-ml-py3|cupy"

echo "================================================================================"
echo "PHASE 5: VERIFY PROJECT FILES"
echo "================================================================================"

echo -e "\n[5.1] Navigate to Project Directory"
cd "/home/chinmay/Development/GitHub Repos/Mega_Project_SEMVII_version2"

echo -e "\n[5.2] List Project Files"
ls -lah

echo -e "\n[5.3] Verify Critical Files Exist"
for file in setup.py demo.py monitor.py verify_gpu.py Dockerfile.gpu; do
    if [ -f "$file" ]; then
        echo "✅ $file exists"
    else
        echo "❌ $file missing"
    fi
done

echo -e "\n[5.4] Check app/ directory"
ls -lah app/

echo -e "\n[5.5] Check k8s/ directory"
ls -lah k8s/

echo -e "\n[5.6] Check scaler/ directory"
ls -lah scaler/

echo "================================================================================"
echo "PHASE 6: RUN GPU VERIFICATION SCRIPT"
echo "================================================================================"

echo -e "\n[6.1] Execute verify_gpu.py"
python3 verify_gpu.py

echo "================================================================================"
echo "PHASE 7: DEPLOY TO KUBERNETES"
echo "================================================================================"

echo -e "\n[7.1] Clean up any existing Minikube cluster"
minikube delete

echo -e "\n[7.2] Start Minikube with GPU support"
# This will be done by setup.py, but you can manually do:
# minikube start --driver=docker --gpus=all --memory=4096 --cpus=2

echo -e "\n[7.3] Run setup.py to deploy everything"
python3 setup.py

echo -e "\n[7.4] Wait for pods to be ready"
kubectl wait --for=condition=ready pod -l app=userscale-app -n userscale --timeout=300s
kubectl wait --for=condition=ready pod -l app=hpa-app -n hpa --timeout=300s

echo -e "\n[7.5] Verify Deployments"
kubectl get pods -n userscale
kubectl get pods -n hpa

echo -e "\n[7.6] Check Services"
kubectl get svc -n userscale
kubectl get svc -n hpa

echo -e "\n[7.7] Verify GPU Resources in Cluster"
kubectl get nodes -o json | grep -i "nvidia.com/gpu"

echo "================================================================================"
echo "PHASE 8: RUN DEMO WORKLOAD"
echo "================================================================================"

echo -e "\n[8.1] Open new terminal and run monitor (in background or separate terminal):"
echo "python3 monitor.py"

echo -e "\n[8.2] Open another terminal to watch nvidia-smi:"
echo "watch -n 1 nvidia-smi"

echo -e "\n[8.3] Open another terminal to watch pods:"
echo "kubectl get pods -n userscale -w"

echo -e "\n[8.4] Run demo.py (this will take ~5 minutes)"
python3 demo.py

echo "================================================================================"
echo "PHASE 9: VALIDATION"
echo "================================================================================"

echo -e "\n[9.1] Check GPU Utilization"
nvidia-smi

echo -e "\n[9.2] Check Pod Replicas"
kubectl get pods -n userscale
kubectl get pods -n hpa

echo -e "\n[9.3] Check HPA Status"
kubectl get hpa -n hpa

echo -e "\n[9.4] Check Scaler Logs"
kubectl logs -n userscale -l app=userscale-scaler --tail=50

echo -e "\n[9.5] Check App Logs"
kubectl logs -n userscale -l app=userscale-app --tail=20

echo -e "\n[9.6] Test Endpoints"
curl http://localhost:8001/healthz
curl http://localhost:8001/metrics

echo "================================================================================"
echo "PHASE 10: CLEANUP (OPTIONAL)"
echo "================================================================================"

echo -e "\n[10.1] Run cleanup script"
echo "python3 setup.py --cleanup"

echo -e "\n[10.2] Stop Minikube"
echo "minikube stop"

echo -e "\n[10.3] Delete Minikube cluster"
echo "minikube delete"

echo "================================================================================"
echo "EXECUTION COMPLETE"
echo "================================================================================"
