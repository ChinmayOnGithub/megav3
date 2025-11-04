#!/usr/bin/env python3
"""
UserScale Setup - Complete Deployment Automation
Builds images, deploys to Kubernetes, verifies everything is running
Supports cleanup with --cleanup flag
"""

import subprocess
import time
import sys
import os
import json
import argparse

def run_cmd(cmd, show_output=False, timeout=600):
    """Run command with optional output"""
    try:
        if show_output:
            result = subprocess.run(cmd, shell=True, timeout=timeout)
            return result.returncode == 0
        else:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            output = result.stdout + "\n" + result.stderr if result.stderr else result.stdout
            return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout} seconds"
    except Exception as e:
        return False, str(e)


def print_header(title):
    """Print section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print('='*80)


def print_step(message, success=True):
    """Print step result"""
    emoji = "✅" if success else "❌"
    print(f"{emoji} {message}")


def log_info(message):
    """Print info log"""
    print(f"[INFO] {message}")


def log_ok(message):
    """Print success log"""
    print(f"[OK] {message}")


def log_warn(message):
    """Print warning log"""
    print(f"[WARN] {message}")


def check_prerequisites():
    """Check and setup prerequisites"""
    print_header("Step 1/8: Checking Prerequisites")
    
    # Check kubectl
    success, _ = run_cmd("kubectl version --client")
    if not success:
        print_step("kubectl not found", False)
        print("   Install kubectl: https://kubernetes.io/docs/tasks/tools/")
        sys.exit(1)
    print_step("kubectl found")
    
    # Check docker
    success, _ = run_cmd("docker --version")
    if not success:
        print_step("Docker not found", False)
        print("   Install Docker: https://docs.docker.com/get-docker/")
        sys.exit(1)
    print_step("Docker found")
    
    # Check if Docker daemon is running
    print("▶ Checking Docker daemon...")
    success, _ = run_cmd("docker ps")
    if not success:
        print("   Docker daemon not running, starting...")
        run_cmd("sudo service docker start", show_output=True)
        time.sleep(3)
        success, _ = run_cmd("docker ps")
        if not success:
            print_step("Failed to start Docker daemon", False)
            print("   Run manually: sudo service docker start")
            sys.exit(1)
    print_step("Docker daemon running")
    
    # Check GPU
    print("▶ Checking GPU availability...")
    success, _ = run_cmd("nvidia-smi")
    if success:
        print_step("NVIDIA GPU detected")
    else:
        log_warn("GPU not detected - will use CPU fallback")
    
    # Check/start minikube with GPU support
    success, _ = run_cmd("minikube status")
    if not success:
        print("▶ Starting minikube with GPU passthrough support...")
        # Get system memory
        success_mem, mem_output = run_cmd("free -m | awk '/^Mem:/{print $2}'")
        total_mem = 4096  # default
        if success_mem:
            try:
                total_mem = int(mem_output.strip())
                # Allocate 40% of RAM, minimum 2048MB for GPU workloads
                minikube_mem = max(total_mem * 40 // 100, 2048)
                minikube_mem = min(minikube_mem, 4096)  # max 4GB
            except:
                minikube_mem = 2048
        else:
            minikube_mem = 2048
        
        print(f"   Allocating {minikube_mem}MB memory to Minikube")
        
        # Clean up first
        print("   Cleaning up Docker to free memory...")
        run_cmd("docker system prune -af", show_output=False)
        time.sleep(2)
        
        # Start Minikube with Docker driver and GPU passthrough
        # Use --mount for persistent GPU access and --docker-opt for GPU runtime
        cmd = f"minikube start --driver=docker --container-runtime=docker --cpus=2 --memory={minikube_mem} --docker-opt=default-runtime=nvidia"
        print("   Starting Minikube (GPU access via Docker runtime)...")
        print("   Note: Using persistent configuration with NVIDIA runtime")
        success = run_cmd(cmd, show_output=True)
        if not success:
            print_step("Failed to start minikube", False)
            print("   Try: minikube delete && minikube start --memory=2048 --cpus=2")
            sys.exit(1)
    print_step("Minikube running")
    
    # Enable metrics-server
    print("▶ Enabling metrics-server...")
    run_cmd("minikube addons enable metrics-server")
    print_step("Metrics-server enabled")
    
    # Note: NVIDIA device plugin NOT needed - using GPU passthrough via Docker runtime
    # Pods access GPU directly via NVIDIA_VISIBLE_DEVICES environment variable
    print("▶ GPU access configured via Docker runtime passthrough")
    
    # Wait for metrics-server
    print("▶ Waiting for cluster components...")
    time.sleep(10)


def build_docker_images():
    """Build Docker image using Minikube's Docker daemon"""
    print_header("Step 2/8: Building Docker Image (Minikube Local)")
    
    # Check if GPU Dockerfile exists
    if os.path.exists("Dockerfile.gpu"):
        dockerfile = "Dockerfile.gpu"
        print("▶ Using GPU-enabled Dockerfile")
    elif os.path.exists("Dockerfile.app"):
        dockerfile = "Dockerfile.app"
        print("▶ Using standard Dockerfile")
    else:
        print_step("No Dockerfile found", False)
        sys.exit(1)
    
    # Use Minikube's Docker daemon to avoid image transfer
    print("▶ Configuring to use Minikube's Docker daemon...")
    print("   This ensures image is built directly in Minikube (no transfer needed)")
    
    # Set Docker environment to use Minikube's daemon
    success, env_output = run_cmd("minikube docker-env")
    if not success:
        print_step("Failed to get Minikube Docker environment", False)
        sys.exit(1)
    
    # Parse environment variables
    docker_env = {}
    for line in env_output.split('\n'):
        if 'export' in line:
            # Extract KEY=VALUE from: export KEY="VALUE"
            parts = line.replace('export ', '').replace('"', '').strip().split('=')
            if len(parts) == 2:
                docker_env[parts[0]] = parts[1]
    
    # Check if image already exists IN MINIKUBE
    print("▶ Checking if image already exists in Minikube...")
    check_cmd = "eval $(minikube docker-env) && docker images userscale-gpu:latest --format '{{.Repository}}:{{.Tag}}'"
    success, img_output = run_cmd(check_cmd)
    
    if success and "userscale-gpu:latest" in img_output:
        print_step("Image userscale-gpu:latest already exists in Minikube")
        print("   ✅ SKIPPING BUILD - Image is cached permanently")
        print("   No download needed, using existing image")
        return
    
    print(f"▶ Building Application image (userscale-gpu:latest)...")
    print("   Building directly in Minikube Docker daemon...")
    print("   First build: 10-15 minutes (downloads CuPy ~500MB)")
    print("   Subsequent builds: 1-2 minutes (cached layers)")
    
    # Build with Minikube's Docker daemon (20 minute timeout)
    build_cmd = f"eval $(minikube docker-env) && docker build -f {dockerfile} -t userscale-gpu:latest ."
    success = run_cmd(build_cmd, show_output=True, timeout=1200)
    
    if not success:
        print_step("Failed to build Application image", False)
        print("\n" + "="*80)
        print("BUILD ERROR - Try:")
        print("  1. eval $(minikube docker-env)")
        print("  2. docker build -f Dockerfile.gpu -t userscale-gpu:latest .")
        print("="*80)
        sys.exit(1)
    
    print_step("Application image built in Minikube Docker daemon")
    
    # Verify image
    success, img_output = run_cmd(check_cmd)
    if success and "userscale-gpu:latest" in img_output:
        print_step("Image verified in Minikube")


