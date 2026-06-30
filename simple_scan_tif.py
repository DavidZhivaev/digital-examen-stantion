#!/usr/bin/env python3
"""
Simple scanner script - scan sheets from ADF and save as TIF images.
No GUI, no ML model, just scan and save individual TIF files.

Usage:
    python3 simple_scan_tif.py
"""

import os
import sys
from datetime import datetime

# Import scanner module
try:
    import scanner_hal
except ImportError:
    print("[ERROR] scanner_hal.so not found!")
    print("Build it first: cd scanner_module && sh build_pybind.sh")
    sys.exit(1)

from PIL import Image
import numpy as np


def main():
    output_dir = "./output_tif"
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 50)
    print("Simple Scanner - Scan to TIF")
    print("=" * 50)
    print()

    # Create scanner instance
    scanner = scanner_hal.Scanner()

    # List available scanners
    print("[INFO] Searching for scanners...")
    devices = scanner.list_scanners()

    if not devices:
        print("[ERROR] No scanners found!")
        return 1

    print(f"[OK] Found {len(devices)} scanner(s):")
    for i, dev in enumerate(devices):
        print(f"  {i + 1}. {dev}")
    print()

    # Select scanner
    if len(devices) == 1:
        device_id = devices[0]
        print(f"[INFO] Using: {device_id}")
    else:
        try:
            choice = int(input("Select scanner (number): ")) - 1
            device_id = devices[choice]
        except (ValueError, IndexError):
            print("[ERROR] Invalid selection")
            return 1

    # Connect
    print(f"[INFO] Connecting to {device_id}...")
    if not scanner.connect(device_id):
        print("[ERROR] Failed to connect!")
        return 1
    print("[OK] Connected")
    print()

    # Scan batch
    print("[INFO] Scanning... (insert pages into ADF)")
    print("[INFO] Waiting for pages...")

    try:
        arrays = scanner.scan_batch()
    except Exception as e:
        print(f"[ERROR] Scan failed: {e}")
        scanner.disconnect()
        return 1

    if not arrays:
        print("[WARNING] No pages scanned!")
        scanner.disconnect()
        return 0

    print(f"[OK] Scanned {len(arrays)} page(s)")
    print()

    # Disconnect scanner
    scanner.disconnect()
    print("[OK] Scanner disconnected")
    print()

    # Generate timestamp for filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save each image as TIF
    print("[INFO] Saving TIF images...")
    saved_files = []

    for i, arr in enumerate(arrays):
        # Convert numpy array to PIL Image
        img = Image.fromarray(arr)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Generate filename
        tif_filename = f"scan_{timestamp}_page_{i+1:04d}.tif"
        tif_path = os.path.join(output_dir, tif_filename)

        # Save as TIF (uncompressed)
        img.save(tif_path, "TIFF", compression="none", dpi=(100, 100))

        print(f"  Page {i + 1}: {tif_filename} ({img.size[0]}x{img.size[1]})")
        saved_files.append(tif_path)

    print()
    print("=" * 50)
    print(f"Done! Saved {len(saved_files)} TIF file(s) to {output_dir}/")
    print("=" * 50)
    print()
    print("Files:")
    for f in saved_files:
        print(f"  {f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
