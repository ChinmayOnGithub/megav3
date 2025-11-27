#!/usr/bin/env python3
"""
Unified FastAPI application supporting GPU-intensive workloads:
1. Array Sorting (GPU-first)
2. Image Convolution (GPU-first)

Workload controlled using WORKLOAD_TYPE environment variable.
Metrics exposed for autoscaling: GPU, latency, concurrent requests.
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
import logging

# GPU runtime detection
try:
    import cupy as cp
    GPU_AVAILABLE = True
except Exception:
    cp = None
    GPU_AVAILABLE = False

GPU_BROKEN = False

# Real GPU metrics via pynvml
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_METRICS_AVAILABLE = True
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
except:
    GPU_METRICS_AVAILABLE = False
    GPU_HANDLE = None

# Config
WORKLOAD_TYPE = os.getenv("WORKLOAD_TYPE", "sorting").lower()
CPU_THREADS = max(1, int(os.getenv("CPU_THREADS", "4")))
PORT = int(os.getenv("PORT", "8000"))

app = FastAPI(
    title=f"Userscale App - {WORKLOAD_TYPE.capitalize()} Workload",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

log = logging.getLogger("userscale-app")

start_time = time.time()
concurrent_requests = 0
latency_samples: list = []
latency_lock = threading.Lock()
request_count = 0

executor = ThreadPoolExecutor(max_workers=CPU_THREADS, thread_name_prefix="compute")


def record_latency(ms: float, limit: int = 200):
    with latency_lock:
        latency_samples.append(ms)
        if len(latency_samples) > limit:
            latency_samples.pop(0)


def get_avg_latency() -> float:
    with latency_lock:
        if not latency_samples:
            return 0.0
        return sum(latency_samples) / len(latency_samples)


def get_gpu_metrics() -> Dict[str, Any]:
    if not GPU_METRICS_AVAILABLE or not GPU_HANDLE:
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0
        }
    try:
        util = pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE)
        mem = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
        temp = pynvml.nvmlDeviceGetTemperature(GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)

        return {
            "gpu_utilization": float(util.gpu),
            "gpu_memory_used_mb": int(mem.used / (1024 * 1024)),
            "gpu_memory_total_mb": int(mem.total / (1024 * 1024)),
            "gpu_memory_percent": round((mem.used / mem.total) * 100, 1),
            "gpu_temperature": int(temp)
        }
    except:
        return {
            "gpu_utilization": 0.0,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 0,
            "gpu_memory_percent": 0.0,
            "gpu_temperature": 0
        }


# ================================
# WORKLOAD 1: ARRAY SORTING
# ================================

def array_sorting_cpu(size: int) -> float:
    """CPU-based array sorting with multiple operations"""
    iterations = 3
    total = 0.0
    
    for _ in range(iterations):
        # Generate large random array
        arr = np.random.rand(size).astype(np.float32)
        
        # Multiple sorting operations
        arr = np.sort(arr)
        arr = arr[::-1]  # Reverse
        arr = np.sort(arr)
        
        # Additional operations
        arr = arr ** 2
        arr = np.sqrt(arr + 1.0)
        arr = np.sin(arr) * np.cos(arr)
        
        total += float(np.sum(arr[:1000]))
    
    return total / iterations


def array_sorting_gpu(size: int) -> float:
    """GPU-based array sorting - optimized for reliable scaling"""
    global GPU_BROKEN

    if not GPU_AVAILABLE or GPU_BROKEN:
        return array_sorting_cpu(size)

    try:
        # Reduced workload for faster response times
        # Size 100-2000 maps to 1M-5M elements
        actual_size = max(size * 2000, 1_000_000)  # 1M to 4M elements
        
        # Fewer iterations for faster completion
        iterations = max(5, min(15, 50_000_000 // actual_size))
        
        total = 0.0

        for _ in range(iterations):
            # Create random array on GPU
            arr = cp.random.rand(actual_size, dtype=cp.float32)
            
            # GPU sorting operations
            arr = cp.sort(arr)  # Ascending
            arr = arr[::-1]     # Reverse
            arr = cp.sort(arr)  # Ascending again
            
            # Reduced GPU operations (5 instead of 10)
            for _ in range(5):
                arr = cp.sin(arr) + cp.cos(arr * 0.5)
                arr = cp.sqrt(cp.abs(arr) + 1.0)
                arr = cp.power(arr, 1.5)
                arr = cp.tanh(arr)
                arr = cp.log(cp.abs(arr) + 1.0)
            
            # Force synchronization
            total += float(cp.sum(arr[:5000]).get())
            
            # Clean up
            del arr
        
        # Final synchronization
        cp.cuda.Stream.null.synchronize()
        return total / iterations

    except Exception as e:
        GPU_BROKEN = True
        if log:
            log.warning("GPU sorting workload failed, falling back to CPU: %s", e)
        return array_sorting_cpu(size)


# ================================
# WORKLOAD 2: IMAGE CONVOLUTION
# ================================

def image_convolution_cpu(size: int) -> float:
    """CPU-based image convolution"""
    iterations = 2
    total = 0.0
    
    # Image dimensions based on size parameter
    img_size = max(512, size * 2)
    
    for _ in range(iterations):
        # Generate random image
        image = np.random.rand(img_size, img_size, 3).astype(np.float32)
        
        # Simple convolution kernels
        kernel_blur = np.ones((5, 5), dtype=np.float32) / 25
        kernel_sharpen = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
        
        # Apply convolutions (simplified)
        for channel in range(3):
            # Blur
            for i in range(2, img_size-2):
                for j in range(2, img_size-2):
                    image[i, j, channel] = np.sum(image[i-2:i+3, j-2:j+3, channel] * kernel_blur)
        
        # Additional operations
        image = np.sin(image) * np.cos(image)
        image = np.sqrt(np.abs(image) + 1.0)
        
        total += float(np.sum(image[:100, :100, :]))
    
    return total / iterations


def image_convolution_gpu(size: int) -> float:
    """GPU-based image convolution - optimized for reliable scaling"""
    global GPU_BROKEN

    if not GPU_AVAILABLE or GPU_BROKEN:
        return image_convolution_cpu(size)

    try:
        # Reduced image size for faster processing
        # Size 100-2000 maps to 512-2048 pixels
        img_size = max(512, size * 2)  # 512 to 4096 pixels
        
        # Fewer iterations
        iterations = max(3, min(10, 10_000_000 // (img_size * img_size)))
        
        total = 0.0

        for _ in range(iterations):
            # Create random image on GPU (RGB)
            image = cp.random.rand(img_size, img_size, 3, dtype=cp.float32)
            
            # Reduced convolution operations (4 instead of 8)
            for _ in range(4):
                # Apply to each channel
                for c in range(3):
                    channel = image[:, :, c:c+1]
                    # Simplified operations
                    channel = cp.sin(channel) + cp.cos(channel * 0.5)
                    channel = cp.sqrt(cp.abs(channel) + 1.0)
                    channel = cp.tanh(channel)
                    image[:, :, c:c+1] = channel
                
                # Edge detection
                image = cp.abs(cp.diff(image, axis=0, prepend=0))
                image = cp.abs(cp.diff(image, axis=1, prepend=0))
                
                # Normalization
                image = (image - cp.mean(image)) / (cp.std(image) + 1e-8)
                image = cp.clip(image, 0, 1)
            
            # Reduced additional operations (3 instead of 5)
            for _ in range(3):
                image = cp.power(image, 1.5)
                image = cp.log(cp.abs(image) + 1.0)
                image = cp.exp(-cp.abs(image) * 0.1)
            
            # Force synchronization
            total += float(cp.sum(image[:100, :100, :]).get())
            
            # Clean up
            del image
        
        # Final synchronization
        cp.cuda.Stream.null.synchronize()
        return total / iterations

    except Exception as e:
        GPU_BROKEN = True
        if log:
            log.warning("GPU convolution workload failed, falling back to CPU: %s", e)
        return image_convolution_cpu(size)


# ================================
# API
# ================================

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
    size: int = Query(500, ge=100, le=2000)
):
    global concurrent_requests, request_count

    concurrent_requests += 1
    request_count += 1
    t0 = time.time()

    try:
        loop = asyncio.get_event_loop()

        if WORKLOAD_TYPE == "sorting":
            # Array Sorting Workload
            if GPU_AVAILABLE:
                result = await loop.run_in_executor(executor, array_sorting_gpu, size)
                workload_used = "array_sorting_gpu"
            else:
                result = await loop.run_in_executor(executor, array_sorting_cpu, size)
                workload_used = "array_sorting_cpu"

            return {
                "workload": workload_used,
                "size": size,
                "result": result,
                "gpu_used": GPU_AVAILABLE
            }
        
        elif WORKLOAD_TYPE == "convolution":
            # Image Convolution Workload
            if GPU_AVAILABLE:
                result = await loop.run_in_executor(executor, image_convolution_gpu, size)
                workload_used = "image_convolution_gpu"
            else:
                result = await loop.run_in_executor(executor, image_convolution_cpu, size)
                workload_used = "image_convolution_cpu"

            return {
                "workload": workload_used,
                "size": size,
                "result": result,
                "gpu_used": GPU_AVAILABLE
            }
        
        else:
            return {
                "error": f"Unknown workload type: {WORKLOAD_TYPE}",
                "available": ["sorting", "convolution"]
            }

    finally:
        dt = (time.time() - t0) * 1000
        record_latency(dt)
        concurrent_requests -= 1


@app.get("/metrics")
def metrics():
    cpu_percent = psutil.cpu_percent(interval=0.0)
    mem = psutil.virtual_memory()
    avg_latency = get_avg_latency()
    gpu = get_gpu_metrics()

    return JSONResponse({
        "gpu_utilization": gpu["gpu_utilization"],
        "avg_latency_ms": avg_latency,
        "gpu_memory_used_mb": gpu["gpu_memory_used_mb"],
        "gpu_memory_total_mb": gpu["gpu_memory_total_mb"],
        "gpu_memory_percent": gpu["gpu_memory_percent"],
        "gpu_temperature": gpu["gpu_temperature"],
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "request_count": request_count,
        "uptime_s": int(time.time() - start_time),
        "workload_type": WORKLOAD_TYPE,
        "gpu_available": GPU_AVAILABLE,
        "concurrent_requests": concurrent_requests
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.unified_app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=1,
        access_log=False,
        log_level="warning"
    )
