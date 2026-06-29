#!/bin/bash
# build_all.sh - Build all C++ modules for Scanner Station
set -e

echo "========================================"
echo "Scanner Station - Build All Modules"
echo "========================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check dependencies first
echo "[1/4] Checking dependencies..."

if ! command -v cmake &> /dev/null; then
    echo "[ERROR] CMake not found!"
    echo "Run: sudo ./install_linux_deps.sh"
    exit 1
fi

if ! command -v g++ &> /dev/null && ! command -v clang++ &> /dev/null; then
    echo "[ERROR] No C++ compiler found!"
    echo "Run: sudo ./install_linux_deps.sh"
    exit 1
fi

if ! python3 -c "import pybind11" 2>/dev/null; then
    echo "[ERROR] pybind11 not found!"
    echo "Run: pip3 install pybind11"
    exit 1
fi

echo "[OK] All dependencies found"
echo ""

# Build scanner_module
echo "[2/4] Building scanner_module..."
cd scanner_module
chmod +x build_pybind.sh
./build_pybind.sh
cd ..
echo ""

# Check if scanner_hal was built
if [ -f "scanner_hal.cpython"*".so" ] || [ -f "scanner_hal.so" ]; then
    echo "[OK] scanner_hal.so built successfully"
else
    echo "[WARNING] scanner_hal.so not found in project root"
fi
echo ""

# Build output_module
echo "[3/4] Building output_module..."
cd output_module
chmod +x build.sh
./build.sh
cd ..
echo ""

# Check if output_generator_cpp was built
if [ -f "output_generator_cpp.cpython"*".so" ] || [ -f "output_generator_cpp.so" ]; then
    echo "[OK] output_generator_cpp.so built successfully"
else
    echo "[WARNING] output_generator_cpp.so not found (Python bindings may not have built)"
fi
echo ""

# Install Python dependencies
echo "[4/4] Installing Python dependencies..."
pip3 install -r requirements-linux.txt --quiet 2>/dev/null || pip3 install -r requirements.txt --quiet
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet

echo ""
echo "========================================"
echo "Build Complete!"
echo "========================================"
echo ""
echo "Modules built:"
ls -la *.so 2>/dev/null || echo "  (no .so files in root)"
echo ""
echo "To run the application:"
echo "  python3 main.py"
echo ""
