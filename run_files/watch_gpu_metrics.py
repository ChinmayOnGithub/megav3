#!/usr/bin/env python3
"""
Watch GPU metrics from pods in real-time
"""

import subprocess
import time
import json
import requests

NAMESPACE = "userscale"
PORT = 8000

def get_pod_ips(label):
    """Get IPs of running pods"""
    try:
        cmd = f"kubectl get pods -n {NAMESPACE} -l {label} --field-selector=status.phase=Running -o json"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        data = json.loads(result.stdout)
        return [pod["status"].get("podIP") for pod in data.get("items", []) if pod["status"].get("podIP")]
    except:
        return []

def get_metrics(ip):
    """Get metrics from a pod"""
    try:
        response = requests.get(f"http://{ip}:{PORT}/metrics", timeout=2)
        return response.json()
    except:
        return None

def main():
    print("\n" + "="*80)
    print("  GPU METRICS MONITOR")
    print("="*80 + "\n")
    
    deployment = input("Monitor [1] HPA or [2] UserScale? (1/2): ").strip()
    
    if deployment == "1":
        label = "app=hpa-app,scaler=hpa"
        name = "HPA"
    else:
        label = "app=userscale-app,scaler=userscale"
        name = "UserScale"
    
    print(f"\nMonitoring {name} pods...\n")
    print(f"{'Time':<12} {'Pod':<20} {'GPU %':<10} {'CPU %':<10} {'Latency (ms)':<15}")
    print("-" * 80)
    
    try:
        while True:
            ips = get_pod_ips(label)
            timestamp = time.strftime("%H:%M:%S")
            
            if not ips:
                print(f"{timestamp:<12} No pods running", flush=True)
            else:
                for i, ip in enumerate(ips):
                    metrics = get_metrics(ip)
                    if metrics:
                        gpu = metrics.get("gpu_utilization", 0)
                        cpu = metrics.get("cpu_percent", 0)
                        latency = metrics.get("avg_latency_ms", 0)
                        
                        pod_name = f"pod-{i+1}"
                        print(f"{timestamp:<12} {pod_name:<20} {gpu:<10.1f} {cpu:<10.1f} {latency:<15.1f}", flush=True)
                    else:
                        print(f"{timestamp:<12} pod-{i+1:<17} [no metrics]", flush=True)
            
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")

if __name__ == "__main__":
    main()
