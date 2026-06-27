#!/bin/bash
set -e

BUILD_DIR="build"
CONFIG="Release"

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

cmake -DCMAKE_BUILD_TYPE="$CONFIG" ..
cmake --build . --config "$CONFIG" -j$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

find . -name "output_generator_cpp*.so" -o -name "output_generator_cpp*.dylib" | while read f; do
    cp "$f" ../../
    echo "Copied $(basename "$f") to project root"
done

echo "Build completed successfully"
