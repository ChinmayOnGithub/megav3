#!/usr/bin/env python3
"""
Watch pod scaling in real-time
"""

import subprocess
import time
import json

NAMESPACE = "userscale"

def get_pods(label):
    """Get pod count for a label selector"""
    try:
        cmd = f"kubectl get pods -n {NAMESPACE} -l {label} --field-selector=status.phase=Running -o json"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        data = json.loads(result.stdout)
        return len(data.get("items", []))
    except:
        return 0

def main():
    print("\n" + "="*60)
    print("  POD SCALING MONITOR")
    print("="*60 + "\n")
    print(f"{'Time':<12} {'HPA Pods':<15} {'UserScale Pods':<15}")
    print("-" * 60)
    
    try:
        while True:
            hpa_pods = get_pods("app=hpa-app,scaler=hpa")
            userscale_pods = get_pods("app=userscale-app,scaler=userscale")
            
            timestamp = time.strftime("%H:%M:%S")
            print(f"{timestamp:<12} {hpa_pods:<15} {userscale_pods:<15}", flush=True)
            
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")

if __name__ == "__main__":
    main()
