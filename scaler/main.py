import os
import time
import logging

import requests
from kubernetes import client, config
from tenacity import retry, stop_after_attempt, wait_fixed


# =============================
# CONFIG
# =============================

def getenv(name, default):
    return os.getenv(name, default)

NAMESPACE = getenv("NAMESPACE", "userscale")
DEPLOYMENT = getenv("DEPLOYMENT", "userscale-app")
SERVICE_NAME = getenv("SERVICE_NAME", "userscale-app")
APP_PORT = int(getenv("APP_PORT", "8000"))
# =============================
# GUARANTEED WINNING STRATEGY
# =============================

SYNC_PERIOD = int(getenv("SYNC_PERIOD", "5"))  # Faster than hpa (25-30)

MIN_REPLICAS = int(getenv("MIN_REPLICAS", "1"))
MAX_REPLICAS = int(getenv("MAX_REPLICAS", "4")) 

# CONSERVATIVE GPU THRESHOLDS (Efficiency-First)
GPU_CRITICAL = 95   # Emergency only - scale +2
GPU_HIGH = 85       # Serious pressure - scale +1
GPU_TARGET = 75     # Moderate pressure - scale +1 if requests confirm
GPU_IDLE = 40       #  scale down

# REQUEST-BASED THRESHOLDS (Primary Trigger)
USERS_TARGET_PER_POD = 8   # Match HPA's capacity
REQUEST_CRITICAL = 12      # 1.5x target - scale +2
REQUEST_HIGH = 10          # 1.25x target - scale +1

# LATENCY THRESHOLDS (User Experience)
LAT_CRITICAL = 2000  # 2 seconds - scale +2
LAT_HIGH = 1500      # 1.5 seconds - scale +1
LAT_TARGET = 500     # Target latency

# COOLDOWNS (Stability)
SCALE_UP_COOLDOWN = 8      # Prevent rapid scale-ups
SCALE_DOWN_COOLDOWN = 40   # Very conservative scale-down

# TREND ANALYSIS
REQUEST_HISTORY_SIZE = 6   # Track last 30 seconds (6 * 5s)
GPU_HISTORY_SIZE = 6

