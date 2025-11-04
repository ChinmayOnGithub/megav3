#!/usr/bin/env python3
"""
Side-by-Side Monitor: UserScale vs HPA
Real-time comparison of both autoscalers with live GPU metrics
"""

import subprocess
import time
import json
from typing import Dict, List, Tuple
from datetime import datetime
import requests

NAMESPACE = "userscale"
REFRESH_INTERVAL = 5  # seconds

# Tracking data
userscale_history = {"replicas": [], "gpu": [], "events": 0, "timestamps": []}
hpa_history = {"replicas": [], "gpu": [], "events": 0, "timestamps": []}


def get_host_gpu_metrics() -> Dict:
    """Get real GPU metrics from host using nvidia-smi"""
    try:
        cmd = "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(',')
            if len(parts) >= 4:
                gpu_util = float(parts[0].strip())
                mem_used = float(parts[1].strip())
                mem_total = float(parts[2].strip())
                temp = float(parts[3].strip())
                mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
                
                return {
                    "utilization": gpu_util,
                    "memory_percent": mem_percent,
                    "memory_used_mb": mem_used,
                    "memory_total_mb": mem_total,
                    "temperature": int(temp),
                    "available": True
                }
    except Exception as e:
        pass
    
    return {
        "utilization": 0,
        "memory_percent": 0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "temperature": 0,
        "available": False
    }


def get_pod_metrics(label_selector: str) -> Tuple[List[Dict], int, int]:
    """Get metrics from all pods matching label selector"""
    try:
        # Get pod IPs
        cmd = f'kubectl get pods -n {NAMESPACE} -l {label_selector} -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            return [], 0, 0
        
        data = json.loads(result.stdout)
        pods = data.get('items', [])
        
        running_pods = 0
        pending_pods = 0
        metrics_list = []
        
        for pod in pods:
            status = pod.get('status', {}).get('phase', 'Unknown')
            if status == 'Running':
                running_pods += 1
                pod_ip = pod.get('status', {}).get('podIP')
                
                if pod_ip:
                    try:
                        response = requests.get(f'http://{pod_ip}:8000/metrics', timeout=2)
                        if response.status_code == 200:
                            metrics_list.append(response.json())
                    except:
                        pass
            elif status == 'Pending':
                pending_pods += 1
        
        return metrics_list, running_pods, pending_pods
        
    except Exception as e:
        return [], 0, 0


def get_deployment_replicas(deployment_name: str) -> Tuple[int, int]:
    """Get current and desired replicas for deployment"""
    try:
        cmd = f'kubectl get deployment {deployment_name} -n {NAMESPACE} -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            spec = data.get('spec', {})
            status = data.get('status', {})
            
            desired = spec.get('replicas', 0)
            current = status.get('readyReplicas', 0)
            
            return current, desired
    except:
        pass
    
    return 0, 0


def get_hpa_status() -> Dict:
    """Get HPA status"""
    try:
        cmd = f'kubectl get hpa hpa-autoscaler -n {NAMESPACE} -o json'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            status = data.get('status', {})
            spec = data.get('spec', {})
            
            return {
                "current": status.get('currentReplicas', 0),
                "desired": status.get('desiredReplicas', 0),
                "min": spec.get('minReplicas', 1),
                "max": spec.get('maxReplicas', 20)
            }
    except:
        pass
    
    return {"current": 0, "desired": 0, "min": 1, "max": 20}


def calculate_avg_gpu(metrics_list: List[Dict]) -> float:
    """Calculate average GPU utilization from pod metrics"""
    if not metrics_list:
        return 0.0
    
    gpu_values = []
    for m in metrics_list:
        gpu = m.get('gpu_utilization', 0)
        if gpu > 0:
            gpu_values.append(gpu)
    
    return sum(gpu_values) / len(gpu_values) if gpu_values else 0.0


