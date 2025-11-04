#!/bin/bash
# Install NVIDIA Container Toolkit for Docker GPU support

echo "=================================="
echo "Installing NVIDIA Container Toolkit"
echo "=================================="

# Add NVIDIA package repositories
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Update package list
sudo apt-get update

# Install NVIDIA Container Toolkit
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker

# Restart Docker
sudo systemctl restart docker

echo ""
echo "✅ Installation complete!"
echo ""
echo "Testing Docker GPU support..."
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi

echo ""
echo "If you see GPU info above, Docker GPU support is working!"