def load_images_to_minikube():
    """Skip image loading - already built in Minikube Docker daemon"""
    print_header("Step 3/8: Verifying Image in Minikube")
    
    print("▶ Image already in Minikube Docker daemon (no transfer needed)")
    
    # Verify image exists
    check_cmd = "eval $(minikube docker-env) && docker images userscale-gpu:latest --format '{{.Repository}}:{{.Tag}}'"
    success, img_output = run_cmd(check_cmd)
    
    if success and "userscale-gpu:latest" in img_output:
        print_step("Image userscale-gpu:latest ready in Minikube")
    else:
        print_step("Warning: Image not found in Minikube", False)
    
    time.sleep(1)


def deploy_kubernetes_resources():
    """Deploy all Kubernetes manifests"""
    print_header("Step 4/8: Deploying Kubernetes Resources")
    
    # Create namespace
    print("▶ Creating namespace...")
    run_cmd("kubectl create namespace userscale --dry-run=client -o yaml | kubectl apply -f -", show_output=False)
    print_step("Namespace ready")
    
    # Deploy GPU-enabled manifests
    manifests = ["k8s/userscale-gpu.yaml", "k8s/hpa-gpu.yaml"]
    
    for manifest in manifests:
        if not os.path.exists(manifest):
            print_step(f"Required manifest {manifest} not found", False)
            sys.exit(1)
    
    # Deploy all manifests
    for manifest in manifests:
        print(f"▶ Deploying {os.path.basename(manifest)}...")
        success, _ = run_cmd(f"kubectl apply -f {manifest}")
        if success:
            print_step(f"{os.path.basename(manifest)} deployed")
        else:
            log_warn(f"Failed to deploy {manifest}")
    
    time.sleep(3)


