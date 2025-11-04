#!/bin/bash
# Docker entrypoint script - verifies dependencies at runtime

set -e

echo "=========================================="
echo "  UserScale Container Startup"
echo "=========================================="
echo ""

# Verify Python dependencies (non-GPU)
echo "✓ Checking Python dependencies..."
python3 -c "import fastapi, uvicorn, numpy, requests, psutil, pydantic, kubernetes, httpx, tenacity" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ✅ Core dependencies OK"
else
    echo "  ❌ Core dependencies missing"
    exit 1
fi

# Verify pynvml (can check without GPU)
python3 -c "import pynvml" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ✅ pynvml installed"
else
    echo "  ❌ pynvml missing"
    exit 1
fi

# Verify CuPy is installed (don't import, just check module exists)
python3 -c "import importlib.util; assert importlib.util.find_spec('cupy') is not None" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ✅ CuPy installed"
else
    echo "  ❌ CuPy missing"
    exit 1
fi

# Try to detect GPU (optional, won't fail if not present)
echo ""
echo "✓ Checking GPU availability..."
if command -v nvidia-smi &> /dev/null; then
    if nvidia-smi &> /dev/null; then
        echo "  ✅ GPU detected via nvidia-smi"
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null | head -1 | sed 's/^/     /'
    else
        echo "  ⚠️  nvidia-smi present but no GPU detected"
    fi
else
    echo "  ⚠️  nvidia-smi not available (CPU fallback mode)"
fi

echo ""
echo "✓ Starting application..."
echo "=========================================="
echo ""

# Execute the main command (passed as arguments to this script)
exec "$@"
