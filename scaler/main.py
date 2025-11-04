import os
import math
import time
import logging
from typing import Optional

import httpx
import requests
from kubernetes import client, config
from tenacity import retry, stop_after_attempt, wait_fixed


def get_env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None else default


NAMESPACE = get_env("NAMESPACE", "userscale")
DEPLOYMENT = get_env("DEPLOYMENT", "userscale-app")
SERVICE_NAME = get_env("SERVICE_NAME", "userscale-app")
APP_PORT = int(get_env("APP_PORT", "8000"))
SYNC_PERIOD = int(get_env("SYNC_PERIOD", "5"))  # Very fast monitoring

# ULTRA-AGGRESSIVE configuration - prioritize latency over everything
ALPHA = float(get_env("ALPHA", "0.3"))  # Very responsive - react immediately
MIN_REPLICAS = int(get_env("MIN_REPLICAS", "3"))  # Start with 3 for strong baseline
MAX_REPLICAS = int(get_env("MAX_REPLICAS", "20"))
USERS_TARGET_PER_POD = int(get_env("USERS_TARGET_PER_POD", "5"))  # Very low = scale up very early
CPU_TARGET = float(get_env("CPU_TARGET", "30"))  # Very low = scale up very early
GPU_TARGET = float(get_env("GPU_TARGET", "40"))
LATENCY_TARGET_MS = float(get_env("LATENCY_TARGET_MS", "100"))  # Very strict target
SCALE_UP_STEP = int(get_env("SCALE_UP_STEP", "5"))  # Very aggressive scale-up
SCALE_DOWN_STEP = int(get_env("SCALE_DOWN_STEP", "1"))  # Conservative scale-down
COOLDOWN_PERIOD = int(get_env("COOLDOWN_PERIOD", "10"))  # Very short cooldown
COOLDOWN_SCALE_UP = int(get_env("COOLDOWN_SCALE_UP", "2"))  # Almost no cooldown for scale-up
COOLDOWN_SCALE_DOWN = int(get_env("COOLDOWN_SCALE_DOWN", "45"))  # Much longer for scale-down
GPU_PROM_BASE = os.getenv("GPU_PROM_BASE")  # e.g., http://prometheus:9090


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("userscale-scaler")


class EWMASignal:
    def __init__(self, alpha: float, initial_value: Optional[float] = None):
        self.alpha = alpha
        self.value = initial_value

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value


class ScalingController:
    """Optimized scaling controller with separate cooldowns for up/down"""
    def __init__(self):
        self.last_scale_up_time = 0
        self.last_scale_down_time = 0
        self.scale_direction = 0  # 0: no change, 1: scale up, -1: scale down
        self.consecutive_scales = 0
        self.latency_spike_count = 0
    
    def can_scale(self, direction: int, latency_critical: bool = False) -> bool:
        """Check if scaling is allowed with optimized cooldowns"""
        now = time.time()
        
        # Scale up: shorter cooldown, especially if latency is critical
        if direction > 0:
            cooldown = COOLDOWN_SCALE_UP if not latency_critical else 0
            if now - self.last_scale_up_time < cooldown:
                return False
        
        # Scale down: longer cooldown to avoid thrashing
        elif direction < 0:
            if now - self.last_scale_down_time < COOLDOWN_SCALE_DOWN:
                return False
        
        # If direction changed, reset consecutive count
        if direction != self.scale_direction:
            self.consecutive_scales = 0
            self.scale_direction = direction
        
        # Allow more consecutive scale-ups than scale-downs
        if direction > 0:
            return self.consecutive_scales < 5  # Allow more scale-ups
        else:
            return self.consecutive_scales < 2  # Limit scale-downs
    
    def record_scale(self, direction: int):
        """Record a scaling operation"""
        now = time.time()
        if direction > 0:
            self.last_scale_up_time = now
        elif direction < 0:
            self.last_scale_down_time = now
        
        self.scale_direction = direction
        self.consecutive_scales += 1
    
    def check_latency_critical(self, latency: float, target: float) -> bool:
        """Determine if latency situation is critical"""
        if latency > target * 1.5:  # 1.5x over target (more sensitive)
            self.latency_spike_count += 1
            return True
        else:
            self.latency_spike_count = max(0, self.latency_spike_count - 1)
            return False


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def load_kube_config():
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")