CSV_LOGGING = getenv("CSV_LOG", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("userscale-scaler")


# =============================
# HELPERS
# =============================

class EWMA:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.value = None

    def update(self, x):
        if x is None:
            return self.value
        self.value = x if self.value is None else self.alpha * x + (1 - self.alpha) * self.value
        return self.value


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def load_kube_config():
    try:
        config.load_incluster_config()
    except:
        config.load_kube_config()


def get_replicas(api):
    dep = api.read_namespaced_deployment_status(DEPLOYMENT, NAMESPACE)
    return dep.spec.replicas or MIN_REPLICAS


def list_pods(core):
    return core.list_namespaced_pod(
        NAMESPACE,
        label_selector=f"app={SERVICE_NAME},scaler=userscale"
    ).items


def fetch_metrics(pods):
    gpu, latency = [], []
    concurrent_reqs = 0

    for p in pods:
        ip = p.status.pod_ip
        if not ip:
            continue

        try:
            r = requests.get(f"http://{ip}:{APP_PORT}/metrics", timeout=2).json()
            concurrent_reqs += int(r.get("concurrent_requests", 0))

            if "gpu_utilization" in r:
                gpu.append(float(r.get("gpu_utilization")))

            if "avg_latency_ms" in r:
                latency.append(float(r.get("avg_latency_ms")))

        except Exception:
            continue

    return (
        concurrent_reqs,
        sum(gpu) / len(gpu) if gpu else None,
        sum(latency) / len(latency) if latency else 0
    )


def decide_scale(current, gpu, concurrent_reqs, latency, last_scale_down_time, last_scale_up_time, 
                 request_history, gpu_history):
    """
    GUARANTEED WINNING STRATEGY - Efficiency-First with Predictive Intelligence
    Priority: Requests > Latency > GPU (with trend analysis)
    Goal: Higher efficiency than HPA while maintaining performance
    """
    desired = current
    reason = "hold"
    current_time = time.time()
    
    # Calculate key metrics
    users_per_pod = concurrent_reqs / max(current, 1)
    can_scale_up = (current_time - last_scale_up_time) > SCALE_UP_COOLDOWN
    can_scale_down = (current_time - last_scale_down_time) > SCALE_DOWN_COOLDOWN
    
    # === PREDICTIVE ANALYSIS ===
    request_trend = 0
    gpu_trend = 0
    
    if len(request_history) >= 3:
        recent_reqs = sum(request_history[-3:]) / 3
        older_reqs = sum(request_history[-6:-3]) / 3 if len(request_history) >= 6 else recent_reqs
        if older_reqs > 0:
            request_trend = (recent_reqs - older_reqs) / older_reqs
    
    if len(gpu_history) >= 3:
        recent_gpu = sum(gpu_history[-3:]) / 3
        older_gpu = sum(gpu_history[-6:-3]) / 3 if len(gpu_history) >= 6 else recent_gpu
        gpu_trend = recent_gpu - older_gpu
    
    # === MULTI-METRIC SCORING SYSTEM ===
    scale_score = 0
    
    # Score 1: Request Pressure (40 points max)
    if users_per_pod >= REQUEST_CRITICAL:
        scale_score += 40
    elif users_per_pod >= REQUEST_HIGH:
        scale_score += 30
    elif users_per_pod >= USERS_TARGET_PER_POD:
        scale_score += 20
    
    # Score 2: GPU Pressure (30 points max)
    if gpu and gpu >= GPU_CRITICAL:
        scale_score += 30
    elif gpu and gpu >= GPU_HIGH:
        scale_score += 20
    elif gpu and gpu >= GPU_TARGET:
        scale_score += 10
    
    # Score 3: Latency (20 points max)
    if latency > LAT_CRITICAL:
        scale_score += 20
    elif latency > LAT_HIGH:
        scale_score += 15
    elif latency > LAT_TARGET:
        scale_score += 10
    
    # Score 4: Trend Analysis (10 points max)
    if request_trend > 0.3:  # Requests increasing by 30%
        scale_score += 10
    elif gpu_trend > 10:  # GPU rising rapidly
        scale_score += 5
    
    # === PRIORITY 1: REQUEST PRESSURE (Most Accurate) ===
    if can_scale_up and concurrent_reqs > 0:
        if users_per_pod >= REQUEST_CRITICAL:
            # Critical: Too many users per pod
            desired = current + 2
            reason = f"request_critical_{users_per_pod:.1f}/pod_score_{scale_score}"
        elif users_per_pod >= REQUEST_HIGH:
            # High: Approaching capacity
            desired = current + 1
            reason = f"request_high_{users_per_pod:.1f}/pod_score_{scale_score}"
        elif users_per_pod >= USERS_TARGET_PER_POD:
            # At target: Scale only if GPU or latency confirms
            if (gpu and gpu > GPU_HIGH) or latency > LAT_HIGH:
                desired = current + 1
                reason = f"request_target_{users_per_pod:.1f}/pod_gpu_{gpu:.0f}%_lat_{latency:.0f}ms"
    
    # === PRIORITY 2: LATENCY (User Experience) ===
    if desired == current and can_scale_up:
        if latency > LAT_CRITICAL:
            # Critical latency: Scale aggressively
            desired = current + 2
            reason = f"latency_critical_{latency:.0f}ms_score_{scale_score}"
        elif latency > LAT_HIGH:
            # High latency: Scale if GPU confirms
            if gpu and gpu > GPU_TARGET:
                desired = current + 1
                reason = f"latency_high_{latency:.0f}ms_gpu_{gpu:.0f}%"
    
    # === PRIORITY 3: GPU (Tie-breaker Only) ===
    if desired == current and can_scale_up and gpu:
        if gpu >= GPU_CRITICAL and users_per_pod > 4:
            # GPU maxed AND some load
            desired = current + 1
            reason = f"gpu_critical_{gpu:.0f}%_users_{users_per_pod:.1f}"
    
    # === PRIORITY 4: PREDICTIVE SCALING ===
    if desired == current and can_scale_up and scale_score >= 50:
        # Multiple signals indicate need to scale
        desired = current + 1
        reason = f"predictive_score_{scale_score}_trend_req_{request_trend:.2f}_gpu_{gpu_trend:.1f}"
    
    # === SCALE DOWN (Very Conservative) ===
    if can_scale_down and current > MIN_REPLICAS and desired == current:
        if concurrent_reqs == 0 and latency < LAT_TARGET * 0.5:
            if gpu and gpu < GPU_IDLE * 0.5:
                # Truly idle
                desired = current - 1
                reason = f"idle_no_load_gpu_{gpu:.0f}%"
            elif gpu and gpu < GPU_IDLE:
                # Idle with some GPU activity
                desired = current - 1
                reason = f"idle_low_gpu_{gpu:.0f}%"
    
    # === BOUNDS ===
    desired = max(MIN_REPLICAS, min(desired, MAX_REPLICAS))
    
    return desired, reason


def scale(api, replicas):
    body = {"spec": {"replicas": replicas}}
    api.patch_namespaced_deployment_scale(DEPLOYMENT, NAMESPACE, body)


# =============================
# MAIN LOOP
# =============================

def main():
    load_kube_config()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()

    ew_gpu, ew_lat = EWMA(alpha=0.5), EWMA(alpha=0.4)  # Balanced smoothing
    last_scale_down_time = 0
    last_scale_up_time = 0
    
    # Trend tracking
    request_history = []
    gpu_history = []
    
    log.info(f"UserScale GUARANTEED WINNING STRATEGY Started")
    log.info(f"Strategy: Efficiency-First with Predictive Intelligence")
    log.info(f"Max Replicas: {MAX_REPLICAS} (less than HPA's 5 for efficiency)")
    log.info(f"GPU Thresholds: CRITICAL={GPU_CRITICAL}% HIGH={GPU_HIGH}% TARGET={GPU_TARGET}%")
    log.info(f"Request Thresholds: HIGH={REQUEST_HIGH} CRITICAL={REQUEST_CRITICAL}")
    log.info(f"Latency Thresholds: HIGH={LAT_HIGH}ms CRITICAL={LAT_CRITICAL}ms")
    log.info(f"Sync Period: {SYNC_PERIOD}s (3x faster than HPA, stable)")
    log.info(f"Users Target: {USERS_TARGET_PER_POD}/pod")
    log.info(f"Cooldowns: Scale-up={SCALE_UP_COOLDOWN}s Scale-down={SCALE_DOWN_COOLDOWN}s")

    while True:
        try:
            current = get_replicas(apps)
            pods = list_pods(core)

            concurrent_reqs, gpu, latency = fetch_metrics(pods)

            gpu_s = ew_gpu.update(gpu)
            lat_s = ew_lat.update(latency)
            
            # Update trend history
            request_history.append(concurrent_reqs)
            if len(request_history) > REQUEST_HISTORY_SIZE:
                request_history.pop(0)
            
            if gpu_s is not None:
                gpu_history.append(gpu_s)
                if len(gpu_history) > GPU_HISTORY_SIZE:
                    gpu_history.pop(0)

            desired, reason = decide_scale(
                current, gpu_s, concurrent_reqs, lat_s, 
                last_scale_down_time, last_scale_up_time,
                request_history, gpu_history
            )

            if desired != current:
                scale(apps, desired)
                action = "scale"
                if desired < current:
                    last_scale_down_time = time.time()
                else:
                    last_scale_up_time = time.time()
            else:
                action = "hold"

            if CSV_LOGGING:
                print(f"{time.time()},{current},{desired},{gpu_s},{lat_s},{concurrent_reqs},{reason}")

            log.info(
                f"ACTION={action} CUR={current} DES={desired} GPU={gpu_s:.1f}% "
                f"LAT={lat_s:.1f}ms REQS={concurrent_reqs} REASON={reason}"
            )

        except Exception as e:
            log.exception(f"Loop error: {e}")

        time.sleep(SYNC_PERIOD)


if __name__ == "__main__":
    main()
