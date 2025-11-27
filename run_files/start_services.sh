#!/bin/bash
# Start Services Helper Script
# Ensures HPA and UserScale deployments are scaled and port-forwarded

set -e

NAMESPACE="userscale"

echo "=================================="
echo "  Starting Services"
echo "=================================="
echo ""

# Scale up deployments
echo "Scaling deployments..."
kubectl scale deployment hpa-app -n $NAMESPACE --replicas=1
kubectl scale deployment userscale-app -n $NAMESPACE --replicas=1

# Wait for pods to be ready
echo "⏳ Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=hpa-app -n $NAMESPACE --timeout=60s
kubectl wait --for=condition=ready pod -l app=userscale-app -n $NAMESPACE --timeout=60s

echo "Pods are ready"
echo ""

# Kill existing port forwards
echo "🔄 Cleaning up old port forwards..."
pkill -f "kubectl port-forward" 2>/dev/null || true
sleep 2

# Start port forwarding
echo "🔌 Starting port forwards..."
kubectl port-forward -n $NAMESPACE svc/hpa-app 8002:8000 > /tmp/hpa-pf.log 2>&1 &
sleep 2
kubectl port-forward -n $NAMESPACE svc/userscale-app 8001:8000 > /tmp/userscale-pf.log 2>&1 &
sleep 3

# Test connectivity
echo "Testing connectivity..."
if curl -s http://localhost:8002/healthz > /dev/null; then
    echo "[OK] HPA service ready at http://localhost:8002"
else
    echo "[FAIL] HPA service not responding"
    exit 1
fi

if curl -s http://localhost:8001/healthz > /dev/null; then
    echo "[OK] UserScale service ready at http://localhost:8001"
else
    echo "[FAIL] UserScale service not responding"
    exit 1
fi

echo ""
echo "[OK] All services ready!"
echo ""
echo "You can now run:"
echo "  python3 run_files/demo.py"
