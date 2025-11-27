#!/usr/bin/env python3
"""
Watch scaling decisions and metrics in real-time
"""

import subprocess
import time
import json
import requests

NAMESPACE = "userscale"
PORT = 8000

def get_replicas(deployment):
    """Get current replica count"""
    try:
        cmd = f"kubectl get deployment {deployment} -n {NAMESPACE} -o json"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        data = json.loads(result.stdout)
        return data["status"].get("readyReplicas", 0)
    except:
        return 0

def get_pod_ips(label):
    """Get IPs of running pods"""
    try:
        cmd = f"kubectl get pods -n {NAMESPACE} -l {label} --field-selector=status.phase=Running -o json"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        data = json.loads(result.stdout)
        return [pod["status"].get("podIP") for pod in data.get("items", []) if pod["status"].get("podIP")]
    except:
        return []

def get_aggregated_metrics(ips):
    """Get aggregated metrics from all pods"""
    gpu_vals = []
    cpu_vals = []
    latencies = []
    total_requests = 0
    concurrent_requests = 0
    
    for ip in ips:
        try:
            response = requests.get(f"http://{ip}:{PORT}/metrics", timeout=2)
            metrics = response.json()
            
            if metrics.get("gpu_utilization", 0) > 0:
                gpu_vals.append(metrics["gpu_utilization"])
            cpu_vals.append(metrics.get("cpu_percent", 0))
            if metrics.get("avg_latency_ms", 0) > 0:
                latencies.append(metrics["avg_latency_ms"])
            total_requests += metrics.get("request_count", 0)
            concurrent_requests += metrics.get("concurrent_requests", 0)
        except:
            pass
    
    return {
        "gpu_avg": sum(gpu_vals) / len(gpu_vals) if gpu_vals else 0,
        "cpu_avg": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
        "latency_avg": sum(latencies) / len(latencies) if latencies else 0,
        "total_requests": total_requests,
        "concurrent_requests": concurrent_requests
    }

def main():
    print("\n" + "="*120)
    print("  SCALING MONITOR - Real-time Metrics & Decisions")
    print("="*120 + "\n")
    
    deployment_choice = input("Monitor [1] HPA or [2] UserScale? (1/2): ").strip()
    
    if deployment_choice == "1":
        deployment = "hpa-app"
        label = "app=hpa-app,scaler=hpa"
        name = "HPA"
    else:
        deployment = "userscale-app"
        label = "app=userscale-app,scaler=userscale"
        name = "UserScale"
    
    print(f"\nMonitoring {name} scaling...\n")
    print(f"{'Time':<12} {'Pods':<8} {'GPU %':<10} {'CPU %':<10} {'Latency (ms)':<15} {'Requests':<12} {'Concurrent':<12}")
    print("-" * 120)
    
    prev_replicas = 0
    
    try:
        while True:
            replicas = get_replicas(deployment)
            ips = get_pod_ips(label)
            metrics = get_aggregated_metrics(ips)
            
            timestamp = time.strftime("%H:%M:%S")
            
            # Detect scaling event
            scaling_indicator = ""
            if replicas > prev_replicas:
                scaling_indicator = f" SCALED UP (+{replicas - prev_replicas})"
            elif replicas < prev_replicas:
                scaling_indicator = f" SCALED DOWN (-{prev_replicas - replicas})"
            
            print(f"{timestamp:<12} {replicas:<8} {metrics['gpu_avg']:<10.1f} {metrics['cpu_avg']:<10.1f} "
                  f"{metrics['latency_avg']:<15.1f} {metrics['total_requests']:<12} {metrics['concurrent_requests']:<12}{scaling_indicator}", 
                  flush=True)
            
            prev_replicas = replicas
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")

if __name__ == "__main__":
    main()
