#!/usr/bin/env python3
"""
Unified FastAPI application supporting two workload types:
1. Matrix Multiplication (existing)
2. Data Sorting/Simulation (new - CPU/Memory/GPU intensive)

Workload selection via WORKLOAD_TYPE environment variable.
Metrics focused on: Average Latency and Active Users (for replica scaling)
"""

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import os
import time
import psutil
import numpy as np
from typing import Dict, Any
import threading
from concurrent.futures import ThreadPoolExecutor
import asyncio

try:
    import cupy as cp
    GPU_AVAILABLE = True
except Exception:
    cp = None
    GPU_AVAILABLE = False

# Try to import pynvml for GPU metrics
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_METRICS_AVAILABLE = True
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
except:
    GPU_METRICS_AVAILABLE = False
    GPU_HANDLE = None

# Configuration
WORKLOAD_TYPE = os.getenv("WORKLOAD_TYPE", "matrix").lower()  # "matrix" or "sorting"
CPU_THREADS = max(1, int(os.getenv("CPU_THREADS", "4")))
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(
    title=f"Userscale App - {WORKLOAD_TYPE.capitalize()} Workload",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

# Global state
start_time = time.time()
active_users = 0
concurrent_requests = 0
latency_samples: list = []
latency_lock = threading.Lock()
request_count = 0

# Thread pool for compute tasks
executor = ThreadPoolExecutor(max_workers=CPU_THREADS, thread_name_prefix="compute")

# Matrix workload cache
matrix_cache = {}


def record_latency(ms: float, limit: int = 200):
    """Record latency sample"""
    with latency_lock:
        latency_samples.append(ms)
        if len(latency_samples) > limit:
            latency_samples.pop(0)


def get_avg_latency() -> float:
    """Get average latency from recent samples"""
    with latency_lock:
        if not latency_samples:
            return 0.0
        return sum(latency_samples) / len(latency_samples)


def get_gpu_metrics() -> Dict[str, Any]:
    """Get REAL GPU utilization and memory metrics using pynvml - NO SIMULATION"""
    if not GPU_METRICS_AVAILABLE or not GPU_HANDLE:
        # Return zeros if GPU not available - NO FAKE DATA
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0,
            "error": "GPU not available or pynvml not initialized"
        }
    
    try:
        # Get REAL metrics from actual GPU hardware via pynvml
        util = pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
        temp = pynvml.nvmlDeviceGetTemperature(GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)
        
        return {
            "gpu_utilization": float(util.gpu),
            "gpu_memory_used_mb": int(mem_info.used / (1024 * 1024)),
            "gpu_memory_total_mb": int(mem_info.total / (1024 * 1024)),
            "gpu_memory_percent": round((mem_info.used / mem_info.total) * 100, 1),
            "gpu_temperature": int(temp)
        }
    except Exception as e:
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0,
            "error": str(e)
        }


# ============================================================================
# WORKLOAD 1: Matrix Multiplication
# ============================================================================

def matrix_multiply_cpu(size: int) -> float:
    """CPU-based matrix multiplication using NumPy - intensive version"""
    # Perform multiple iterations to increase CPU load
    iterations = 3
    total = 0.0
    for _ in range(iterations):
        a = np.random.rand(size, size).astype(np.float32)
        b = np.random.rand(size, size).astype(np.float32)
        c = a @ b
        # Additional operations to increase load
        c = np.sin(c) + np.cos(c * 0.5)
        total += float(np.sum(c))
    return total / iterations


