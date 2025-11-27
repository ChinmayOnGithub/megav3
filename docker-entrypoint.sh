#!/bin/bash
# Safe entrypoint — GPU optional, no hard failures

set -e

echo "=========================================="
echo "  UserScale Container Startup"
echo "=========================================="
echo ""

echo "✓ Checking core Python dependencies..."
python3 - << 'EOF'
import fastapi, uvicorn, numpy, requests, psutil, pydantic, kubernetes, httpx, tenacity
EOF

echo "  [OK] Core dependencies OK"

echo ""
echo "✓ Checking pynvml..."
python3 - << 'EOF'
import pynvml
try:
    pynvml.nvmlInit()
    print("  [OK] pynvml initialized")
    h = pynvml.nvmlDeviceGetHandleByIndex(0)
    name = pynvml.nvmlDeviceGetName(h).decode()
    print(f"     GPU: {name}")
except Exception as e:
    print(f"  [WARNING] pynvml present but GPU not accessible: {e}")
EOF

echo ""
echo "✓ Checking CuPy..."
python3 - << 'EOF'
try:
    import cupy as cp
    a = cp.zeros((1,))
    cp.cuda.Stream.null.synchronize()
    print("  [OK] CuPy loaded and CUDA context OK")
except ImportError:
    print("  [ERROR] CuPy not installed (should not happen)")
    exit(1)
except Exception as e:
    print(f"  [WARNING] CuPy installed but GPU not usable: {e}")
EOF

echo ""
echo "✓ Checking nvidia-smi..."
if command -v nvidia-smi &>/dev/null; then
    if nvidia-smi &>/dev/null; then
        echo "  [OK] GPU detected via nvidia-smi"
        nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/     /'
    else
        echo "  [WARNING] nvidia-smi found but no GPU visible"
    fi
else
    echo "  [WARNING] nvidia-smi not available (Docker time-slicing mode)"
fi

echo ""
echo "✓ Starting application..."
echo "=========================================="
echo ""

exec "$@"
