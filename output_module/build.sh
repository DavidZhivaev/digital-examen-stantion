#!/bin/bash
# Build script for output_module (PDF/ZIP generator)
set -e

echo "========================================"
echo "Building output_module"
echo "========================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
BUILD_TYPE="${1:-Release}"

# Get pybind11 cmake directory for Python bindings
PYBIND11_DIR=$(python3 -m pybind11 --cmakedir 2>/dev/null || echo "")
if [ -z "$PYBIND11_DIR" ]; then
    echo "[WARNING] pybind11 not found - Python bindings will not be built"
    echo "Install with: pip3 install pybind11"
else
    echo "[INFO] pybind11_DIR: $PYBIND11_DIR"
fi

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "[INFO] Configuring CMake..."
if [ -n "$PYBIND11_DIR" ]; then
    cmake \
        -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
        -Dpybind11_DIR="$PYBIND11_DIR" \
        ..
else
    cmake \
        -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
        ..
fi

echo ""
echo "[INFO] Building..."
cmake --build . --parallel "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

if [ -f compile_commands.json ]; then
    cp compile_commands.json ..
fi

# Copy Python module to project root if built
if ls output_generator_cpp*.so 1> /dev/null 2>&1; then
    echo "[INFO] Copying output_generator_cpp.so to project root..."
    cp output_generator_cpp*.so ../../
fi

echo ""
echo "========================================"
echo "Build complete!"
echo "Binaries in ${BUILD_DIR}"
echo "========================================"
