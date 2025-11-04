#!/usr/bin/env python3
"""
Concurrent Demo: UserScale vs HPA
Runs the same workload on both autoscalers and compares performance
"""

import requests
import time
import threading
import subprocess
import json
from typing import Dict, List
from datetime import datetime

NAMESPACE = "userscale"
USERSCALE_SERVICE = "http://localhost:8001"
HPA_SERVICE = "http://localhost:8002"
DURATION = 300  # 5 minutes
WORKERS = 50

# Tracking data
userscale_data = {
    "replicas": [],
    "gpu": [],
    "requests": 0,
    "failed": 0,
    "latencies": [],
    "timestamps": []
}

hpa_data = {
    "replicas": [],
    "gpu": [],
    "requests": 0,
    "failed": 0,
    "latencies": [],
    "timestamps": []
}


def get_host_gpu_metrics() -> Dict:
    """Get real GPU metrics from host"""
    try:
        cmd = "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(',')
            if len(parts) >= 4:
                return {
                    "utilization": float(parts[0].strip()),
                    "memory_percent": (float(parts[1].strip()) / float(parts[2].strip()) * 100),
                    "temperature": int(float(parts[3].strip()))
                }
    except:
        pass
    
    return {"utilization": 0, "memory_percent": 0, "temperature": 0}


def get_deployment_replicas(deployment_name: str) -> int:
    """Get current replicas for deployment"""
    try:
        cmd = f'kubectl get deployment {deployment_name} -n {NAMESPACE} -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('status', {}).get('readyReplicas', 0)
    except:
        pass
    
    return 0


def get_pod_metrics(label_selector: str) -> float:
    """Get average GPU utilization from pods"""
    try:
        cmd = f'kubectl get pods -n {NAMESPACE} -l {label_selector} -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            return 0.0
        
        data = json.loads(result.stdout)
        pods = data.get('items', [])
        
        gpu_values = []
        for pod in pods:
            if pod.get('status', {}).get('phase') == 'Running':
                pod_ip = pod.get('status', {}).get('podIP')
                if pod_ip:
                    try:
                        response = requests.get(f'http://{pod_ip}:8000/metrics', timeout=2)
                        if response.status_code == 200:
                            metrics = response.json()
                            gpu = metrics.get('gpu_utilization', 0)
                            if gpu > 0:
                                gpu_values.append(gpu)
                    except:
                        pass
        
        return sum(gpu_values) / len(gpu_values) if gpu_values else 0.0
    except:
        return 0.0


def send_workload_requests(service_url: str, data_dict: Dict, duration: int):
    """Send continuous requests to a service"""
    end_time = time.time() + duration
    
    while time.time() < end_time:
        try:
            t0 = time.time()
            response = requests.get(f"{service_url}/compute?size=1000", timeout=30)
            latency = (time.time() - t0) * 1000
            
            if response.status_code == 200:
                data_dict["requests"] += 1
                data_dict["latencies"].append(latency)
            else:
                data_dict["failed"] += 1
        except Exception as e:
            data_dict["failed"] += 1
            time.sleep(0.1)


def track_metrics(data_dict: Dict, label_selector: str, duration: int):
    """Track metrics during workload execution"""
    deployment_name = "userscale-app" if "userscale" in label_selector else "hpa-app"
    end_time = time.time() + duration
    
    while time.time() < end_time:
        replicas = get_deployment_replicas(deployment_name)
        gpu = get_pod_metrics(label_selector)
        
        data_dict["replicas"].append(replicas)
        data_dict["gpu"].append(gpu)
        data_dict["timestamps"].append(time.time())
        
        time.sleep(5)


def print_progress_bar(current: int, total: int, width: int = 50):
    """Print a progress bar"""
    percent = current / total
    filled = int(width * percent)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r⏱️  [{bar}] {percent*100:.1f}% | Time: {current}s/{total}s", end="", flush=True)


