#!/usr/bin/env python3
"""
GPU Autoscaling Demo - Sequential Benchmarking
Runs HPA then UserScale with selected workload
"""

import requests
import time
import threading
import subprocess
import json
import os
from datetime import datetime

NAMESPACE = "userscale"
HPA_DEPLOY = "hpa-app"
USERSCALE_DEPLOY = "userscale-app"

HPA_URL = "http://localhost:8002"
USERSCALE_URL = "http://localhost:8001"

PORT = 8000
TEST_DURATION = 90
WORKERS = 20

# Create results directory with timestamp
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULTS_DIR = f"results/{TIMESTAMP}"
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""


def get_replicas(deploy):
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        data = json.loads(out)
        return data["status"].get("readyReplicas", 0)
    except:
        return 0


def get_pod_metrics(selector):
    try:
        out = run_cmd(f"kubectl get pods -n {NAMESPACE} -l {selector} -o json")
        pods = json.loads(out)["items"]
        
        gpu_vals = []
        cpu_vals = []
        latencies = []
        total_requests = 0
        
        for pod in pods:
            ip = pod["status"].get("podIP")
            if not ip:
                continue
            try:
                m = requests.get(f"http://{ip}:{PORT}/metrics", timeout=2).json()
                if m.get("gpu_utilization", 0) > 0:
                    gpu_vals.append(m["gpu_utilization"])
                cpu_vals.append(m.get("cpu_percent", 0))
                if m.get("avg_latency_ms", 0) > 0:
                    latencies.append(m["avg_latency_ms"])
                total_requests += m.get("request_count", 0)
            except:
                pass
        
        return {
            "gpu_avg": sum(gpu_vals) / len(gpu_vals) if gpu_vals else 0,
            "gpu_max": max(gpu_vals) if gpu_vals else 0,
            "cpu_avg": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
            "latency_avg": sum(latencies) / len(latencies) if latencies else 0,
            "latency_max": max(latencies) if latencies else 0,
            "total_requests": total_requests
        }
    except:
        return {"gpu_avg": 0, "gpu_max": 0, "cpu_avg": 0, "latency_avg": 0, "latency_max": 0, "total_requests": 0}


def generate_load(url, workload_size, stop_event, stats):
    while not stop_event.is_set():
        try:
            t0 = time.time()
            r = requests.get(f"{url}/compute?size={workload_size}", timeout=60)  # Reduced timeout
            latency = (time.time() - t0) * 1000
            
            if r.status_code == 200:
                stats["requests"] += 1
                stats["latencies"].append(latency)
            else:
                stats["failures"] += 1
        except Exception:
            stats["failures"] += 1
            time.sleep(1)  # Wait before retry


def monitor_scaling(deploy, selector, stop_event, timeline):
    while not stop_event.is_set():
        replicas = get_replicas(deploy)
        metrics = get_pod_metrics(selector)
        
        timeline.append({
            "time": time.time(),
            "replicas": replicas,
            "gpu_avg": metrics["gpu_avg"],
            "gpu_max": metrics["gpu_max"],
            "cpu_avg": metrics["cpu_avg"],
            "latency_avg": metrics["latency_avg"],
            "latency_max": metrics["latency_max"],
            "total_requests": metrics["total_requests"]
        })
        
        time.sleep(3)


def ensure_running(deploy):
    """Ensure deployment is running with at least 1 replica"""
    # Check current replicas
    result = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
    if result:
        try:
            data = json.loads(result)
            current = data.get("spec", {}).get("replicas", 0)
            if current == 0:
                print(f"WARNING: {deploy} is at 0 replicas, scaling to 1...")
                run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=1")
                time.sleep(15)
        except:
            pass
    
    # Ensure it's running
    run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=1")
    time.sleep(10)
    
    # Wait for ready
    run_cmd(f"kubectl wait --for=condition=ready pod -l app={deploy} -n {NAMESPACE} --timeout=60s")


def pause_other_deployment(deploy):
    """Pause the other deployment during test (but don't scale to 0)"""
    # Just label it as paused, don't scale to 0
    run_cmd(f"kubectl label deployment {deploy} -n {NAMESPACE} test-paused=true --overwrite")
    print(f"PAUSED: {deploy} paused (keeping at 1 replica)")


def resume_deployment(deploy):
    """Resume the deployment"""
    run_cmd(f"kubectl label deployment {deploy} -n {NAMESPACE} test-paused-")
    print(f"RESUMED: {deploy} resumed")