def matrix_multiply_gpu(size: int) -> float:
    """REAL GPU-based matrix multiplication using CuPy - HIGHLY INTENSIVE CUDA operations
    Optimized for GTX 1050 Ti and similar GPUs to generate measurable load"""
    if not GPU_AVAILABLE:
        return matrix_multiply_cpu(size)
    
    # ULTRA INTENSIVE: Designed to saturate GPU and trigger scaling
    # Use larger matrices and more iterations for real GPU load
    actual_size = max(size, 800)  # Minimum 800x800 for real GPU load
    iterations = max(10, 100000 // (actual_size + 1))  # Scale iterations inversely with size
    total = 0.0
    
    for _ in range(iterations):
        # Create large matrices on GPU
        a = cp.random.rand(actual_size, actual_size, dtype=cp.float32)
        b = cp.random.rand(actual_size, actual_size, dtype=cp.float32)
        
        # Multiple matrix multiplications to saturate GPU
        c = cp.matmul(a, b)
        c = cp.matmul(c, a)  # Chain multiplication
        c = cp.matmul(c, b)  # More multiplication
        
        # Intensive element-wise GPU operations (5 passes instead of 3)
        for _ in range(5):
            c = cp.sin(c) + cp.cos(c * 0.5)
            c = cp.sqrt(cp.abs(c) + 1.0)
            c = cp.tanh(c) * cp.exp(-cp.abs(c) * 0.01)
            c = cp.power(c, 1.5)  # Additional power operation
        
        # Sum and transfer result
        result = float(cp.sum(c).get())
        total += result
        
        # Clean up GPU memory
        del a, b, c
    
    # Ensure all GPU operations complete
    cp.cuda.Stream.null.synchronize()
    
    return total / iterations


# ============================================================================
# WORKLOAD 2: Data Sorting/Simulation (CPU/Memory/GPU intensive)
# ============================================================================

def cpu_monte_carlo(num_samples: int) -> float:
    """CPU Monte Carlo simulation - intensive version"""
    # Run multiple iterations
    iterations = 2
    total = 0.0
    for _ in range(iterations):
        x = np.random.random(num_samples)
        y = np.random.random(num_samples)
        inside = (x**2 + y**2) <= 1.0
        # Additional computations
        result = 4.0 * np.sum(inside) / num_samples
        # Add some trigonometric operations
        extra = np.mean(np.sin(x) * np.cos(y))
        total += result + extra
    return total / iterations


def memory_sort_shuffle(size_mb: int) -> float:
    """Memory-intensive sorting - intensive version"""
    num_elements = (size_mb * 1024 * 1024) // 8
    # Multiple sort operations
    iterations = 2
    total = 0.0
    for _ in range(iterations):
        arr = np.random.random(num_elements)
        arr = np.sort(arr)
        # Additional operations
        arr = arr ** 2 + np.sqrt(arr + 1)
        total += float(np.sum(arr[:1000]))
    return total / iterations


def gpu_sort_compute(num_elements: int = 10_000_000) -> float:
    """REAL GPU-intensive sorting and computation using CuPy - CUDA operations
    Optimized for real GPU load generation"""
    if not GPU_AVAILABLE:
        # CPU fallback
        arr = np.random.random(num_elements).astype(np.float32)
        arr.sort(kind="quicksort")
        checksum = float(arr[:1_000_000].sum()) if num_elements >= 1_000_000 else float(arr.sum())
        del arr
        return checksum
    
    # ULTRA INTENSIVE: More iterations and operations for real GPU load
    actual_elements = max(num_elements, 15_000_000)  # Minimum 15M elements
    iterations = 5  # More iterations
    total = 0.0
    
    for _ in range(iterations):
        # Create large array on GPU
        arr = cp.random.random(actual_elements, dtype=cp.float32)
        
        # GPU sorting (expensive operation)
        arr = cp.sort(arr)
        
        # Multiple passes of intensive GPU computations
        for _ in range(3):
            arr = cp.sin(arr) + cp.cos(arr * 0.5)
            arr = cp.sqrt(cp.abs(arr) + 1.0)
            arr = arr ** 2
            arr = cp.tanh(arr)
        
        # Sum result
        checksum = float(cp.sum(arr[:1_000_000]).get()) if actual_elements >= 1_000_000 else float(cp.sum(arr).get())
        total += checksum
        
        # Clean up
        del arr
    
    # Ensure all GPU operations complete
    cp.cuda.Stream.null.synchronize()
    
    return total / iterations


def sorting_simulation_workload(complexity: int = 2) -> Dict[str, float]:
    """
    Combined sorting/simulation workload
    complexity: 1=light, 2=medium, 3=heavy
    """
    results = {}
    
    if complexity >= 1:
        # CPU Monte Carlo
        results['monte_carlo'] = cpu_monte_carlo(3_000_000 * complexity)
    
    if complexity >= 2:
        # Memory sorting
        results['memory_sort'] = memory_sort_shuffle(256 * complexity)
    
    if complexity >= 2 and GPU_AVAILABLE:
        # GPU sorting
        results['gpu_sort'] = gpu_sort_compute(4_000_000 * complexity)
    
    return results


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_s": int(time.time() - start_time),
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE
    }


