#!/usr/bin/env python3
"""
Automated GPU Autoscaling Experiments
Runs HPA and UserScale tests sequentially (90 seconds each)
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
TEST_DURATION = 90  # 90 seconds per test
WORKERS = 20  # Concurrent workers (reduced to prevent timeouts)
WORKLOAD_SIZE = 1500  # Matrix size: 1500x1500 GPU matrix multiplication

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_cmd(cmd):
    """Execute command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""


def get_replicas(deploy):
    """Get current replica count"""
    try:
        out = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        data = json.loads(out)
        return data["status"].get("readyReplicas", 0)
    except:
        return 0


def get_pod_metrics(selector):
    """Get aggregated metrics from all pods"""
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


def generate_load(url, stop_event, stats):
    """Generate load on the service"""
    while not stop_event.is_set():
        try:
            t0 = time.time()
            r = requests.get(f"{url}/compute?size={WORKLOAD_SIZE}", timeout=120)
            latency = (time.time() - t0) * 1000
            
            if r.status_code == 200:
                stats["requests"] += 1
                stats["latencies"].append(latency)
            else:
                stats["failures"] += 1
        except Exception as e:
            stats["failures"] += 1
            time.sleep(0.5)


def monitor_scaling(deploy, selector, stop_event, timeline):
    """Monitor pod scaling over time"""
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


def scale_to_zero(deploy):
    """Scale deployment to 0"""
    run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=0")
    time.sleep(5)


def scale_to_one(deploy):
    """Scale deployment to 1"""
    run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas=1")
    time.sleep(10)


