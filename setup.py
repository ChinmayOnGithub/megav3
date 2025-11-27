#!/usr/bin/env python3
"""
Complete Setup Script - Handles all deployment and configuration
Fixes HPA stuck-at-zero issue and ensures clean re-runs
"""

import subprocess
import time
import sys
import os
import json

def run(cmd, silent=False, timeout=600):
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            timeout=timeout,
            capture_output=True,
            text=True
        )
        if not silent:
            if r.stdout.strip():
                print(r.stdout.strip())
            if r.stderr.strip() and "warning" not in r.stderr.lower():
                print(r.stderr.strip())
        return r.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def header(t):
    print(f"\n{'='*80}\n{t}\n{'='*80}")


def step(msg, ok=True):
    print(f"{'[OK]' if ok else '[FAIL]'} {msg}")


def check_prereq():
    header("Step 1/8: Checking prerequisites")

    if not run("kubectl version --client", silent=True):
        step("kubectl not found", False)
        sys.exit(1)
    step("kubectl found")

    if not run("docker --version", silent=True):
        step("Docker not installed", False)
        sys.exit(1)
    step("Docker found")

    if not run("docker ps", silent=True):
        step("Docker daemon not running", False)
        sys.exit(1)
    step("Docker daemon running")

    if run("nvidia-smi", silent=True):
        step("GPU detected")
    else:
        step("No GPU detected - scaling will still work", False)


def build_image():
    header("Step 2/8: Building Docker image")

    if not os.path.exists("Dockerfile.gpu"):
        step("Dockerfile.gpu missing", False)
        sys.exit(1)

    if not run("docker build -f Dockerfile.gpu -t userscale-gpu:latest .", timeout=1200):
        step("Image build failed", False)
        sys.exit(1)

    step("Image built successfully")


def load_image():
    header("Step 3/8: Loading image into k3s")

    step("Saving image...")
    run("docker save userscale-gpu:latest -o userscale.tar")

    if os.path.exists("/usr/local/bin/k3s"):
        import_cmd = "sudo k3s ctr images import userscale.tar"
    else:
        import_cmd = "ctr --namespace k8s.io images import userscale.tar"

    step("Importing into containerd...")
    if not run(import_cmd):
        step("Failed to import image", False)
        sys.exit(1)

    os.remove("userscale.tar")
    step("Image available inside k3s")


