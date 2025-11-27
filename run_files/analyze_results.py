#!/usr/bin/env python3
"""
Result Analyzer - Parse and compare experiment results
"""

import json
import os
import glob

RESULTS_DIR = "results"


def load_results():
    """Load latest experiment results from timestamped directory"""
    # Find all timestamped directories
    timestamp_dirs = glob.glob(f"{RESULTS_DIR}/[0-9]*")
    
    if timestamp_dirs:
        # Get the most recent directory
        latest_dir = max(timestamp_dirs)
        print(f"Loading results from: {latest_dir}\n")
        
        try:
            with open(f"{latest_dir}/hpa_results.json") as f:
                hpa = json.load(f)
        except:
            print("WARNING: HPA results not found in latest directory, trying root...")
            try:
                with open(f"{RESULTS_DIR}/hpa_results.json") as f:
                    hpa = json.load(f)
            except:
                hpa = None
        
        try:
            with open(f"{latest_dir}/userscale_results.json") as f:
                userscale = json.load(f)
        except:
            print("WARNING: UserScale results not found in latest directory, trying root...")
            try:
                with open(f"{RESULTS_DIR}/userscale_results.json") as f:
                    userscale = json.load(f)
            except:
                userscale = None
    else:
        # Fallback to root directory
        print(f"Loading results from: {RESULTS_DIR}/\n")
        try:
            with open(f"{RESULTS_DIR}/hpa_results.json") as f:
                hpa = json.load(f)
        except:
            hpa = None
        
        try:
            with open(f"{RESULTS_DIR}/userscale_results.json") as f:
                userscale = json.load(f)
        except:
            userscale = None
    
    return hpa, userscale


