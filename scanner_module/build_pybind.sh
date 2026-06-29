#!/bin/bash
# Quick build script for scanner_hal Python module on Linux
set -e

echo "========================================"
echo "Building scanner_hal Python module"
echo "========================================"
echo ""

# Get pybind11 cmake directory
PYBIND11_DIR=$(python3 -m pybind11 --cmakedir 2>/dev/null || echo "")
if [ -z "$PYBIND11_DIR" ]; then
    echo "[ERROR] pybind11 not found!"
    echo "Install with: pip3 install pybind11"
    exit 1
fi
echo "[INFO] pybind11_DIR: $PYBIND11_DIR"

# Create build directory
mkdir -p build
cd build

echo "[INFO] Configuring CMake..."
cmake -DBUILD_PYTHON_MODULE=ON \
      -Dpybind11_DIR="$PYBIND11_DIR" \
      -DCMAKE_BUILD_TYPE=Release \
      ..

if [ $? -ne 0 ]; then
    echo "[ERROR] CMake configuration failed!"
    cd ..
    exit 1
fi

echo ""
echo "[INFO] Building..."
cmake --build . --config Release -j$(nproc)

if [ $? -ne 0 ]; then
    echo "[ERROR] Build failed!"
    cd ..
    exit 1
fi

echo ""
echo "[INFO] Copying scanner_hal.so to project root..."
find . -name "scanner_hal*.so" -exec cp {} ../../ \;

cd ..

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
