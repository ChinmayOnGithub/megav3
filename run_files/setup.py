#!/usr/bin/env python3
"""
UserScale Setup - K3s Deployment Automation
Loads GPU image into k3s containerd, deploys workloads,
verifies GPU access, supports cleanup with --cleanup flag.
"""

import subprocess
import time
import sys
import os
import argparse


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
            if r.stderr.strip():
                print(r.stderr.strip())
        return r.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def header(t):
    print(f"\n{'='*80}\n{t}\n{'='*80}")


def step(msg, ok=True):
    print(f"{'[OK]' if ok else '[ERROR]'} {msg}")


# ----------------------------------------------------------
# STEP 1 — PREREQUISITES
# ----------------------------------------------------------

def check_prereq():
    header("Step 1/6: Checking prerequisites")

    if not run("kubectl version --client", silent=True):
        step("kubectl not found", False)
        sys.exit(1)
    step("kubectl found")

    # Check if k3s/kubectl can connect to API server
    step("Checking Kubernetes API server...")
    result = subprocess.run(
        "kubectl get nodes 2>&1",
        shell=True,
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if result.returncode != 0:
        step("Cannot connect to Kubernetes API server", False)
        print("  Error: " + result.stderr[:200])
        print("\n  Possible fixes:")
        print("  1. Restart k3s: sudo systemctl restart k3s")
        print("  2. Check k3s status: sudo systemctl status k3s")
        print("  3. Check logs: sudo journalctl -u k3s -n 50")
        
        # Ask if user wants to fix network issue
        response = input("\n  Fix k3s network issue automatically? (y/n): ").strip().lower()
        if response == 'y':
            print("\n  [1/6] Stopping k3s...")
            run("sudo systemctl stop k3s", silent=True, timeout=30)
            time.sleep(3)
            
            print("  [2/6] Removing cached k3s config with old IP...")
            run("sudo rm -f /etc/rancher/k3s/k3s.yaml", silent=True, timeout=10)
            run("sudo rm -f ~/.kube/config", silent=True, timeout=10)
            
            print("  [3/6] Cleaning up stale network interfaces...")
            run("sudo ip link delete cni0 2>/dev/null || true", silent=True, timeout=10)
            run("sudo ip link delete flannel.1 2>/dev/null || true", silent=True, timeout=10)
            
            print("  [4/6] Starting k3s...")
            run("sudo systemctl start k3s", silent=True, timeout=30)
            
            print("  [5/6] Waiting for k3s to initialize (30 seconds)...")
            time.sleep(30)
            
            print("  [6/6] Setting up kubectl config...")
            run("mkdir -p ~/.kube", silent=True, timeout=10)
            run("sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config", silent=True, timeout=10)
            run(f"sudo chown $(id -u):$(id -g) ~/.kube/config", silent=True, timeout=10)
            run("chmod 600 ~/.kube/config", silent=True, timeout=10)
            
            time.sleep(5)
            
            # Check again
            if run("kubectl get nodes", silent=True, timeout=10):
                step("k3s fixed successfully with new network!")
            else:
                step("k3s fix failed - manual intervention needed", False)
                print("\n  Run this script manually:")
                print("    bash run_files/fix_k3s_network.sh")
                sys.exit(1)
        else:
            print("\n  Run this script manually to fix:")
            print("    bash run_files/fix_k3s_network.sh")
            sys.exit(1)
    else:
        step("Kubernetes API server accessible")

    if not run("docker --version", silent=True):
        step("Docker not installed", False)
        sys.exit(1)
    step("Docker found")

    if not run("docker ps", silent=True):
        step("Docker daemon not running", False)
        print("Start it: sudo systemctl start docker")
        sys.exit(1)
    step("Docker daemon running")

    if run("nvidia-smi", silent=True):
        step("GPU detected")
    else:
        step("No GPU detected — scaling will still run", False)


# ----------------------------------------------------------
# STEP 2 — BUILD IMAGE
# ----------------------------------------------------------

def build_image():
    header("Step 2/6: Building image")

    if not os.path.exists("Dockerfile.gpu"):
        step("Dockerfile.gpu missing", False)
        sys.exit(1)

    if not run("docker build -f Dockerfile.gpu -t userscale-gpu:latest .", timeout=1200):
        step("Image build failed", False)
        sys.exit(1)

    step("Image built successfully")


# ----------------------------------------------------------
# STEP 3 — LOAD IMAGE INTO K3S CONTAINERD
# ----------------------------------------------------------

def load_image():
    header("Step 3/6: Loading image into k3s")

    step("Saving image…")
    run("docker save userscale-gpu:latest -o userscale.tar")

    # detect mode
    if os.path.exists("/usr/local/bin/k3s"):
        import_cmd = "sudo k3s ctr images import userscale.tar"
    else:
        import_cmd = "ctr --namespace k8s.io images import userscale.tar"

    step("Importing into containerd…")
    if not run(import_cmd):
        step("Failed to import image", False)
        sys.exit(1)

    os.remove("userscale.tar")
    step("Image available inside k3s")


# ----------------------------------------------------------
# STEP 4 — DEPLOY
# ----------------------------------------------------------

def deploy():
    header("Step 5/6: Deploying manifests")

    # Quick check if namespace exists
    result = subprocess.run(
        "kubectl get namespace userscale 2>&1",
        shell=True,
        capture_output=True,
        text=True
    )
    
    namespace_exists = "userscale" in result.stdout and "NotFound" not in result.stderr
    
    if namespace_exists:
        step("Namespace exists, cleaning up...")
        
        # Scale down deployments first (faster cleanup)
        run("kubectl scale deployment --all -n userscale --replicas=0", silent=True, timeout=10)
        time.sleep(2)
        
        # Delete resources in parallel
        run("kubectl delete hpa --all -n userscale --ignore-not-found=true --timeout=10s", silent=True, timeout=15)
        run("kubectl delete deployment --all -n userscale --ignore-not-found=true --timeout=10s", silent=True, timeout=15)
        run("kubectl delete service --all -n userscale --ignore-not-found=true --timeout=10s", silent=True, timeout=15)
        
        # Force delete namespace
        run("kubectl patch namespace userscale -p '{\"metadata\":{\"finalizers\":[]}}' --type=merge", silent=True, timeout=5)
        run("kubectl delete namespace userscale --force --grace-period=0", silent=True, timeout=10)
        
        # Wait for deletion (max 20 seconds)
        for i in range(20):
            result = subprocess.run(
                "kubectl get namespace userscale 2>&1",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if "NotFound" in result.stderr or "not found" in result.stdout.lower():
                break
            time.sleep(1)
        
        step("Namespace cleaned")
    
    # Create namespace
    run("kubectl create namespace userscale", silent=True, timeout=10)
    step("Namespace created")

    # Apply manifests
    for m in ["k8s/userscale-gpu.yaml", "k8s/hpa-gpu.yaml"]:
        if not os.path.exists(m):
            step(f"Missing manifest: {m}", False)
            sys.exit(1)
        step(f"Applying {m}")
        run(f"kubectl apply -f {m}", timeout=30)
    
    step("Manifests applied")


# ----------------------------------------------------------
# STEP 5 — GPU TIME-SLICING CONFIG
# ----------------------------------------------------------

def configure_gpu_timeslicing():
    header("Step 4/6: Configuring NVIDIA GPU time-slicing")

    cfg = "k8s/gpu-timeslice-config.yaml"
    if not os.path.exists(cfg):
        step("gpu-timeslice-config.yaml not found; skipping", False)
        return
    
    # Check if GPU operator exists
    result = subprocess.run(
        "kubectl get namespace gpu-operator 2>&1",
        shell=True,
        capture_output=True,
        text=True
    )
    
    if "NotFound" in result.stderr or "not found" in result.stdout.lower():
        step("GPU operator not installed; skipping time-slicing config", False)
        return
    
    step(f"Applying {cfg}")
    run(f"kubectl apply -f {cfg}", timeout=30)

    step("Restarting NVIDIA device plugin")
    run("kubectl rollout restart daemonset nvidia-device-plugin-daemonset -n gpu-operator", silent=True, timeout=30)
    
    # Don't wait for rollout - let it happen in background
    step("GPU time-slicing configured (restart in progress)")


# ----------------------------------------------------------
# STEP 6 — WAIT READY
# ----------------------------------------------------------

def wait_ready():
    header("Step 6/6: Waiting for workloads")

    apps = ["userscale-app", "userscale-scaler", "hpa-app"]

    for app in apps:
        step(f"Waiting for {app}...")
        result = subprocess.run(
            f"kubectl wait --for=condition=available --timeout=120s deployment/{app} -n userscale 2>&1",
            shell=True,
            capture_output=True,
            text=True,
            timeout=130
        )
        if result.returncode == 0:
            step(f"{app} ready")
        else:
            step(f"{app} not ready (timeout)", False)
            print(f"  Status: {result.stdout}")

    print("\nCurrent pods:")
    run("kubectl get pods -n userscale -o wide", timeout=10)


# ----------------------------------------------------------
# SMOKE TEST + PORT FORWARD
# ----------------------------------------------------------


def smoke_test():
    header("Smoke test: health check")

    step("Checking /healthz on userscale-app")
    result = subprocess.run(
        "kubectl run tmp-healthz --rm -i --restart=Never -n userscale --image=curlimages/curl:8.5.0 --command -- curl -sS http://userscale-app:8000/healthz",
        shell=True,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode == 0 and "ok" in result.stdout:
        step("Health check passed")
    else:
        step("Health check failed (service may still be starting)", False)
        print(f"  Response: {result.stdout}")


def forward():
    header("Port-forward: local access")

    run("pkill -f 'kubectl port-forward'", silent=True, timeout=5)
    time.sleep(1)

    subprocess.Popen("kubectl port-forward -n userscale svc/userscale-app 8001:8000",
                     shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    subprocess.Popen("kubectl port-forward -n userscale svc/hpa-app 8002:8000",
                     shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(2)
    step("Port-forward active")
    print("  userscale: http://localhost:8001")
    print("  hpa:       http://localhost:8002")


# ----------------------------------------------------------
# CLEANUP
# ----------------------------------------------------------

def cleanup():
    header("Cleanup")
    
    # Kill port forwards
    run("pkill -f 'kubectl port-forward'", silent=True, timeout=5)
    
    # Quick cleanup
    step("Scaling down deployments...")
    run("kubectl scale deployment --all -n userscale --replicas=0", silent=True, timeout=10)
    time.sleep(2)
    
    step("Deleting resources...")
    run("kubectl delete hpa --all -n userscale --ignore-not-found=true --timeout=5s", silent=True, timeout=10)
    run("kubectl delete deployment --all -n userscale --ignore-not-found=true --timeout=5s", silent=True, timeout=10)
    
    step("Removing namespace...")
    run("kubectl patch namespace userscale -p '{\"metadata\":{\"finalizers\":[]}}' --type=merge", silent=True, timeout=5)
    run("kubectl delete namespace userscale --force --grace-period=0 --ignore-not-found=true", silent=True, timeout=10)
    
    # Wait max 15 seconds
    for i in range(15):
        result = subprocess.run(
            "kubectl get namespace userscale 2>&1",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if "NotFound" in result.stderr or "not found" in result.stdout.lower():
            break
        time.sleep(1)
    
    step("Cleanup complete")


# ----------------------------------------------------------
# MAIN
# ----------------------------------------------------------

def run_dependency_check():
    header("Step 0/6: Dependency Check")
    
    script_path = os.path.join(os.path.dirname(__file__), "download_dependencies.py")
    if os.path.exists(script_path):
        step("Running download_dependencies.py...")
        result = subprocess.run([sys.executable, script_path], timeout=600)
        if result.returncode != 0:
            step("Dependency check failed", False)
            print("Please fix the issues and run again")
            sys.exit(1)
        step("Dependencies verified")
    else:
        step("download_dependencies.py not found, skipping", False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--skip-deps", action="store_true", help="Skip dependency check")
    args = p.parse_args()

    if args.cleanup:
        cleanup()
        sys.exit(0)

    if not args.skip_deps:
        run_dependency_check()
    
    check_prereq()
    build_image()
    load_image()
    configure_gpu_timeslicing()
    deploy()
    wait_ready()
    smoke_test()
    forward()

    print("\nDeployment complete!")
    print("Next steps:")
    print("  python3 run_files/demo.py")
    print("  python3 run_files/watch_gpu_metrics.py  (in another terminal)")
    print("  python3 run_files/watch_scaling.py      (in another terminal)")


if __name__ == "__main__":
    main()
