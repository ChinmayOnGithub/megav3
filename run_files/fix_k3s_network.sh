#!/bin/bash
# Fix k3s after network change
# This script removes cached IP addresses and restarts k3s

echo "=========================================="
echo "  K3S Network Fix Script"
echo "=========================================="
echo ""

# Stop k3s
echo "[1/7] Stopping k3s..."
sudo systemctl stop k3s
sleep 3

# Remove k3s config with old IP
echo "[2/7] Removing cached k3s config..."
sudo rm -f /etc/rancher/k3s/k3s.yaml
sudo rm -f ~/.kube/config

# Clean up network interfaces
echo "[3/7] Cleaning up stale network interfaces..."
sudo ip link delete cni0 2>/dev/null || true
sudo ip link delete flannel.1 2>/dev/null || true

# Start k3s with proper permissions
echo "[4/7] Starting k3s with write permissions..."
sudo systemctl start k3s

# Wait for k3s to be fully ready
echo "[5/7] Waiting for k3s to initialize..."
for i in {1..60}; do
    if sudo test -f /etc/rancher/k3s/k3s.yaml; then
        echo "  Config file generated after ${i} seconds"
        break
    fi
    sleep 1
done

# Additional wait for k3s to be fully ready
sleep 10

# Fix permissions on k3s config
echo "[6/7] Fixing k3s config permissions..."
sudo chmod 644 /etc/rancher/k3s/k3s.yaml

# Copy new config
echo "[7/7] Setting up kubectl config..."
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
chmod 600 ~/.kube/config

# Set KUBECONFIG environment variable
export KUBECONFIG=~/.kube/config

echo ""
echo "=========================================="
echo "  Testing Connection"
echo "=========================================="
echo ""

# Wait a bit more
sleep 5

# Test connection
if kubectl get nodes 2>/dev/null; then
    echo ""
    echo "[OK] k3s is working with new network!"
    echo ""
    echo "Next steps:"
    echo "  python3 run_files/setup.py --skip-deps"
else
    echo ""
    echo "[WARNING] kubectl test failed, checking k3s status..."
    echo ""
    
    # Check k3s status
    if sudo systemctl is-active --quiet k3s; then
        echo "[OK] k3s service is running"
        echo ""
        echo "Checking if config file exists..."
        if sudo test -f /etc/rancher/k3s/k3s.yaml; then
            echo "[OK] Config file exists"
            echo ""
            echo "Try running these commands manually:"
            echo "  export KUBECONFIG=~/.kube/config"
            echo "  kubectl get nodes"
        else
            echo "[ERROR] Config file not generated"
            echo ""
            echo "Check k3s logs:"
            echo "  sudo journalctl -u k3s -n 50 --no-pager"
        fi
    else
        echo "[ERROR] k3s service is not running"
        echo ""
        echo "Check status:"
        echo "  sudo systemctl status k3s"
        echo "  sudo journalctl -u k3s -n 50 --no-pager"
    fi
fi