def run_experiment(name, url, deploy, selector, workload_size):
    print(f"\n{'='*80}")
    print(f"  {name} EXPERIMENT - 90 SECONDS")
    print(f"{'='*80}\n")
    
    stats = {"requests": 0, "failures": 0, "latencies": []}
    timeline = []
    stop_event = threading.Event()
    
    # Start monitoring
    monitor_thread = threading.Thread(target=monitor_scaling, args=(deploy, selector, stop_event, timeline))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Start load generators
    load_threads = []
    for _ in range(WORKERS):
        t = threading.Thread(target=generate_load, args=(url, workload_size, stop_event, stats))
        t.daemon = True
        t.start()
        load_threads.append(t)
    
    # Run for 90 seconds
    start_time = time.time()
    while time.time() - start_time < TEST_DURATION:
        elapsed = int(time.time() - start_time)
        current_replicas = get_replicas(deploy)
        print(f"\rTIME: {elapsed}s/{TEST_DURATION}s | Pods: {current_replicas} | Requests: {stats['requests']} | Failures: {stats['failures']}", end="", flush=True)
        time.sleep(1)
    
    print()
    
    # Stop all threads
    stop_event.set()
    time.sleep(2)
    
    # Calculate statistics
    if timeline:
        replicas_list = [t["replicas"] for t in timeline]
        gpu_avgs = [t["gpu_avg"] for t in timeline if t["gpu_avg"] > 0]
        gpu_maxs = [t["gpu_max"] for t in timeline if t["gpu_max"] > 0]
        cpu_avgs = [t["cpu_avg"] for t in timeline]
        
        if not stats["latencies"] and timeline:
            timeline_latencies = [t["latency_avg"] for t in timeline if t["latency_avg"] > 0]
            if timeline_latencies:
                stats["latencies"] = timeline_latencies
        
        cpu_per_pod_list = []
        for t in timeline:
            if t["replicas"] > 0:
                cpu_per_pod_list.append(t["cpu_avg"] / t["replicas"])
        
        # Calculate additional metrics
        avg_pods = sum(replicas_list) / len(replicas_list) if replicas_list else 0
        throughput_rps = stats["requests"] / TEST_DURATION
        requests_per_pod = stats["requests"] / max(avg_pods, 1)
        gpu_efficiency = (sum(gpu_avgs) / len(gpu_avgs) if gpu_avgs else 0) / max(avg_pods, 1)
        scaling_efficiency = avg_pods / max(max(replicas_list) if replicas_list else 1, 1)
        concurrent_users_per_pod = WORKERS / max(avg_pods, 1)
        
        # Calculate percentiles
        sorted_latencies = sorted(stats["latencies"]) if stats["latencies"] else [0]
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        
        results = {
            "experiment": name,
            "duration_seconds": TEST_DURATION,
            "workload_size": workload_size,
            "min_pods": min(replicas_list) if replicas_list else 0,
            "max_pods": max(replicas_list) if replicas_list else 0,
            "avg_pods": avg_pods,
            "gpu_utilization_avg": sum(gpu_avgs) / len(gpu_avgs) if gpu_avgs else 0,
            "gpu_utilization_max": max(gpu_maxs) if gpu_maxs else 0,
            "cpu_utilization_avg": sum(cpu_avgs) / len(cpu_avgs) if cpu_avgs else 0,
            "cpu_per_pod_avg": sum(cpu_per_pod_list) / len(cpu_per_pod_list) if cpu_per_pod_list else 0,
            "latency_avg_ms": sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0,
            "latency_min_ms": min(stats["latencies"]) if stats["latencies"] else 0,
            "latency_max_ms": max(stats["latencies"]) if stats["latencies"] else 0,
            "latency_p95_ms": sorted_latencies[p95_idx] if sorted_latencies else 0,
            "latency_p99_ms": sorted_latencies[p99_idx] if sorted_latencies else 0,
            "total_requests": stats["requests"],
            "failed_requests": stats["failures"],
            "success_rate": (stats["requests"] / (stats["requests"] + stats["failures"]) * 100) if (stats["requests"] + stats["failures"]) > 0 else 0,
            "throughput_rps": throughput_rps,
            "requests_per_pod": requests_per_pod,
            "gpu_efficiency": gpu_efficiency,
            "scaling_efficiency": scaling_efficiency,
            "concurrent_users_per_pod": concurrent_users_per_pod,
            "scaling_events": len([i for i in range(1, len(replicas_list)) if replicas_list[i] != replicas_list[i-1]]),
            "timeline": timeline
        }
    else:
        results = {"error": "No data collected"}
    
    # Save results
    with open(f"{RESULTS_DIR}/{name.lower().replace(' ', '_')}_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary - ONLY specified metrics
    print(f"\n{name} RESULTS:")
    print(f"  Max Pods: {results.get('max_pods', 0)}")
    print(f"  Concurrent Users Per Pod: {results.get('concurrent_users_per_pod', 0):.1f}")
    print(f"  Scaling Events: {results.get('scaling_events', 0)}")
    print(f"  Requests Per Pod: {results.get('requests_per_pod', 0):.1f}")
    print(f"  GPU Efficiency (% per pod): {results.get('gpu_efficiency', 0):.1f}")
    print(f"  Scaling Efficiency: {results.get('scaling_efficiency', 0):.3f}")
    print(f"  Success Rate (%): {results.get('success_rate', 0):.1f}")
    
    return results


def print_comparison(hpa_results, userscale_results):
    print(f"\n{'='*90}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*90}\n")
    
    def winner(hpa_val, us_val, lower_is_better=False):
        if abs(hpa_val - us_val) < 0.01:
            return "TIE"
        if lower_is_better:
            return "HPA" if hpa_val < us_val else "UserScale"
        else:
            return "HPA" if hpa_val > us_val else "UserScale"
    
    print(f"{'Metric':<40} {'HPA':<20} {'UserScale':<20} {'Winner':<10}")
    print("-" * 90)
    
    metrics = [
        ("Max Pods", "max_pods", True),
        ("Concurrent Users Per Pod", "concurrent_users_per_pod", False),
        ("Scaling Events", "scaling_events", False),
        ("Requests Per Pod", "requests_per_pod", False),
        ("GPU Efficiency (% per pod)", "gpu_efficiency", False),
        ("Scaling Efficiency", "scaling_efficiency", False),
        ("Success Rate (%)", "success_rate", False),
    ]
    
    wins = {"HPA": 0, "UserScale": 0, "TIE": 0}
    
    for label, key, lower_better in metrics:
        hpa_val = hpa_results.get(key, 0)
        us_val = userscale_results.get(key, 0)
        w = winner(hpa_val, us_val, lower_better)
        wins[w] += 1
        
        print(f"{label:<40} {hpa_val:<20.2f} {us_val:<20.2f} {w:<10}")
    
    print("\n" + "="*90)
    print("  OVERALL WINNER")
    print("="*90 + "\n")
    
    print(f"HPA Wins:       {wins['HPA']}")
    print(f"UserScale Wins: {wins['UserScale']}")
    print(f"Ties:           {wins['TIE']}")
    
    if wins['UserScale'] > wins['HPA']:
        improvement = ((wins['UserScale'] - wins['HPA']) / len(metrics)) * 100
        print(f"\nWINNER: UserScale ({improvement:.0f}% superiority)")
    elif wins['HPA'] > wins['UserScale']:
        print(f"\nWINNER: HPA")
    else:
        print(f"\nRESULT: Tie")
    
    # Save comparison
    comparison = {
        "hpa": hpa_results,
        "userscale": userscale_results,
        "wins": wins,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(f"{RESULTS_DIR}/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)


def main():
    print("\n" + "="*80)
    print("  GPU-AWARE AUTOSCALING EXPERIMENTS")
    print("="*80 + "\n")
    
    # Application selection
    print("Available GPU Workloads:")
    print("  1. Array Sorting (GPU-intensive sorting operations)")
    print("  2. Image Convolution (GPU-intensive image processing)")
    print("")
    
    app_choice = input("Choose application to run (1 or 2): ").strip()
    
    if app_choice == "1":
        workload_type = "sorting"
        workload_name = "Array Sorting"
        workload_size = 800  # Reduced for faster response
    elif app_choice == "2":
        workload_type = "convolution"
        workload_name = "Image Convolution"
        workload_size = 600  # Reduced for faster response
    else:
        print("Invalid choice. Defaulting to Array Sorting.")
        workload_type = "sorting"
        workload_name = "Array Sorting"
        workload_size = 800
    
    # Update workload type in deployments
    print(f"\nConfiguring workload: {workload_name}")
    run_cmd(f"kubectl set env deployment/hpa-app -n {NAMESPACE} WORKLOAD_TYPE={workload_type}")
    run_cmd(f"kubectl set env deployment/userscale-app -n {NAMESPACE} WORKLOAD_TYPE={workload_type}")
    time.sleep(5)
    
    print(f"\nWORKLOAD CONFIGURATION:")
    print(f"   Type: {workload_name}")
    print(f"   Size: {workload_size}")
    print(f"   Concurrent Workers: {WORKERS}")
    print(f"   Test Duration: {TEST_DURATION} seconds per experiment")
    print(f"   Results Directory: {RESULTS_DIR}\n")
    
    input("Press Enter to start experiments...\n")
    
    # Experiment 1: HPA
    print("\nPreparing HPA experiment...")
    ensure_running(HPA_DEPLOY)
    pause_other_deployment(USERSCALE_DEPLOY)
    
    hpa_results = run_experiment(
        "HPA",
        HPA_URL,
        HPA_DEPLOY,
        "app=hpa-app,scaler=hpa",
        workload_size
    )
    
    print("\nWaiting 15 seconds before next experiment...")
    time.sleep(15)
    
    # Experiment 2: UserScale
    print("\nPreparing UserScale experiment...")
    resume_deployment(USERSCALE_DEPLOY)
    ensure_running(USERSCALE_DEPLOY)
    pause_other_deployment(HPA_DEPLOY)
    
    userscale_results = run_experiment(
        "UserScale",
        USERSCALE_URL,
        USERSCALE_DEPLOY,
        "app=userscale-app,scaler=userscale",
        workload_size
    )
    
    # Resume both
    resume_deployment(HPA_DEPLOY)
    resume_deployment(USERSCALE_DEPLOY)
    
    # Print comparison
    print_comparison(hpa_results, userscale_results)
    
    print(f"\nExperiments complete! Results saved to {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