def format_gpu_bar(percent: float, width: int = 20) -> str:
    """Create a visual bar for GPU utilization"""
    filled = int((percent / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    
    if percent >= 70:
        color = "🔴"
    elif percent >= 40:
        color = "🟡"
    else:
        color = "🟢"
    
    return f"{color} {bar} {percent:5.1f}%"


def print_header():
    """Print monitor header"""
    print("\n" + "="*120)
    print("  🔥 USERSCALE vs HPA - SIDE-BY-SIDE COMPARISON")
    print("  Real-time GPU-aware autoscaling comparison")
    print("="*120)
    print()


def print_metrics_row(timestamp: str, userscale_data: Dict, hpa_data: Dict, host_gpu: Dict):
    """Print a single row of metrics for both scalers"""
    
    # UserScale section
    us_replicas = f"{userscale_data['current']}/{userscale_data['desired']}"
    us_pods = f"{userscale_data['running']} Running"
    if userscale_data['pending'] > 0:
        us_pods += f", {userscale_data['pending']} Pending"
    
    us_gpu = userscale_data['avg_gpu']
    us_gpu_bar = format_gpu_bar(us_gpu)
    
    # HPA section
    hpa_replicas = f"{hpa_data['current']}/{hpa_data['desired']}"
    hpa_pods = f"{hpa_data['running']} Running"
    if hpa_data['pending'] > 0:
        hpa_pods += f", {hpa_data['pending']} Pending"
    
    hpa_gpu = hpa_data['avg_gpu']
    hpa_gpu_bar = format_gpu_bar(hpa_gpu)
    
    # Host GPU
    host_gpu_bar = format_gpu_bar(host_gpu['utilization'])
    
    print(f"[{timestamp}]")
    print(f"┌─────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────┐")
    print(f"│ 🟢 USERSCALE (GPU-Aware)                                │ 🔵 HPA (CPU-Based)                                      │")
    print(f"├─────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┤")
    print(f"│ 📦 Replicas: {us_replicas:<43} │ 📦 Replicas: {hpa_replicas:<43} │")
    print(f"│ 🏃 Pods: {us_pods:<47} │ 🏃 Pods: {hpa_pods:<47} │")
    print(f"│ 🎮 GPU (Pod): {us_gpu_bar:<40} │ 🎮 GPU (Pod): {hpa_gpu_bar:<40} │")
    print(f"│ 📊 Avg Replicas: {userscale_data['avg_replicas']:<37.1f} │ 📊 Avg Replicas: {hpa_data['avg_replicas']:<37.1f} │")
    print(f"│ 📈 Max Replicas: {userscale_data['max_replicas']:<37} │ 📈 Max Replicas: {hpa_data['max_replicas']:<37} │")
    print(f"│ ⚡ Scaling Events: {userscale_data['events']:<35} │ ⚡ Scaling Events: {hpa_data['events']:<35} │")
    print(f"└─────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────┘")
    print(f"│ 🖥️  HOST GPU (nvidia-smi): {host_gpu_bar:<70} │")
    print(f"│    Memory: {host_gpu['memory_used_mb']:.0f}/{host_gpu['memory_total_mb']:.0f} MB ({host_gpu['memory_percent']:.1f}%) | Temp: {host_gpu['temperature']}°C                                           │")
    print(f"└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘")
    print()


def track_scaling_event(history: Dict, current_replicas: int):
    """Track scaling events"""
    if history['replicas'] and history['replicas'][-1] != current_replicas:
        history['events'] += 1


def update_history(history: Dict, replicas: int, gpu: float):
    """Update history with new data point"""
    history['replicas'].append(replicas)
    history['gpu'].append(gpu)
    history['timestamps'].append(time.time())
    
    # Keep last 100 data points
    if len(history['replicas']) > 100:
        history['replicas'].pop(0)
        history['gpu'].pop(0)
        history['timestamps'].pop(0)


def get_stats(history: Dict) -> Dict:
    """Calculate statistics from history"""
    if not history['replicas']:
        return {"avg_replicas": 0, "max_replicas": 0, "avg_gpu": 0}
    
    return {
        "avg_replicas": sum(history['replicas']) / len(history['replicas']),
        "max_replicas": max(history['replicas']),
        "avg_gpu": sum(history['gpu']) / len(history['gpu']) if history['gpu'] else 0
    }


def print_final_summary():
    """Print final comparison summary"""
    us_stats = get_stats(userscale_history)
    hpa_stats = get_stats(hpa_history)
    
    print("\n" + "="*120)
    print("  📊 FINAL COMPARISON SUMMARY")
    print("="*120)
    print()
    
    print(f"📈 Replica Scaling Patterns:")
    if len(userscale_history['replicas']) > 0:
        us_pattern = " → ".join(map(str, userscale_history['replicas'][-10:]))  # Last 10
        print(f"   UserScale: [{us_pattern}]")
    if len(hpa_history['replicas']) > 0:
        hpa_pattern = " → ".join(map(str, hpa_history['replicas'][-10:]))  # Last 10
        print(f"   HPA:       [{hpa_pattern}]")
    
    print()
    print(f"📊 Statistics:")
    print(f"   {'Metric':<25} {'UserScale':<20} {'HPA':<20}")
    print(f"   {'-'*65}")
    print(f"   {'Average Replicas':<25} {us_stats['avg_replicas']:<20.2f} {hpa_stats['avg_replicas']:<20.2f}")
    print(f"   {'Max Replicas':<25} {us_stats['max_replicas']:<20} {hpa_stats['max_replicas']:<20}")
    print(f"   {'Scaling Events':<25} {userscale_history['events']:<20} {hpa_history['events']:<20}")
    print(f"   {'Avg GPU Utilization':<25} {us_stats['avg_gpu']:<20.1f}% {hpa_stats['avg_gpu']:<20.1f}%")
    
    print()
    print(f"🏆 Winner Analysis:")
    
    # Determine winner
    if us_stats['avg_gpu'] > hpa_stats['avg_gpu']:
        print(f"   ✅ UserScale: Higher GPU utilization ({us_stats['avg_gpu']:.1f}% vs {hpa_stats['avg_gpu']:.1f}%)")
    else:
        print(f"   ✅ HPA: Higher GPU utilization ({hpa_stats['avg_gpu']:.1f}% vs {us_stats['avg_gpu']:.1f}%)")
    
    if us_stats['avg_replicas'] < hpa_stats['avg_replicas']:
        print(f"   ✅ UserScale: More efficient ({us_stats['avg_replicas']:.1f} vs {hpa_stats['avg_replicas']:.1f} avg replicas)")
    else:
        print(f"   ✅ HPA: More efficient ({hpa_stats['avg_replicas']:.1f} vs {us_stats['avg_replicas']:.1f} avg replicas)")
    
    if userscale_history['events'] > hpa_history['events']:
        print(f"   ✅ UserScale: More responsive ({userscale_history['events']} vs {hpa_history['events']} scaling events)")
    else:
        print(f"   ✅ HPA: More responsive ({hpa_history['events']} vs {userscale_history['events']} scaling events)")
    
    print()
    print("="*120)


def main():
    """Main monitoring loop"""
    print_header()
    
    print("🔍 Checking deployments...")
    
    # Check if deployments exist
    us_current, us_desired = get_deployment_replicas("userscale-app")
    hpa_current, hpa_desired = get_deployment_replicas("hpa-app")
    
    if us_desired == 0 and hpa_desired == 0:
        print("❌ No deployments found!")
        print("   Run: python setup.py")
        return
    
    print(f"✅ UserScale deployment: {us_current}/{us_desired} replicas")
    print(f"✅ HPA deployment: {hpa_current}/{hpa_desired} replicas")
    print()
    print(f"📡 Monitoring every {REFRESH_INTERVAL} seconds... (Press Ctrl+C to stop)")
    print()
    
    try:
        while True:
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Get host GPU metrics
            host_gpu = get_host_gpu_metrics()
            
            # Get UserScale metrics
            us_current, us_desired = get_deployment_replicas("userscale-app")
            us_metrics, us_running, us_pending = get_pod_metrics("scaler=userscale")
            us_avg_gpu = calculate_avg_gpu(us_metrics)
            
            track_scaling_event(userscale_history, us_current)
            update_history(userscale_history, us_current, us_avg_gpu)
            us_stats = get_stats(userscale_history)
            
            userscale_data = {
                "current": us_current,
                "desired": us_desired,
                "running": us_running,
                "pending": us_pending,
                "avg_gpu": us_avg_gpu,
                "events": userscale_history['events'],
                **us_stats
            }
            
            # Get HPA metrics
            hpa_current, hpa_desired = get_deployment_replicas("hpa-app")
            hpa_metrics, hpa_running, hpa_pending = get_pod_metrics("scaler=hpa")
            hpa_avg_gpu = calculate_avg_gpu(hpa_metrics)
            
            track_scaling_event(hpa_history, hpa_current)
            update_history(hpa_history, hpa_current, hpa_avg_gpu)
            hpa_stats = get_stats(hpa_history)
            
            hpa_data = {
                "current": hpa_current,
                "desired": hpa_desired,
                "running": hpa_running,
                "pending": hpa_pending,
                "avg_gpu": hpa_avg_gpu,
                "events": hpa_history['events'],
                **hpa_stats
            }
            
            # Print metrics
            print_metrics_row(timestamp, userscale_data, hpa_data, host_gpu)
            
            time.sleep(REFRESH_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
        print_final_summary()


if __name__ == "__main__":
    main()