def print_comparison(hpa, userscale):
    """Print comparison with winners - ONLY required metrics"""
    print("\n" + "="*90)
    print("  FINAL COMPARISON - HPA vs UserScale")
    print("="*90 + "\n")
    
    if not hpa or not userscale:
        print("ERROR: Missing results. Run demo.py first.")
        return
    
    # Calculate concurrent users per pod and additional metrics (assuming 20 workers)
    WORKERS = 20
    TEST_DURATION = 90
    
    hpa_concurrent_users = WORKERS / hpa.get('avg_pods', 1)
    us_concurrent_users = WORKERS / userscale.get('avg_pods', 1)
    
    # Calculate additional metrics if not present
    if 'throughput_rps' not in hpa:
        hpa['throughput_rps'] = hpa.get('total_requests', 0) / TEST_DURATION
    if 'throughput_rps' not in userscale:
        userscale['throughput_rps'] = userscale.get('total_requests', 0) / TEST_DURATION
    
    if 'requests_per_pod' not in hpa:
        hpa['requests_per_pod'] = hpa.get('total_requests', 0) / max(hpa.get('avg_pods', 1), 1)
    if 'requests_per_pod' not in userscale:
        userscale['requests_per_pod'] = userscale.get('total_requests', 0) / max(userscale.get('avg_pods', 1), 1)
    
    if 'gpu_efficiency' not in hpa:
        hpa['gpu_efficiency'] = hpa.get('gpu_utilization_avg', 0) / max(hpa.get('avg_pods', 1), 1)
    if 'gpu_efficiency' not in userscale:
        userscale['gpu_efficiency'] = userscale.get('gpu_utilization_avg', 0) / max(userscale.get('avg_pods', 1), 1)
    
    if 'scaling_efficiency' not in hpa:
        hpa['scaling_efficiency'] = hpa.get('avg_pods', 0) / max(hpa.get('max_pods', 1), 1)
    if 'scaling_efficiency' not in userscale:
        userscale['scaling_efficiency'] = userscale.get('avg_pods', 0) / max(userscale.get('max_pods', 1), 1)
    
    # Calculate winners
    def winner(hpa_val, us_val, lower_is_better=False):
        if abs(hpa_val - us_val) < 0.01:
            return "TIE"
        if lower_is_better:
            return "HPA" if hpa_val < us_val else "UserScale"
        else:
            return "HPA" if hpa_val > us_val else "UserScale"
    
    print(f"{'Metric':<40} {'HPA':<20} {'UserScale':<20} {'Winner':<10}")
    print("-" * 90)
    
    # Max Pods
    w = winner(hpa.get('max_pods', 0), userscale.get('max_pods', 0), lower_is_better=True)
    print(f"{'Max Pods':<40} {hpa.get('max_pods', 0):<20} {userscale.get('max_pods', 0):<20} {w:<10}")
    
    # Concurrent Users Per Pod
    w = winner(hpa_concurrent_users, us_concurrent_users, lower_is_better=False)
    print(f"{'Concurrent Users Per Pod':<40} {f'{hpa_concurrent_users:.1f}':<20} {f'{us_concurrent_users:.1f}':<20} {w:<10}")
    
    # Scaling Events
    w = winner(hpa.get('scaling_events', 0), userscale.get('scaling_events', 0), lower_is_better=False)
    print(f"{'Scaling Events':<40} {hpa.get('scaling_events', 0):<20} {userscale.get('scaling_events', 0):<20} {w:<10}")
    
    # Requests Per Pod
    w = winner(hpa.get('requests_per_pod', 0), userscale.get('requests_per_pod', 0), lower_is_better=False)
    print(f"{'Requests Per Pod':<40} {f'{hpa.get("requests_per_pod", 0):.1f}':<20} {f'{userscale.get("requests_per_pod", 0):.1f}':<20} {w:<10}")
    
    # GPU Efficiency
    w = winner(hpa.get('gpu_efficiency', 0), userscale.get('gpu_efficiency', 0), lower_is_better=False)
    print(f"{'GPU Efficiency (% per pod)':<40} {f'{hpa.get("gpu_efficiency", 0):.1f}':<20} {f'{userscale.get("gpu_efficiency", 0):.1f}':<20} {w:<10}")
    
    # Scaling Efficiency
    w = winner(hpa.get('scaling_efficiency', 0), userscale.get('scaling_efficiency', 0), lower_is_better=True)
    print(f"{'Scaling Efficiency':<40} {f'{hpa.get("scaling_efficiency", 0):.3f}':<20} {f'{userscale.get("scaling_efficiency", 0):.3f}':<20} {w:<10}")
    
    # Success Rate
    w = winner(hpa.get('success_rate', 0), userscale.get('success_rate', 0), lower_is_better=False)
    print(f"{'Success Rate (%)':<40} {f'{hpa.get("success_rate", 0):.1f}':<20} {f'{userscale.get("success_rate", 0):.1f}':<20} {w:<10}")
    
    # Count wins (7 metrics total)
    wins = {"HPA": 0, "UserScale": 0, "TIE": 0}
    
    metrics = [
        (hpa.get('max_pods', 0), userscale.get('max_pods', 0), True),
        (hpa_concurrent_users, us_concurrent_users, False),
        (hpa.get('scaling_events', 0), userscale.get('scaling_events', 0), False),
        (hpa.get('requests_per_pod', 0), userscale.get('requests_per_pod', 0), False),
        (hpa.get('gpu_efficiency', 0), userscale.get('gpu_efficiency', 0), False),
        (hpa.get('scaling_efficiency', 0), userscale.get('scaling_efficiency', 0), True),
        (hpa.get('success_rate', 0), userscale.get('success_rate', 0), False),
    ]
    
    for hpa_val, us_val, lower_better in metrics:
        w = winner(hpa_val, us_val, lower_better)
        wins[w] += 1
    
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
        deficit = ((wins['HPA'] - wins['UserScale']) / len(metrics)) * 100
        print(f"\nWINNER: HPA ({deficit:.0f}% better than UserScale)")
    else:
        print(f"\nRESULT: Tie")
    
    # Calculate key improvements
    if hpa.get('gpu_utilization_avg', 0) > 0:
        gpu_diff = userscale.get('gpu_utilization_avg', 0) - hpa.get('gpu_utilization_avg', 0)
        if gpu_diff > 0:
            print(f"\nUserScale GPU improvement: +{gpu_diff:.1f}%")
        else:
            print(f"\nUserScale GPU deficit: {gpu_diff:.1f}%")
    
    if hpa_concurrent_users > 0:
        throughput_improvement = ((us_concurrent_users - hpa_concurrent_users) / hpa_concurrent_users) * 100
        if throughput_improvement > 0:
            print(f"UserScale throughput improvement: +{throughput_improvement:.1f}%")
        else:
            print(f"UserScale throughput deficit: {throughput_improvement:.1f}%")


def main():
    print("\n" + "="*90)
    print("  RESULT ANALYZER")
    print("="*90)
    
    # Ask user for folder path
    print("\nEnter the folder path containing result files:")
    print("(Press Enter to use latest timestamped folder)")
    folder_path = input("Path: ").strip()
    
    if folder_path:
        # Use user-provided path
        print(f"\n📂 Loading results from: {folder_path}\n")
        try:
            with open(f"{folder_path}/hpa_results.json") as f:
                hpa = json.load(f)
        except:
            print("ERROR: HPA results not found in specified folder")
            hpa = None
        
        try:
            with open(f"{folder_path}/userscale_results.json") as f:
                userscale = json.load(f)
        except:
            print("ERROR: UserScale results not found in specified folder")
            userscale = None
    else:
        # Use default load_results function
        hpa, userscale = load_results()
    
    if not hpa and not userscale:
        print("\nERROR: No results found. Run demo.py first.")
        return
    
    print_comparison(hpa, userscale)
    
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