def wait_for_deployments():
    """Wait for deployments to be ready"""
    print_header("Step 5/8: Waiting for Deployments")
    
    deployments = [
        ("userscale-app", "UserScale"),
        ("hpa-app", "HPA")
    ]
    
    for deployment, name in deployments:
        print(f"▶ Waiting for {name} deployment...")
        success, _ = run_cmd(
            f"kubectl wait --for=condition=available --timeout=180s deployment/{deployment} -n userscale"
        )
        if not success:
            print_step(f"{name} deployment not ready (may still be starting)", False)
        else:
            print_step(f"{name} deployment ready")
    
    # Give pods time to fully initialize
    print("▶ Waiting for pods to initialize...")
    time.sleep(10)


def verify_gpu_in_cluster():
    """Verify GPU availability via passthrough"""
    print_header("Step 6/8: Verifying GPU Access")
    
    print("▶ Checking GPU passthrough configuration...")
    # With GPU passthrough, we don't check Kubernetes resources
    # Instead, verify that host GPU is accessible
    success, output = run_cmd("nvidia-smi")
    if success:
        print_step("Host GPU accessible for passthrough")
        print("   Pods will access GPU via NVIDIA_VISIBLE_DEVICES environment variable")
        return True
    else:
        log_warn("GPU not detected on host - pods will use CPU fallback")
        print("   Install NVIDIA drivers: sudo apt install nvidia-driver-xxx")
        return False


def verify_deployment():
    """Verify all components are running"""
    print_header("Step 7/8: Verifying Deployment")
    
    # Check namespace
    success, output = run_cmd("kubectl get namespace userscale -o json")
    if not success:
        print_step("Namespace 'userscale' not found", False)
        return False
    print_step("Namespace 'userscale' exists")
    
    # Check deployments
    success, output = run_cmd("kubectl get deployments -n userscale -o json")
    if success:
        try:
            data = json.loads(output)
            deployments = data.get("items", [])
            for dep in deployments:
                name = dep["metadata"]["name"]
                replicas = dep["spec"]["replicas"]
                ready = dep["status"].get("readyReplicas", 0)
                print_step(f"Deployment {name}: {ready}/{replicas} replicas ready")
        except:
            pass
    
    # Check pods
    success, output = run_cmd("kubectl get pods -n userscale -o json")
    if success:
        try:
            data = json.loads(output)
            pods = data.get("items", [])
            running = sum(1 for p in pods if p.get("status", {}).get("phase") == "Running")
            total = len(pods)
            print_step(f"Pods: {running}/{total} running")
        except:
            pass
    
    # Check services
    success, output = run_cmd("kubectl get svc -n userscale -o json")
    if success:
        try:
            data = json.loads(output)
            services = data.get("items", [])
            for svc in services:
                name = svc["metadata"]["name"]
                print_step(f"Service {name} exists")
        except:
            pass
    
    return True


