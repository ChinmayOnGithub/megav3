#!/usr/bin/env python3
"""
GPU Verification Script
Checks if GPU is properly configured for the project
"""

import subprocess
import sys

def check_nvidia_smi():
    """Check if nvidia-smi is available"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("✅ nvidia-smi detected")
            print(f"   GPU: {result.stdout.strip()}")
            return True
        else:
            print("❌ nvidia-smi failed")
            return False
    except Exception as e:
        print(f"❌ nvidia-smi not found: {e}")
        return False

def check_pynvml():
    """Check if pynvml can access GPU"""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        
        print("✅ pynvml working")
        print(f"   Device: {name}")
        print(f"   Utilization: {util.gpu}%")
        print(f"   Memory: {mem.used / (1024**2):.0f} MB / {mem.total / (1024**2):.0f} MB")
        print(f"   Temperature: {temp}°C")
        
        pynvml.nvmlShutdown()
        return True
    except ImportError:
        print("❌ pynvml not installed")
        print("   Install: pip install nvidia-ml-py3")
        return False
    except Exception as e:
        print(f"❌ pynvml error: {e}")
        return False

def check_cupy():
    """Check if CuPy can use GPU"""
    try:
        import cupy as cp
        
        # Test GPU computation
        a = cp.random.rand(100, 100)
        b = cp.random.rand(100, 100)
        c = cp.matmul(a, b)
        result = float(cp.sum(c))
        
        device = cp.cuda.Device(0)
        props = cp.cuda.runtime.getDeviceProperties(0)
        gpu_name = props['name'].decode()
        
        print("✅ CuPy working")
        print(f"   Device: {gpu_name}")
        print(f"   Test computation result: {result:.2f}")
        return True
    except ImportError:
        print("❌ CuPy not installed")
        print("   Install: pip install cupy-cuda12x")
        return False
    except Exception as e:
        print(f"❌ CuPy error: {e}")
        return False

def check_docker_gpu():
    """Check if Docker has GPU support"""
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:12.2.0-base-ubuntu22.04", "nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print("✅ Docker GPU support working")
            return True
        else:
            print("❌ Docker GPU support failed")
            print(f"   Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Docker GPU test error: {e}")
        return False

def main():
    print("="*80)
    print("  GPU VERIFICATION FOR MEGA_PROJECT_SEMVII")
    print("="*80)
    print()
    
    results = {}
    
    print("1. Checking nvidia-smi...")
    results['nvidia-smi'] = check_nvidia_smi()
    print()
    
    print("2. Checking pynvml...")
    results['pynvml'] = check_pynvml()
    print()
    
    print("3. Checking CuPy...")
    results['cupy'] = check_cupy()
    print()
    
    print("4. Checking Docker GPU support...")
    results['docker-gpu'] = check_docker_gpu()
    print()
    
    print("="*80)
    print("  SUMMARY")
    print("="*80)
    
    all_passed = all(results.values())
    
    for component, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {component:20s} {status}")
    
    print()
    
    if all_passed:
        print("🎉 All GPU checks passed! System is ready.")
        print()
        print("Next steps:")
        print("  1. Run: python3 setup.py")
        print("  2. Run: python3 demo.py")
        print("  3. Run: python3 monitor.py")
        return 0
    else:
        print("⚠️  Some GPU checks failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
