#!/usr/bin/env python3
"""
Complete Dependency Checker and Installer
Verifies and installs all required tools, packages, and configurations
"""

import subprocess
import sys
import os

def run_cmd(cmd, silent=False):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if not silent and result.stdout:
            print(result.stdout.strip())
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_and_install(name, check_cmd, install_cmd=None, required=True):
    print(f"\n{'='*60}")
    print(f"Checking: {name}")
    print(f"{'='*60}")
    
    success, stdout, stderr = run_cmd(check_cmd, silent=True)
    
    if success:
        print(f"[OK] {name} is installed")
        if stdout:
            print(f"   {stdout.strip()[:100]}")
        return True
    else:
        print(f"[FAIL] {name} is NOT installed")
        
        if not required:
            print(f"WARNING: {name} is optional, continuing...")
            return True
        
        if install_cmd:
            print(f"Installing {name}...")
            success, _, _ = run_cmd(install_cmd)
            if success:
                print(f"[OK] {name} installed successfully")
                return True
            else:
                print(f"[FAIL] Failed to install {name}")
                return False
        else:
            print(f"WARNING: Please install {name} manually")
            return False

def main():
    print("\n" + "="*60)
    print("  DEPENDENCY CHECKER AND INSTALLER")
    print("="*60 + "\n")
    
    all_ok = True
    
    # 1. Python and pip
    all_ok &= check_and_install(
        "Python 3",
        "python3 --version",
        required=True
    )
    
    # Try pip3, fallback to python3 -m pip
    pip_ok = check_and_install(
        "pip3",
        "pip3 --version",
        required=False
    )
    
    if not pip_ok:
        pip_ok = check_and_install(
            "pip (via python3 -m pip)",
            "python3 -m pip --version",
            required=True
        )
    
    all_ok &= pip_ok
    
    # 2. Docker
    all_ok &= check_and_install(
        "Docker",
        "docker --version",
        required=True
    )
    
    all_ok &= check_and_install(
        "Docker daemon",
        "docker ps",
        required=True
    )
    
    # 3. Kubernetes
    all_ok &= check_and_install(
        "kubectl",
        "kubectl version --client",
        required=True
    )
    
    all_ok &= check_and_install(
        "Kubernetes cluster",
        "kubectl cluster-info",
        required=True
    )
    
    # 4. NVIDIA GPU
    gpu_available = check_and_install(
        "nvidia-smi",
        "nvidia-smi",
        required=False
    )
    
    if gpu_available:
        check_and_install(
            "NVIDIA GPU details",
            "nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader",
            required=False
        )
    
    # 5. Python packages
    print(f"\n{'='*60}")
    print("Installing Python dependencies...")
    print(f"{'='*60}")
    
    packages = [
        "fastapi",
        "uvicorn[standard]",
        "numpy",
        "requests",
        "psutil",
        "pydantic",
        "kubernetes",
        "httpx",
        "tenacity",
        "nvidia-ml-py3",
        "cupy-cuda12x"
    ]
    
    # Determine pip command
    pip_cmd = "pip3"
    success, _, _ = run_cmd("pip3 --version", silent=True)
    if not success:
        pip_cmd = "python3 -m pip"
    
    for pkg in packages:
        print(f"Checking {pkg}...")
        # Try to import first
        pkg_import = pkg.split('[')[0].replace('-', '_')
        success, _, _ = run_cmd(f"python3 -c 'import {pkg_import}'", silent=True)
        if success:
            print(f"[OK] {pkg} already installed")
        else:
            print(f"Installing {pkg}...")
            success, _, _ = run_cmd(f"{pip_cmd} install {pkg}", silent=True)
            if success:
                print(f"[OK] {pkg} installed")
            else:
                print(f"WARNING: {pkg} installation failed (may need manual install)")
    
    # 6. Kubernetes metrics server
    print(f"\n{'='*60}")
    print("Checking Kubernetes metrics server...")
    print(f"{'='*60}")
    
    success, _, _ = run_cmd("kubectl get deployment metrics-server -n kube-system", silent=True)
    if success:
        print("[OK] Metrics server is deployed")
    else:
        print("WARNING: Metrics server not found")
        print("   HPA may not work without metrics server")
        print("   Install with: kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml")
    
    # 7. GPU Operator (if GPU available)
    if gpu_available:
        print(f"\n{'='*60}")
        print("Checking NVIDIA GPU Operator...")
        print(f"{'='*60}")
        
        success, _, _ = run_cmd("kubectl get pods -n gpu-operator", silent=True)
        if success:
            print("[OK] GPU Operator is deployed")
        else:
            print("WARNING: GPU Operator not found")
            print("   GPU time-slicing may not work")
    
    # 8. Verify namespace
    print(f"\n{'='*60}")
    print("Checking userscale namespace...")
    print(f"{'='*60}")
    
    success, _, _ = run_cmd("kubectl get namespace userscale", silent=True)
    if success:
        print("[OK] Namespace 'userscale' exists")
    else:
        print("WARNING: Namespace 'userscale' not found")
        print("   Will be created by setup.py")
    
    # Final summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}\n")
    
    # Final summary
    print(f"\n{'='*60}")
    print("  FINAL STATUS")
    print(f"{'='*60}\n")
    
    if all_ok:
        print("[OK] ALL SYSTEM CHECKS PASSED!")
        print("\nNote: Python packages are installed in Docker image")
        print("   They don't need to be in system Python")
        print("\nEnvironment is ready!")
        print("\nNext steps:")
        print("  1. Run: python3 setup.py")
        print("  2. Run: python3 demo.py")
    else:
        print("[FAIL] Some system dependencies are missing")
        print("\nPlease install missing dependencies:")
        print("  - Docker")
        print("  - kubectl")
        print("  - Kubernetes cluster (k3s)")
        print("\nThen run again")

if __name__ == "__main__":
    main()