def run_experiment(name, url, deploy, selector):
    """Run a single 90-second experiment"""
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
        t = threading.Thread(target=generate_load, args=(url, stop_event, stats))
        t.daemon = True
        t.start()
        load_threads.append(t)
    
    # Run for 90 seconds with progress
    start_time = time.time()
    while time.time() - start_time < TEST_DURATION:
        elapsed = int(time.time() - start_time)
        current_replicas = get_replicas(deploy)
        print(f"\r{elapsed}s/{TEST_DURATION}s | Pods: {current_replicas} | Requests: {stats['requests']} | Failures: {stats['failures']}", end="", flush=True)
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
        
        # Use timeline latencies if stats latencies are empty
        if not stats["latencies"] and timeline:
            timeline_latencies = [t["latency_avg"] for t in timeline if t["latency_avg"] > 0]
            if timeline_latencies:
                stats["latencies"] = timeline_latencies
        
        # Calculate CPU per pod
        cpu_per_pod_list = []
        for t in timeline:
            if t["replicas"] > 0:
                cpu_per_pod_list.append(t["cpu_avg"] / t["replicas"])
        
        results = {
            "experiment": name,
            "duration_seconds": TEST_DURATION,
            "min_pods": min(replicas_list) if replicas_list else 0,
            "max_pods": max(replicas_list) if replicas_list else 0,
            "avg_pods": sum(replicas_list) / len(replicas_list) if replicas_list else 0,
            "gpu_utilization_avg": sum(gpu_avgs) / len(gpu_avgs) if gpu_avgs else 0,
            "gpu_utilization_max": max(gpu_maxs) if gpu_maxs else 0,
            "cpu_utilization_avg": sum(cpu_avgs) / len(cpu_avgs) if cpu_avgs else 0,
            "cpu_per_pod_avg": sum(cpu_per_pod_list) / len(cpu_per_pod_list) if cpu_per_pod_list else 0,
            "latency_avg_ms": sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0,
            "latency_min_ms": min(stats["latencies"]) if stats["latencies"] else 0,
            "latency_max_ms": max(stats["latencies"]) if stats["latencies"] else 0,
            "total_requests": stats["requests"],
            "failed_requests": stats["failures"],
            "success_rate": (stats["requests"] / (stats["requests"] + stats["failures"]) * 100) if (stats["requests"] + stats["failures"]) > 0 else 0,
            "requests_passed": stats["requests"],
            "requests_total": stats["requests"] + stats["failures"],
            "users_per_pod": (stats["requests"] / sum(replicas_list)) if sum(replicas_list) > 0 else 0,
            "timeline": timeline,
            "scaling_events": len([i for i in range(1, len(replicas_list)) if replicas_list[i] != replicas_list[i-1]])
        }
    else:
        results = {"error": "No data collected"}
    
    # Save results
    with open(f"{RESULTS_DIR}/{name.lower().replace(' ', '_')}_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Calculate additional meaningful metrics
    if results.get('requests_total', 0) > 0 and results.get('avg_pods', 0) > 0:
        concurrent_users_per_pod = WORKERS / results.get('avg_pods', 1)
        results['concurrent_users_per_pod'] = f"{concurrent_users_per_pod:.1f} users"
        
        # Throughput: requests per second
        results['throughput_rps'] = results.get('total_requests', 0) / TEST_DURATION
        
        # Resource efficiency: requests per pod
        results['requests_per_pod'] = results.get('total_requests', 0) / results.get('avg_pods', 1)
        
        # Scaling efficiency: avg pods / max pods (lower is better)
        results['scaling_efficiency'] = results.get('avg_pods', 0) / max(results.get('max_pods', 1), 1)
        
        # GPU efficiency: GPU utilization / avg pods (higher is better)
        results['gpu_efficiency'] = results.get('gpu_utilization_avg', 0) / max(results.get('avg_pods', 1), 1)
    else:
        results['concurrent_users_per_pod'] = "0 users"
        results['throughput_rps'] = 0
        results['requests_per_pod'] = 0
        results['scaling_efficiency'] = 0
        results['gpu_efficiency'] = 0
    
    # Print summary
    print(f"\n{name} RESULTS:")
    print(f"  Pods: min={results.get('min_pods', 0)} max={results.get('max_pods', 0)} avg={results.get('avg_pods', 0):.1f}")
    print(f"  GPU: avg={results.get('gpu_utilization_avg', 0):.1f}% max={results.get('gpu_utilization_max', 0):.1f}%")
    print(f"  CPU per pod: avg={results.get('cpu_per_pod_avg', 0):.1f}%")
    print(f"  Response time max: {results.get('latency_max_ms', 0):.1f}ms")
    print(f"  Requests: {results.get('requests_passed', 0)}/{results.get('requests_total', 0)} (success: {results.get('success_rate', 0):.1f}%)")
    print(f"  Throughput: {results.get('throughput_rps', 0):.2f} req/s")
    print(f"  Concurrent users per pod: {results['concurrent_users_per_pod']}")
    print(f"  Requests per pod: {results.get('requests_per_pod', 0):.1f}")
    print(f"  Scaling events: {results.get('scaling_events', 0)}")
    print(f"  GPU efficiency: {results.get('gpu_efficiency', 0):.1f}% per pod")
    
    return results


def print_comparison(hpa_results, userscale_results):
    """Print comparison between HPA and UserScale - ONLY required metrics"""
    print(f"\n{'='*90}")
    print(f"  FINAL COMPARISON - HPA vs UserScale")
    print(f"{'='*90}\n")
    
    # Calculate concurrent users per pod for both
    hpa_concurrent_users = WORKERS / hpa_results.get('avg_pods', 1)
    us_concurrent_users = WORKERS / userscale_results.get('avg_pods', 1)
    
    # Calculate winners
    def winner(hpa_val, us_val, lower_is_better=False):
        if abs(hpa_val - us_val) < 0.01:
            return "TIE"
        if lower_is_better:
            return "HPA" if hpa_val < us_val else "UserScale"
        else:
            return "HPA" if hpa_val > us_val else "UserScale"
    
    print(f"{'Metric':<40} {'HPA':<20} {'UserScale':<20} {'Winner':<10}")
    print(f"{'-'*90}")
    
    # Min Pods
    w = winner(hpa_results.get('min_pods', 0), userscale_results.get('min_pods', 0), lower_is_better=True)
    print(f"{'Min Pods':<40} {hpa_results.get('min_pods', 0):<20} {userscale_results.get('min_pods', 0):<20} {w:<10}")
    
    # Max Pods
    w = winner(hpa_results.get('max_pods', 0), userscale_results.get('max_pods', 0), lower_is_better=True)
    print(f"{'Max Pods':<40} {hpa_results.get('max_pods', 0):<20} {userscale_results.get('max_pods', 0):<20} {w:<10}")
    
    # Concurrent Users Per Pod (human-readable)
    w = winner(hpa_concurrent_users, us_concurrent_users, lower_is_better=False)
    print(f"{'Concurrent Users Per Pod':<40} {f'{hpa_concurrent_users:.1f} users':<20} {f'{us_concurrent_users:.1f} users':<20} {w:<10}")
    
    # Scaling Events
    w = winner(hpa_results.get('scaling_events', 0), userscale_results.get('scaling_events', 0), lower_is_better=False)
    print(f"{'Scaling Events':<40} {hpa_results.get('scaling_events', 0):<20} {userscale_results.get('scaling_events', 0):<20} {w:<10}")
    
    # Response Time Max (ONLY)
    w = winner(hpa_results.get('latency_max_ms', 0), userscale_results.get('latency_max_ms', 0), lower_is_better=True)
    print(f"{'Response Time Max (ms)':<40} {f'{hpa_results.get("latency_max_ms", 0):.1f}':<20} {f'{userscale_results.get("latency_max_ms", 0):.1f}':<20} {w:<10}")
    
    # GPU Utilization
    w = winner(hpa_results.get('gpu_utilization_avg', 0), userscale_results.get('gpu_utilization_avg', 0), lower_is_better=False)
    print(f"{'GPU Utilization (%)':<40} {f'{hpa_results.get("gpu_utilization_avg", 0):.1f}':<20} {f'{userscale_results.get("gpu_utilization_avg", 0):.1f}':<20} {w:<10}")
    
    # CPU Per Pod
    w = winner(hpa_results.get('cpu_per_pod_avg', 0), userscale_results.get('cpu_per_pod_avg', 0), lower_is_better=True)
    print(f"{'CPU Utilization Per Pod (%)':<40} {f'{hpa_results.get("cpu_per_pod_avg", 0):.1f}':<20} {f'{userscale_results.get("cpu_per_pod_avg", 0):.1f}':<20} {w:<10}")
    
    # Requests Passed (successful/total format)
    hpa_passed = f"{hpa_results.get('requests_passed', 0)}/{hpa_results.get('requests_total', 0)}"
    us_passed = f"{userscale_results.get('requests_passed', 0)}/{userscale_results.get('requests_total', 0)}"
    w = winner(hpa_results.get('requests_passed', 0), userscale_results.get('requests_passed', 0), lower_is_better=False)
    print(f"{'Requests Passed':<40} {hpa_passed:<20} {us_passed:<20} {w:<10}")
    
    print(f"\n{'--- ADDITIONAL METRICS ---':<40}")
    
    # Throughput
    w = winner(hpa_results.get('throughput_rps', 0), userscale_results.get('throughput_rps', 0), lower_is_better=False)
    print(f"{'Throughput (req/s)':<40} {f'{hpa_results.get("throughput_rps", 0):.2f}':<20} {f'{userscale_results.get("throughput_rps", 0):.2f}':<20} {w:<10}")
    
    # Requests Per Pod
    w = winner(hpa_results.get('requests_per_pod', 0), userscale_results.get('requests_per_pod', 0), lower_is_better=False)
    print(f"{'Requests Per Pod':<40} {f'{hpa_results.get("requests_per_pod", 0):.1f}':<20} {f'{userscale_results.get("requests_per_pod", 0):.1f}':<20} {w:<10}")
    
    # GPU Efficiency
    w = winner(hpa_results.get('gpu_efficiency', 0), userscale_results.get('gpu_efficiency', 0), lower_is_better=False)
    print(f"{'GPU Efficiency (% per pod)':<40} {f'{hpa_results.get("gpu_efficiency", 0):.1f}':<20} {f'{userscale_results.get("gpu_efficiency", 0):.1f}':<20} {w:<10}")
    
    # Scaling Efficiency
    w = winner(hpa_results.get('scaling_efficiency', 0), userscale_results.get('scaling_efficiency', 0), lower_is_better=True)
    print(f"{'Scaling Efficiency (avg/max)':<40} {f'{hpa_results.get("scaling_efficiency", 0):.2f}':<20} {f'{userscale_results.get("scaling_efficiency", 0):.2f}':<20} {w:<10}")
    
    # Save comparison
    comparison = {
        "hpa": hpa_results,
        "userscale": userscale_results,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(f"{RESULTS_DIR}/comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    
    print(f"\nResults saved to {RESULTS_DIR}/")


def ensure_deployment_scaled(deploy, replicas=1):
    """
    Ensure deployment is scaled to desired replicas
    """
    try:
        result = run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE} -o json")
        if result:
            dep = json.loads(result)
            current_replicas = dep.get("spec", {}).get("replicas", 0)
            
            if current_replicas != replicas:
                print(f"Scaling {deploy} from {current_replicas} to {replicas} replicas...")
                run_cmd(f"kubectl scale deployment {deploy} -n {NAMESPACE} --replicas={replicas}")
                time.sleep(5)
                return True
            return True
    except:
        return False


def ensure_port_forward(service, local_port):
    """
    Ensure port forwarding is active, restart if needed
    """
    # Check if port is already in use
    try:
        result = subprocess.run(
            f"lsof -ti:{local_port}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Port is in use, check if it's our port-forward
            pid = result.stdout.strip()
            if pid:
                # Kill existing process
                subprocess.run(f"kill {pid}", shell=True, timeout=5)
                time.sleep(2)
    except:
        pass
    
    # Start port forwarding in background
    try:
        subprocess.Popen(
            f"kubectl port-forward -n {NAMESPACE} svc/{service} {local_port}:8000",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(3)
        return True
    except:
        return False


def check_service_ready(name, url, deploy, max_retries=20):
    """
    Robust service readiness check with automatic fixes
    """
    print(f"Checking {name} service...")
    
    # First, ensure deployment is scaled up
    ensure_deployment_scaled(deploy, replicas=1)
    
    # Ensure port forwarding is active
    local_port = 8002 if "hpa" in deploy else 8001
    ensure_port_forward(deploy, local_port)
    
    for attempt in range(max_retries):
        try:
            # Try HTTP health check first
            response = requests.get(f"{url}/healthz", timeout=3)
            if response.status_code == 200:
                print(f"{name} service ready (HTTP check passed)")
                return True
        except:
            pass
        
        # Fallback: Check pod status via kubectl
        try:
            result = run_cmd(f"kubectl get pods -n {NAMESPACE} -l app={deploy},scaler={'hpa' if 'hpa' in deploy else 'userscale'} -o json")
            if result:
                pods = json.loads(result)
                items = pods.get("items", [])
                
                if not items:
                    # No pods found, ensure deployment is scaled
                    if attempt == 5:
                        print(f"WARNING: No pods found, rescaling {deploy}...")
                        ensure_deployment_scaled(deploy, replicas=1)
                    continue
                
                # Check if any pod is running and ready
                for pod in items:
                    status = pod.get("status", {})
                    phase = status.get("phase", "")
                    conditions = status.get("conditions", [])
                    
                    # Check if pod is Running
                    if phase == "Running":
                        # Check if pod is Ready
                        for condition in conditions:
                            if condition.get("type") == "Ready" and condition.get("status") == "True":
                                print(f"{name} service ready (pod running and ready)")
                                # Give it a moment to fully initialize
                                time.sleep(2)
                                return True
                    
                    # Check for CrashLoopBackOff or other issues
                    container_statuses = status.get("containerStatuses", [])
                    for cs in container_statuses:
                        state = cs.get("state", {})
                        if "waiting" in state:
                            reason = state["waiting"].get("reason", "")
                            if "CrashLoopBackOff" in reason or "Error" in reason:
                                print(f"ERROR: {name} pod in {reason} state")
                                print(f"   Checking logs...")
                                run_cmd(f"kubectl logs -n {NAMESPACE} -l app={deploy} --tail=20")
                                return False
        except Exception as e:
            pass
        
        # Wait before retry
        if attempt < max_retries - 1:
            print(f"⏳ {name} not ready yet, waiting... (attempt {attempt + 1}/{max_retries})")
            time.sleep(3)
    
    print(f"ERROR: {name} service not ready after {max_retries} attempts")
    print(f"   Checking deployment status...")
    run_cmd(f"kubectl get deployment {deploy} -n {NAMESPACE}")
    run_cmd(f"kubectl get pods -n {NAMESPACE} -l app={deploy}")
    return False


def preflight_check():
    """
    Pre-flight checks and automatic setup
    """
    print("\nPRE-FLIGHT CHECKS\n")
    
    # Check namespace exists
    result = run_cmd("kubectl get namespace userscale 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print("ERROR: Namespace 'userscale' not found")
        print("   Run: python3 run_files/setup.py")
        return False
    print("Namespace exists")
    
    # Check deployments exist
    result = run_cmd(f"kubectl get deployment {HPA_DEPLOY} -n {NAMESPACE} 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print(f"ERROR: Deployment '{HPA_DEPLOY}' not found")
        print("   Run: kubectl apply -f k8s/hpa-gpu.yaml")
        return False
    print(f"{HPA_DEPLOY} deployment exists")
    
    result = run_cmd(f"kubectl get deployment {USERSCALE_DEPLOY} -n {NAMESPACE} 2>&1")
    if "NotFound" in result or "not found" in result.lower():
        print(f"ERROR: Deployment '{USERSCALE_DEPLOY}' not found")
        print("   Run: kubectl apply -f k8s/userscale-gpu.yaml")
        return False
    print(f"{USERSCALE_DEPLOY} deployment exists")
    
    # Kill any existing port forwards
    print("🔄 Cleaning up old port forwards...")
    subprocess.run("pkill -f 'kubectl port-forward'", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    return True


def main():
    print("\n" + "="*80)
    print("  GPU-AWARE AUTOSCALING EXPERIMENTS")
    print("  HPA vs UserScale - 90 seconds each")
    print("="*80 + "\n")
    
    # Display workload information
    print(f"WORKLOAD CONFIGURATION:")
    print(f"   Type: Matrix Multiplication (GPU-intensive)")
    print(f"   Size: {WORKLOAD_SIZE}×{WORKLOAD_SIZE} matrices")
    print(f"   Concurrent Workers: {WORKERS}")
    print(f"   Test Duration: {TEST_DURATION} seconds per experiment\n")
    
    # Pre-flight checks
    if not preflight_check():
        return
    
    # Robust service readiness checks with automatic fixes
    hpa_ready = check_service_ready("HPA", HPA_URL, HPA_DEPLOY)
    userscale_ready = check_service_ready("UserScale", USERSCALE_URL, USERSCALE_DEPLOY)
    
    if not hpa_ready or not userscale_ready:
        print("\nERROR: Services not ready after automatic fixes.")
        print("\nTROUBLESHOOTING:")
        print("   1. Check deployments:")
        print("      kubectl get deployments -n userscale")
        print("   2. Check pods:")
        print("      kubectl get pods -n userscale")
        print("   3. Check pod logs:")
        print(f"      kubectl logs -n userscale -l app={HPA_DEPLOY if not hpa_ready else USERSCALE_DEPLOY}")
        print("   4. Manual port forward:")
        print("      kubectl port-forward -n userscale svc/hpa-app 8002:8000 &")
        print("      kubectl port-forward -n userscale svc/userscale-app 8001:8000 &")
        return
    
    print("\nAll services ready!\n")
    input("Press Enter to start experiments...\n")
    
    # Experiment 1: HPA
    scale_to_one(HPA_DEPLOY)
    hpa_results = run_experiment(
        "HPA",
        HPA_URL,
        HPA_DEPLOY,
        "app=hpa-app,scaler=hpa"
    )
    scale_to_zero(HPA_DEPLOY)
    
    print("\nWaiting 15 seconds before next experiment...")
    time.sleep(15)
    
    # Experiment 2: UserScale
    scale_to_one(USERSCALE_DEPLOY)
    userscale_results = run_experiment(
        "UserScale",
        USERSCALE_URL,
        USERSCALE_DEPLOY,
        "app=userscale-app,scaler=userscale"
    )
    scale_to_zero(USERSCALE_DEPLOY)
    
    # Print comparison
    print_comparison(hpa_results, userscale_results)
    
    print("\nExperiments complete!")


if __name__ == "__main__":
    main()