def get_current_replicas(apps: client.AppsV1Api, name: str, namespace: str) -> int:
    dep = apps.read_namespaced_deployment_status(name, namespace)
    return dep.spec.replicas or 0


def get_pod_list(core: client.CoreV1Api, namespace: str, selector: str):
    return core.list_namespaced_pod(namespace, label_selector=selector).items


def get_users_and_cpu(core: client.CoreV1Api, pods, port: int):
    total_active_users = 0
    pod_cpu = []
    pod_gpu = []
    for p in pods:
        pod_ip = p.status.pod_ip
        if not pod_ip:
            continue
        try:
            with httpx.Client(timeout=2.0) as s:
                r = s.get(f"http://{pod_ip}:{port}/metrics")
                if r.status_code == 200:
                    m = r.json()
                    total_active_users += int(m.get("active_users", 0))
                    pod_cpu.append(float(m.get("cpu_percent", 0.0)))
                    # Get GPU utilization from metrics endpoint
                    gpu_util = m.get("gpu_utilization", None)
                    if gpu_util is not None:
                        pod_gpu.append(float(gpu_util))
        except Exception:
            continue
    avg_cpu = sum(pod_cpu) / len(pod_cpu) if pod_cpu else 0.0
    avg_gpu = sum(pod_gpu) / len(pod_gpu) if pod_gpu else None
    return total_active_users, avg_cpu, avg_gpu


def get_avg_latency(core, pods, app_port):
    """Get average latency from all pods - PRIMARY SCALING METRIC"""
    total_latency = 0
    pod_count = 0
    
    for pod in pods:
        try:
            pod_ip = pod.status.pod_ip
            if not pod_ip:
                continue
                
            response = requests.get(
                f"http://{pod_ip}:{app_port}/metrics",
                timeout=5.0
            )
            metrics = response.json()
            
            # Get average latency (unified metric for both workloads)
            avg_latency = metrics.get('avg_latency_ms', 0)
            if avg_latency > 0:
                total_latency += avg_latency
                pod_count += 1
                
        except Exception as e:
            logger.warning(f"Failed to get latency from pod {pod.metadata.name}: {e}")
    
    return total_latency / max(pod_count, 1)


def query_gpu_util() -> Optional[float]:
    if not GPU_PROM_BASE:
        return None
    # Expect a Prometheus metric like: DCGM_FI_DEV_GPU_UTIL
    q = "avg(DCGM_FI_DEV_GPU_UTIL)"
    try:
        with httpx.Client(timeout=3.0) as s:
            r = s.get(f"{GPU_PROM_BASE}/api/v1/query", params={"query": q})
            data = r.json()
            result = data.get("data", {}).get("result", [])
            if result:
                v = float(result[0]["value"][1])
                return v
    except Exception:
        return None
    return None


def compute_desired_by_users(total_users: int, replicas: int) -> int:
    per_pod = USERS_TARGET_PER_POD
    needed = math.ceil(total_users / max(per_pod, 1))
    return max(needed, MIN_REPLICAS)


def compute_desired_by_latency(avg_latency_ms: float, target_latency_ms: float, replicas: int) -> int:
    """Compute desired replicas based on latency - ULTRA AGGRESSIVE"""
    if target_latency_ms <= 0 or avg_latency_ms <= 0:
        return replicas
    
    ratio = avg_latency_ms / target_latency_ms
    
    # ULTRA aggressive scaling for high latency - go to max immediately if very high
    if ratio > 10.0:  # 10x over target
        return MAX_REPLICAS  # Go to max immediately!
    elif ratio > 5.0:  # 5x over target
        return min(replicas * 4, MAX_REPLICAS)  # Quadruple replicas
    elif ratio > 3.0:  # 3x over target
        return min(replicas * 3, MAX_REPLICAS)  # Triple replicas
    elif ratio > 2.0:  # 2x over target
        return min(replicas * 2, MAX_REPLICAS)  # Double replicas
    elif ratio > 1.5:  # 1.5x over target
        return min(replicas + 5, MAX_REPLICAS)  # Add 5
    elif ratio > 1.2:  # 1.2x over target
        return min(replicas + 3, MAX_REPLICAS)  # Add 3
    elif ratio > 1.0:  # Slightly over target
        return min(replicas + 2, MAX_REPLICAS)  # Add 2
    elif ratio < 0.3:  # Well under target
        return max(replicas - 1, MIN_REPLICAS)  # Remove 1
    
    return replicas