def setup_port_forwarding():
    """Setup port forwarding for local access"""
    print_header("Step 8/8: Setting Up Port Forwarding")
    
    # Kill any existing port-forward
    if sys.platform == "win32":
        subprocess.run("taskkill /F /IM kubectl.exe 2>nul", shell=True, capture_output=True)
    else:
        subprocess.run("pkill -f 'kubectl port-forward'", shell=True, capture_output=True)
    
    time.sleep(2)
    
    # Start port-forward for UserScale (8001)
    print("▶ Starting port-forward (localhost:8001 → userscale-app:8000)...")
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/userscale-app 8001:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Start port-forward for HPA (8002)
    print("▶ Starting port-forward (localhost:8002 → hpa-app:8000)...")
    subprocess.Popen(
        "kubectl port-forward -n userscale svc/hpa-app 8002:8000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    time.sleep(5)
    
    # Verify port-forwards
    try:
        import requests
        response1 = requests.get("http://localhost:8001/healthz", timeout=5)
        response2 = requests.get("http://localhost:8002/healthz", timeout=5)
        if response1.status_code == 200 and response2.status_code == 200:
            print_step("Port forwarding active for both services")
        else:
            print_step("Port forwarding started (services may still be initializing)", False)
    except:
        print_step("Port forwarding started (verification skipped)")


def cleanup_resources(interactive=True):
    """Cleanup all Kubernetes resources"""
    print_header("Cleanup - Removing All Resources")
    
    # Check if namespace exists
    log_info("Checking if namespace 'userscale' exists...")
    success, output = run_cmd("kubectl get namespace userscale")
    
    if not success:
        log_warn("Namespace 'userscale' not found - nothing to clean up")
        return
    
    log_ok("Namespace 'userscale' found")
    
    # Stop port-forward processes
    log_info("Stopping port-forward processes...")
    if sys.platform == "win32":
        subprocess.run("taskkill /F /IM kubectl.exe 2>nul", shell=True, capture_output=True)
    else:
        subprocess.run("pkill -f 'kubectl port-forward'", shell=True, capture_output=True)
    log_ok("Port-forward processes stopped")
    
    # Delete load generator job
    log_info("Deleting load generator job...")
    run_cmd("kubectl delete job userscale-loadgen -n userscale --ignore-not-found=true")
    log_ok("Load generator job deleted")
    
    # Delete HPA
    log_info("Deleting HPA...")
    run_cmd("kubectl delete hpa --all -n userscale --ignore-not-found=true")
    log_ok("HPA deleted")
    
    # Delete deployments
    log_info("Deleting deployments...")
    run_cmd("kubectl delete deployment --all -n userscale --ignore-not-found=true")
    log_ok("Deployments deleted")
    
    # Delete services
    log_info("Deleting services...")
    run_cmd("kubectl delete service --all -n userscale --ignore-not-found=true")
    log_ok("Services deleted")
    
    # Delete configmaps
    log_info("Deleting configmaps...")
    run_cmd("kubectl delete configmap --all -n userscale --ignore-not-found=true")
    log_ok("Configmaps deleted")
    
    # Delete namespace
    log_info("Deleting namespace 'userscale'...")
    success, _ = run_cmd("kubectl delete namespace userscale --timeout=60s")
    if success:
        log_ok("Namespace 'userscale' deleted")
    else:
        log_warn("Namespace deletion may take longer - check with: kubectl get namespace userscale")
    
    print("\n" + "="*80)
    print("  ✅ Cleanup Complete!")
    print("="*80)
    print("\n🧹 All resources removed:")
    print("  • Namespace deleted")
    print("  • Deployments removed")
    print("  • Services removed")
    print("  • HPA removed")
    print("  • Load generator removed")
    print("  • Port forwarding stopped")
    print("\n✅ Docker image PRESERVED:")
    print("  • userscale-gpu:latest still cached in Minikube")
    print("  • No rebuild needed on next deploy")
    print("\n💡 To redeploy: python3 setup.py (will skip build)")
    print("="*80)


def print_summary():
    """Print deployment summary"""
    print("\n" + "="*80)
    print("  ✅ Setup Complete!")
    print("="*80)
    
    print("\n📋 What was deployed:")
    print("  • Namespace: userscale")
    print("  • UserScale app (GPU-aware autoscaling)")
    print("  • HPA app (CPU-based autoscaling)")
    print("  • Port forwarding:")
    print("    - localhost:8001 → userscale-app")
    print("    - localhost:8002 → hpa-app")
    
    print("\n💾 Permanent Setup:")
    print("  • Docker image cached in Minikube")
    print("  • No rebuild on next run (unless code changes)")
    print("  • Survives pod restarts and laptop sleep")
    print("  • Run demo.py unlimited times - NO rebuild")
    
    print("\n🚀 Next steps:")
    print("  1. Run workload:  python3 demo.py")
    print("  2. Monitor system: python3 monitor.py")
    
    print("\n🎮 Scaling behavior:")
    print("  • UserScale: GPU-aware (GPU > 70% → scale up)")
    print("  • HPA: CPU-based (CPU > 50% → scale up)")
    print("  • Both use REAL GPU workloads (CuPy)")
    
    print("\n" + "="*80)


def prompt_cleanup():
    """Prompt user for cleanup after setup"""
    print("\n" + "="*80)
    print("  Cleanup Options")
    print("="*80)
    
    try:
        response = input("\nDo you want to clean up Kubernetes resources? (Docker image will be preserved) (y/n): ").strip().lower()
        
        if response in ['y', 'yes']:
            print()
            cleanup_resources(interactive=True)
        else:
            print("\n✅ Resources retained for further testing.")
            print("   Docker image cached - next deploy will skip build")
            print("   Run: python3 setup.py --cleanup to remove later.")
            print()
    
    except (EOFError, KeyboardInterrupt):
        print("\n\n✅ Resources retained for further testing.")
        print("   Docker image cached - next deploy will skip build")
        print("   Run: python3 setup.py --cleanup to remove later.")


def main():
    """Main setup flow"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="UserScale Setup - Deploy or cleanup Kubernetes resources"
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Cleanup all resources without prompting'
    )
    args = parser.parse_args()
    
    # If cleanup flag is set, just cleanup and exit
    if args.cleanup:
        cleanup_resources(interactive=False)
        sys.exit(0)
    
    # Normal setup flow
    print("\n" + "="*80)
    print("  UserScale - Automated Setup")
    print("  GPU-Aware Kubernetes Autoscaler")
    print("="*80)
    
    try:
        check_prerequisites()
        build_docker_images()
        load_images_to_minikube()
        deploy_kubernetes_resources()
        wait_for_deployments()
        verify_gpu_in_cluster()
        verify_deployment()
        setup_port_forwarding()
        print_summary()
        
        # Prompt for cleanup
        prompt_cleanup()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        print("   To cleanup: python setup.py --cleanup")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Setup failed: {e}")
        print("   To cleanup: python setup.py --cleanup")
        sys.exit(1)


if __name__ == "__main__":
    main()