@app.get("/compute")
async def compute(
    size: int = Query(500, ge=100, le=2000, description="Matrix size or complexity level"),
    use_gpu: bool = Query(True, description="Use GPU if available")  # Default to True
):
    """
    Unified compute endpoint that adapts based on WORKLOAD_TYPE
    - matrix mode: performs matrix multiplication (GPU-accelerated)
    - sorting mode: performs sorting/simulation workload (GPU-accelerated)
    
    GPU is used by default to generate real GPU load for scaling
    """
    global active_users, concurrent_requests, request_count
    
    concurrent_requests += 1
    active_users = concurrent_requests
    request_count += 1
    t0 = time.time()
    
    try:
        loop = asyncio.get_event_loop()
        
        if WORKLOAD_TYPE == "matrix":
            # Matrix multiplication workload - ALWAYS use GPU if available
            if GPU_AVAILABLE:
                result = await loop.run_in_executor(executor, matrix_multiply_gpu, size)
                workload_used = "matrix_gpu"
            else:
                result = await loop.run_in_executor(executor, matrix_multiply_cpu, size)
                workload_used = "matrix_cpu"
            
            response = {
                "workload": workload_used,
                "size": size,
                "result": result,
                "gpu_used": GPU_AVAILABLE
            }
        
        else:  # sorting mode
            # Sorting/simulation workload - ALWAYS use GPU if available
            complexity = max(1, min(3, size // 500))  # Map size to complexity 1-3
            results = await loop.run_in_executor(
                executor, 
                sorting_simulation_workload, 
                complexity
            )
            
            response = {
                "workload": "sorting_simulation",
                "complexity": complexity,
                "results": results,
                "gpu_used": GPU_AVAILABLE and 'gpu_sort' in results
            }
        
        return response
    
    finally:
        dt = (time.time() - t0) * 1000
        record_latency(dt)
        concurrent_requests -= 1
        active_users = max(concurrent_requests, 0)


@app.get("/matrix")
async def matrix_endpoint(size: int = Query(500, ge=100, le=2000)):
    """Legacy matrix endpoint for backward compatibility"""
    return await compute(size=size, use_gpu=False)


@app.get("/metrics")
def metrics():
    """
    Metrics endpoint - Returns all metrics including GPU
    Primary metrics for scaling: GPU utilization, Active Users, Latency
    """
    cpu_percent = psutil.cpu_percent(interval=0.0)
    mem = psutil.virtual_memory()
    avg_latency = get_avg_latency()
    gpu_metrics = get_gpu_metrics()
    
    response: Dict[str, Any] = {
        # PRIMARY SCALING METRICS (in order of priority)
        "gpu_utilization": gpu_metrics["gpu_utilization"],
        "active_users": max(active_users, 0),
        "avg_latency_ms": avg_latency,
        
        # GPU details
        "gpu_memory_used_mb": gpu_metrics["gpu_memory_used_mb"],
        "gpu_memory_total_mb": gpu_metrics["gpu_memory_total_mb"],
        "gpu_memory_percent": gpu_metrics["gpu_memory_percent"],
        "gpu_temperature": gpu_metrics["gpu_temperature"],
        
        # Secondary metrics for monitoring
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "request_count": request_count,
        "uptime_s": int(time.time() - start_time),
        
        # Configuration info
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE,
        
        # Legacy compatibility (for scaler)
        "latency_ms_p50": {"compute": avg_latency, "matrix": avg_latency}
    }
    
    return JSONResponse(response)


@app.get("/scaling-info")
def scaling_info():
    """Endpoint to provide scaling information"""
    return {
        "current_active_users": max(active_users, 0),
        "avg_latency_ms": get_avg_latency(),
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE,
        "recommended_scaling_factors": {
            "users_per_pod": 10,
            "latency_threshold_ms": 200
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    print("="*80)
    print("🚀 Starting Userscale App")
    print("="*80)
    print(f"   Workload Type: {WORKLOAD_TYPE.upper()}")
    print(f"   CPU Threads: {CPU_THREADS}")
    print(f"   Port: {PORT}")
    print()
    
    # GPU Status
    print("🎮 GPU Configuration:")
    if GPU_AVAILABLE:
        print("   ✅ CuPy available - GPU acceleration ENABLED")
        try:
            device = cp.cuda.Device(0)
            props = cp.cuda.runtime.getDeviceProperties(0)
            gpu_name = props['name'].decode()
            gpu_mem = props['totalGlobalMem'] / (1024**3)
            print(f"   ✅ GPU Device: {gpu_name}")
            print(f"   ✅ GPU Memory: {gpu_mem:.2f} GB")
            print(f"   ✅ Compute Capability: {props['major']}.{props['minor']}")
        except:
            print("   ⚠️  GPU detected but details unavailable")
    else:
        print("   ⚠️  CuPy not available - using CPU fallback")
        print("   💡 Install: pip install cupy-cuda12x")
    
    print()
    print("📊 GPU Metrics:")
    if GPU_METRICS_AVAILABLE:
        print("   ✅ pynvml available - Real GPU metrics ENABLED")
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
            temp = pynvml.nvmlDeviceGetTemperature(GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)
            print(f"   ✅ Current GPU Utilization: {util.gpu}%")
            print(f"   ✅ Current GPU Memory: {mem_info.used / (1024**2):.0f} MB / {mem_info.total / (1024**2):.0f} MB")
            print(f"   ✅ Current GPU Temperature: {temp}°C")
        except:
            print("   ⚠️  pynvml detected but metrics unavailable")
    else:
        print("   ❌ pynvml not available - GPU metrics will return 0")
        print("   💡 Install: pip install nvidia-ml-py3")
    
    print()
    print("🔥 Workload Configuration:")
    if WORKLOAD_TYPE == "matrix":
        if GPU_AVAILABLE:
            print("   ✅ Matrix multiplication will use GPU (CuPy)")
        else:
            print("   ⚠️  Matrix multiplication will use CPU (NumPy)")
    else:
        if GPU_AVAILABLE:
            print("   ✅ Sorting/simulation will use GPU (CuPy)")
        else:
            print("   ⚠️  Sorting/simulation will use CPU (NumPy)")
    
    print("="*80)
    print()
    
    uvicorn.run(
        "app.unified_app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=1,
        loop="asyncio",
        http="httptools",
        access_log=False,
        log_level="warning"
    )