def compute_desired_by_util(avg_util: float, target: float, replicas: int) -> int:
    """Compute desired replicas based on CPU/GPU utilization"""
    if target <= 0:
        return replicas
    ratio = avg_util / target
    
    # Aggressive scaling up for high utilization
    if ratio > 1.5:
        return min(replicas * 2, MAX_REPLICAS)
    elif ratio > 1.2:
        return min(replicas + 2, MAX_REPLICAS)
    elif ratio > 1.0:
        return min(replicas + 1, MAX_REPLICAS)
    elif ratio < 0.3:  # Very low utilization
        return max(replicas - 1, MIN_REPLICAS)
    elif ratio < 0.5:  # Low utilization
        return max(replicas - 1, MIN_REPLICAS)
    
    return replicas


def compute_desired_by_gpu(gpu_util: float, replicas: int) -> int:
    """
    Compute desired replicas based on GPU utilization - PRIMARY SCALING METRIC
    GPU is the most expensive resource, so we scale aggressively based on it
    OPTIMIZED THRESHOLDS for real GPU hardware to trigger meaningful scaling
    """
    if gpu_util is None or gpu_util < 0:
        return replicas
    
    # AGGRESSIVE GPU-based scaling with realistic thresholds
    # These thresholds are tuned for actual GPU workloads
    if gpu_util > 85:  # Critical GPU load - immediate action
        return min(replicas * 3, MAX_REPLICAS)  # Triple replicas immediately
    elif gpu_util > 75:  # Very high GPU load
        return min(replicas * 2, MAX_REPLICAS)  # Double replicas
    elif gpu_util > 65:  # High GPU load
        return min(replicas + 4, MAX_REPLICAS)  # Add 4 replicas
    elif gpu_util > 55:  # Elevated GPU load
        return min(replicas + 3, MAX_REPLICAS)  # Add 3 replicas
    elif gpu_util > 45:  # Moderate-high GPU load
        return min(replicas + 2, MAX_REPLICAS)  # Add 2 replicas
    elif gpu_util > 35:  # Moderate GPU load
        return min(replicas + 1, MAX_REPLICAS)  # Add 1 replica
    elif gpu_util < 10:  # Very low GPU usage
        return max(replicas - 2, MIN_REPLICAS)  # Remove 2 replicas
    elif gpu_util < 20:  # Low GPU usage
        return max(replicas - 1, MIN_REPLICAS)  # Remove 1 replica
    
    return replicas


def clamp_step(current: int, desired: int, latency_critical: bool = False) -> int:
    """Clamp scaling step with option for emergency scaling"""
    if desired > current:
        # If latency is critical, go directly to desired (no step limit)
        if latency_critical:
            return min(desired, MAX_REPLICAS)
        # Otherwise use aggressive step
        step = SCALE_UP_STEP
        return min(current + step, desired, MAX_REPLICAS)
    if desired < current:
        return max(current - SCALE_DOWN_STEP, desired, MIN_REPLICAS)
    return current