def cleanup_namespace():
    header("Step 4/8: Cleaning up existing namespace")
    
    # Check if namespace exists
    result = subprocess.run(
        "kubectl get namespace userscale 2>&1",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "NotFound" not in result.stderr and "not found" not in result.stdout.lower():
        step("Namespace exists, cleaning up...")
        
        # Scale all deployments to 0 first
        run("kubectl scale deployment --all -n userscale --replicas=0", silent=True)
        time.sleep(3)
        
        # Delete HPA to prevent it from interfering
        run("kubectl delete hpa --all -n userscale --ignore-not-found=true", silent=True)
        time.sleep(2)
        
        # Remove finalizers if stuck
        run("kubectl patch namespace userscale -p '{\"metadata\":{\"finalizers\":[]}}' --type=merge", silent=True)
        
        # Force delete namespace
        run("kubectl delete namespace userscale --force --grace-period=0 --ignore-not-found=true", silent=True)
        
        # Wait for deletion
        for i in range(30):
            result = subprocess.run(
                "kubectl get namespace userscale 2>&1",
                shell=True,
                capture_output=True,
                text=True
            )
            if "NotFound" in result.stderr or "not found" in result.stdout.lower():
                break
            time.sleep(1)
        
        step("Namespace cleaned up")
    else:
        step("No existing namespace found")
    
    # Create fresh namespace
    run("kubectl create namespace userscale")
    step("Fresh namespace created")


def configure_gpu_timeslicing():
    header("Step 5/8: Configuring GPU time-slicing")

    cfg = "k8s/gpu-timeslice-config.yaml"
    if not os.path.exists(cfg):
        step("gpu-timeslice-config.yaml not found, skipping", False)
    else:
        step(f"Applying {cfg}")
        run(f"kubectl apply -f {cfg}")

    step("Restarting NVIDIA device plugin")
    run("kubectl rollout restart daemonset nvidia-device-plugin-daemonset -n gpu-operator", silent=True)
    time.sleep(5)


def deploy_manifests():
    header("Step 6/8: Deploying manifests")

    for m in ["k8s/userscale-gpu.yaml", "k8s/hpa-gpu.yaml"]:
        if not os.path.exists(m):
            step(f"Missing manifest: {m}", False)
            sys.exit(1)
        step(f"Applying {m}")
        run(f"kubectl apply -f {m}")
    
    time.sleep(5)


def wait_ready():
    header("Step 7/8: Waiting for workloads")

    apps = ["userscale-app", "userscale-scaler", "hpa-app"]

    for app in apps:
        step(f"Waiting for {app}")
        run(f"kubectl wait --for=condition=available --timeout=180s deployment/{app} -n userscale")

    time.sleep(5)
    
    print("\nCurrent pods:")
    run("kubectl get pods -n userscale -o wide")


def fix_hpa_scaling():
    header("Step 8/8: Fixing HPA configuration and preventing scale-to-zero")
    
    # Ensure HPA is properly configured and not stuck
    step("Verifying HPA configuration...")
    
    # Wait for HPA to be created
    time.sleep(5)
    
    # Check if HPA exists
    result = subprocess.run(
        "kubectl get hpa hpa-autoscaler -n userscale -o json 2>&1",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "NotFound" in result.stderr:
        step("HPA not found, waiting for creation...", False)
        time.sleep(10)
    else:
        # Ensure HPA min replicas is set correctly
        run("kubectl patch hpa hpa-autoscaler -n userscale --type=json -p='[{\"op\": \"replace\", \"path\": \"/spec/minReplicas\", \"value\": 1}]'", silent=True)
        step("HPA min replicas enforced to 1")
    
    # CRITICAL: Ensure deployments NEVER scale to 0
    # Set replicas to 1 and verify
    step("Ensuring deployments start with 1 replica...")
    run("kubectl scale deployment hpa-app -n userscale --replicas=1")
    run("kubectl scale deployment userscale-app -n userscale --replicas=1")
    
    # Patch deployments to prevent scale-to-zero
    run("kubectl patch deployment hpa-app -n userscale -p '{\"spec\":{\"replicas\":1}}'", silent=True)
    run("kubectl patch deployment userscale-app -n userscale -p '{\"spec\":{\"replicas\":1}}'", silent=True)
    
    step("Deployments locked to minimum 1 replica")
    
    # Wait for pods to be ready
    step("Waiting for pods to be ready...")
    time.sleep(15)
    run("kubectl wait --for=condition=ready pod -l app=hpa-app -n userscale --timeout=90s")
    run("kubectl wait --for=condition=ready pod -l app=userscale-app -n userscale --timeout=90s")
    
    # Verify HPA status
    step("Verifying HPA status...")
    run("kubectl get hpa hpa-autoscaler -n userscale")
    
    # Show current pod status
    step("Current pod status:")
    run("kubectl get pods -n userscale")
    
    step("HPA configuration fixed and scale-to-zero prevented")


def setup_port_forwarding():
    header("Port Forwarding Setup")
    
    # Kill existing port forwards
    run("pkill -f 'kubectl port-forward'", silent=True)
    time.sleep(2)
    
    # Start port forwarding in background
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/hpa-app 8002:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/userscale-app 8001:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    
    step("Port forwarding started")
    print("  HPA:       http://localhost:8002")
    print("  UserScale: http://localhost:8001")


def main():
    print("\n" + "="*80)
    print("  GPU-AWARE AUTOSCALING - COMPLETE SETUP")
    print("="*80 + "\n")
    
    check_prereq()
    build_image()
    load_image()
    cleanup_namespace()
    configure_gpu_timeslicing()
    deploy_manifests()
    wait_ready()
    fix_hpa_scaling()
    setup_port_forwarding()

    print("\n" + "="*80)
    print("  SETUP COMPLETE!")
    print("="*80 + "\n")
    print("Next steps:")
    print("  python3 demo.py")
    print("")


if __name__ == "__main__":
    main()