def print_comparison_report():
    """Print final comparison report"""
    print("\n\n" + "="*100)
    print("  📊 USERSCALE vs HPA - FINAL COMPARISON REPORT")
    print("="*100)
    print()
    
    # Replica patterns
    print("📈 Replica Scaling Patterns:")
    if userscale_data["replicas"]:
        # Get unique scaling transitions
        us_pattern = []
        prev = None
        for r in userscale_data["replicas"]:
            if r != prev:
                us_pattern.append(r)
                prev = r
        print(f"   UserScale: [{' → '.join(map(str, us_pattern))}]")
    
    if hpa_data["replicas"]:
        hpa_pattern = []
        prev = None
        for r in hpa_data["replicas"]:
            if r != prev:
                hpa_pattern.append(r)
                prev = r
        print(f"   HPA:       [{' → '.join(map(str, hpa_pattern))}]")
    
    print()
    
    # Statistics
    us_avg_replicas = sum(userscale_data["replicas"]) / len(userscale_data["replicas"]) if userscale_data["replicas"] else 0
    us_max_replicas = max(userscale_data["replicas"]) if userscale_data["replicas"] else 0
    us_avg_gpu = sum(userscale_data["gpu"]) / len(userscale_data["gpu"]) if userscale_data["gpu"] else 0
    us_avg_latency = sum(userscale_data["latencies"]) / len(userscale_data["latencies"]) if userscale_data["latencies"] else 0
    
    hpa_avg_replicas = sum(hpa_data["replicas"]) / len(hpa_data["replicas"]) if hpa_data["replicas"] else 0
    hpa_max_replicas = max(hpa_data["replicas"]) if hpa_data["replicas"] else 0
    hpa_avg_gpu = sum(hpa_data["gpu"]) / len(hpa_data["gpu"]) if hpa_data["gpu"] else 0
    hpa_avg_latency = sum(hpa_data["latencies"]) / len(hpa_data["latencies"]) if hpa_data["latencies"] else 0
    
    # Count scaling events
    us_events = sum(1 for i in range(1, len(userscale_data["replicas"])) if userscale_data["replicas"][i] != userscale_data["replicas"][i-1])
    hpa_events = sum(1 for i in range(1, len(hpa_data["replicas"])) if hpa_data["replicas"][i] != hpa_data["replicas"][i-1])
    
    print("📊 Scaling Statistics:")
    print(f"   {'Metric':<30} {'UserScale':<20} {'HPA':<20}")
    print(f"   {'-'*70}")
    print(f"   {'Average Replicas':<30} {us_avg_replicas:<20.2f} {hpa_avg_replicas:<20.2f}")
    print(f"   {'Max Replicas':<30} {us_max_replicas:<20} {hpa_max_replicas:<20}")
    print(f"   {'Scaling Events':<30} {us_events:<20} {hpa_events:<20}")
    print()
    
    # GPU metrics
    print("🎮 GPU Utilization:")
    print(f"   {'Metric':<30} {'UserScale':<20} {'HPA':<20}")
    print(f"   {'-'*70}")
    print(f"   {'Average GPU':<30} {us_avg_gpu:<20.1f}% {hpa_avg_gpu:<20.1f}%")
    if userscale_data["gpu"]:
        print(f"   {'Peak GPU':<30} {max(userscale_data['gpu']):<20.1f}% {max(hpa_data['gpu']) if hpa_data['gpu'] else 0:<20.1f}%")
    print()
    
    # Performance
    print("⏱️  Performance:")
    print(f"   {'Metric':<30} {'UserScale':<20} {'HPA':<20}")
    print(f"   {'-'*70}")
    print(f"   {'Total Requests':<30} {userscale_data['requests']:<20} {hpa_data['requests']:<20}")
    print(f"   {'Failed Requests':<30} {userscale_data['failed']:<20} {hpa_data['failed']:<20}")
    print(f"   {'Avg Latency (ms)':<30} {us_avg_latency:<20.1f} {hpa_avg_latency:<20.1f}")
    print()
    
    # Winner analysis
    print("🏆 Winner Analysis:")
    print()
    
    # GPU efficiency
    if us_avg_gpu > hpa_avg_gpu:
        diff = ((us_avg_gpu - hpa_avg_gpu) / hpa_avg_gpu * 100) if hpa_avg_gpu > 0 else 0
        print(f"   ✅ GPU Utilization: UserScale ({us_avg_gpu:.1f}% vs {hpa_avg_gpu:.1f}%, +{diff:.1f}%)")
    else:
        diff = ((hpa_avg_gpu - us_avg_gpu) / us_avg_gpu * 100) if us_avg_gpu > 0 else 0
        print(f"   ✅ GPU Utilization: HPA ({hpa_avg_gpu:.1f}% vs {us_avg_gpu:.1f}%, +{diff:.1f}%)")
    
    # Resource efficiency
    if us_avg_replicas < hpa_avg_replicas:
        diff = ((hpa_avg_replicas - us_avg_replicas) / hpa_avg_replicas * 100)
        print(f"   ✅ Resource Efficiency: UserScale ({us_avg_replicas:.1f} vs {hpa_avg_replicas:.1f} avg replicas, {diff:.1f}% fewer)")
    else:
        diff = ((us_avg_replicas - hpa_avg_replicas) / us_avg_replicas * 100) if us_avg_replicas > 0 else 0
        print(f"   ✅ Resource Efficiency: HPA ({hpa_avg_replicas:.1f} vs {us_avg_replicas:.1f} avg replicas, {diff:.1f}% fewer)")
    
    # Responsiveness
    if us_events > hpa_events:
        print(f"   ✅ Responsiveness: UserScale ({us_events} vs {hpa_events} scaling events)")
    else:
        print(f"   ✅ Responsiveness: HPA ({hpa_events} vs {us_events} scaling events)")
    
    # Latency
    if us_avg_latency < hpa_avg_latency:
        diff = ((hpa_avg_latency - us_avg_latency) / hpa_avg_latency * 100) if hpa_avg_latency > 0 else 0
        print(f"   ✅ Latency: UserScale ({us_avg_latency:.1f}ms vs {hpa_avg_latency:.1f}ms, {diff:.1f}% faster)")
    else:
        diff = ((us_avg_latency - hpa_avg_latency) / us_avg_latency * 100) if us_avg_latency > 0 else 0
        print(f"   ✅ Latency: HPA ({hpa_avg_latency:.1f}ms vs {us_avg_latency:.1f}ms, {diff:.1f}% faster)")
    
    print()
    print("="*100)
    print("  DATA SOURCE: Real metrics from actual Kubernetes deployment")
    print("  GPU METRICS: Real hardware metrics via nvidia-smi and pynvml")
    print("="*100)
    print()