def main():
    load_kube_config()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()

    user_ewma = EWMASignal(ALPHA)
    cpu_ewma = EWMASignal(ALPHA)
    gpu_ewma = EWMASignal(ALPHA)
    latency_ewma = EWMASignal(ALPHA)
    
    # Enhanced scaling controller
    scaling_controller = ScalingController()

    # Expect app pods labeled app=userscale-app
    selector = f"app={SERVICE_NAME}"

    while True:
        try:
            current = get_current_replicas(apps, DEPLOYMENT, NAMESPACE)
            pods = get_pod_list(core, NAMESPACE, selector)
            total_users, avg_cpu, avg_gpu = get_users_and_cpu(core, pods, APP_PORT)
            avg_latency = get_avg_latency(core, pods, APP_PORT)

            u_smooth = user_ewma.update(total_users)
            c_smooth = cpu_ewma.update(avg_cpu)
            l_smooth = latency_ewma.update(avg_latency)
            g_smooth = gpu_ewma.update(avg_gpu) if avg_gpu is not None else None

            # Compute desired replicas for each metric
            desired_u = compute_desired_by_users(int(u_smooth), current)
            desired_c = compute_desired_by_util(c_smooth, CPU_TARGET, current)
            desired_l = compute_desired_by_latency(l_smooth, LATENCY_TARGET_MS, current)
            desired_g = compute_desired_by_gpu(g_smooth, current) if g_smooth is not None else current
            
            # Log individual metric recommendations
            gpu_str = f"GPU: {g_smooth:.1f}% (want {desired_g} replicas)" if g_smooth is not None else "GPU: N/A"
            logger.info("📊 METRIC ANALYSIS | %s | Users: %d (want %d replicas) | CPU: %.1f%% (want %d replicas) | Latency: %.1fms (want %d replicas)",
                       gpu_str, int(u_smooth), desired_u, c_smooth, desired_c, l_smooth, desired_l)
            
            # GPU IS PRIMARY - it's the most expensive resource
            # Priority: GPU > Latency > Users > CPU
            desired = current
            scaling_reason = "no_change"
            
            if g_smooth is not None and desired_g != current:
                desired = desired_g
                scaling_reason = "gpu"
                logger.info("🎯 Using GPU metric (primary scaling factor)")
            elif desired_l > desired:
                desired = desired_l
                scaling_reason = "latency"
                logger.info("🔄 Using LATENCY metric")
            elif desired_u > desired:
                desired = desired_u
                scaling_reason = "users"
                logger.info("🔄 Using USERS metric")
            elif desired_c > desired:
                desired = desired_c
                scaling_reason = "cpu"
                logger.info("🔄 Using CPU metric")
            
            desired = max(MIN_REPLICAS, min(desired, MAX_REPLICAS))
            
            # Check if latency is critical
            latency_critical = scaling_controller.check_latency_critical(l_smooth, LATENCY_TARGET_MS)
            
            # Determine scaling direction
            scale_direction = 0
            if desired > current:
                scale_direction = 1
            elif desired < current:
                scale_direction = -1
            
            # Apply intelligent scaling with cooldown
            if scale_direction != 0 and scaling_controller.can_scale(scale_direction, latency_critical):
                bounded = clamp_step(current, desired, latency_critical)
                
                if bounded != current:
                    body = {"spec": {"replicas": bounded}}
                    apps.patch_namespaced_deployment_scale(DEPLOYMENT, NAMESPACE, body)
                    scaling_controller.record_scale(scale_direction)
                    
                    # Determine scaling direction emoji
                    direction_emoji = "📈" if bounded > current else "📉"
                    gpu_status = f"GPU: {g_smooth:.1f}%" if g_smooth is not None else "GPU: N/A"
                    
                    logger.info("%s SCALED %s → %s (reason: %s) | %s | Users: %d | CPU: %.1f%% | Latency: %.1fms", 
                               direction_emoji, current, bounded, scaling_reason.upper(),
                               gpu_status, int(u_smooth), c_smooth, l_smooth)
                else:
                    gpu_status = f"GPU: {g_smooth:.1f}%" if g_smooth is not None else "GPU: N/A"
                    logger.info("⚠️  Scale blocked by step limits | Replicas: %s (want %s) | %s | Users: %d | CPU: %.1f%%", 
                               current, desired, gpu_status, int(u_smooth), c_smooth)
            else:
                if scale_direction != 0:
                    gpu_status = f"GPU: {g_smooth:.1f}%" if g_smooth is not None else "GPU: N/A"
                    logger.info("⏳ Scale blocked by cooldown | Replicas: %s (want %s) | %s | Users: %d | CPU: %.1f%%", 
                               current, desired, gpu_status, int(u_smooth), c_smooth)
                else:
                    gpu_status = f"GPU: {g_smooth:.1f}%" if g_smooth is not None else "GPU: N/A"
                    logger.info("✅ No scale needed | Replicas: %s | %s | Users: %d | CPU: %.1f%% | Latency: %.1fms", 
                               current, gpu_status, int(u_smooth), c_smooth, l_smooth)
                               
        except Exception as e:
            logger.exception("Scaler loop error: %s", e)

        time.sleep(SYNC_PERIOD)


if __name__ == "__main__":
    main()