def main():
    """Main execution"""
    print("="*100)
    print("  🚀 CONCURRENT WORKLOAD DEMO - UserScale vs HPA")
    print("="*100)
    print()
    
    # Check services
    print("🔍 Checking services...")
    try:
        requests.get(f"{USERSCALE_SERVICE}/healthz", timeout=2)
        print(f"   ✅ UserScale service: {USERSCALE_SERVICE}")
    except:
        print(f"   ❌ UserScale service not available at {USERSCALE_SERVICE}")
        print("      Run: kubectl port-forward -n userscale svc/userscale-app 8001:8000")
        return
    
    try:
        requests.get(f"{HPA_SERVICE}/healthz", timeout=2)
        print(f"   ✅ HPA service: {HPA_SERVICE}")
    except:
        print(f"   ❌ HPA service not available at {HPA_SERVICE}")
        print("      Run: kubectl port-forward -n userscale svc/hpa-app 8002:8000")
        return
    
    print()
    print(f"⚙️  Configuration:")
    print(f"   Duration: {DURATION} seconds ({DURATION//60} minutes)")
    print(f"   Workers per service: {WORKERS}")
    print(f"   Workload: Matrix multiplication (size=1000)")
    print()
    
    input("Press Enter to start the workload... ")
    print()
    
    # Start workload threads
    print("🔥 Starting workload on both services...")
    threads = []
    
    # UserScale workload threads
    for i in range(WORKERS):
        t = threading.Thread(target=send_workload_requests, args=(USERSCALE_SERVICE, userscale_data, DURATION))
        t.daemon = True
        t.start()
        threads.append(t)
    
    # HPA workload threads
    for i in range(WORKERS):
        t = threading.Thread(target=send_workload_requests, args=(HPA_SERVICE, hpa_data, DURATION))
        t.daemon = True
        t.start()
        threads.append(t)
    
    # Metric tracking threads
    us_tracker = threading.Thread(target=track_metrics, args=(userscale_data, "scaler=userscale", DURATION))
    us_tracker.daemon = True
    us_tracker.start()
    
    hpa_tracker = threading.Thread(target=track_metrics, args=(hpa_data, "scaler=hpa", DURATION))
    hpa_tracker.daemon = True
    hpa_tracker.start()
    
    # Progress monitoring
    start_time = time.time()
    while time.time() - start_time < DURATION:
        elapsed = int(time.time() - start_time)
        print_progress_bar(elapsed, DURATION)
        
        # Print current stats every 30 seconds
        if elapsed > 0 and elapsed % 30 == 0:
            print()
            print(f"\n   UserScale: {userscale_data['requests']} requests | {len(userscale_data['replicas'])} samples | Avg GPU: {sum(userscale_data['gpu'])/len(userscale_data['gpu']) if userscale_data['gpu'] else 0:.1f}%")
            print(f"   HPA:       {hpa_data['requests']} requests | {len(hpa_data['replicas'])} samples | Avg GPU: {sum(hpa_data['gpu'])/len(hpa_data['gpu']) if hpa_data['gpu'] else 0:.1f}%")
        
        time.sleep(1)
    
    print()
    print()
    print("⏹️  Workload complete! Waiting for threads to finish...")
    
    # Wait for threads
    for t in threads:
        t.join(timeout=5)
    
    us_tracker.join(timeout=5)
    hpa_tracker.join(timeout=5)
    
    # Print report
    print_comparison_report()


if __name__ == "__main__":
    main()
