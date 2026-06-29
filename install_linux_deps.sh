#!/bin/bash
# install_linux_deps.sh
# Installs all dependencies for building scanner_module and output_module on Linux
# Run: chmod +x install_linux_deps.sh && sudo ./install_linux_deps.sh

set -e

echo "========================================"
echo "Scanner Station - Linux Dependency Installer"
echo "========================================"
echo ""

# Detect distro
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    VERSION=$VERSION_ID
else
    DISTRO="unknown"
fi

echo "[INFO] Detected: $DISTRO $VERSION"
echo ""

# ============================================
# Install based on distro
# ============================================

install_debian_ubuntu() {
    echo "[1/5] Updating package lists..."
    apt-get update

    echo ""
    echo "[2/5] Installing build essentials..."
    apt-get install -y \
        build-essential \
        cmake \
        git \
        pkg-config

    echo ""
    echo "[3/5] Installing Python development files..."
    apt-get install -y \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv

    echo ""
    echo "[4/5] Installing OpenCV..."
    apt-get install -y \
        libopencv-dev \
        python3-opencv

    echo ""
    echo "[5/5] Installing SANE (scanner library)..."
    apt-get install -y \
        libsane-dev \
        sane-utils
}

install_fedora_rhel() {
    echo "[1/5] Updating package lists..."
    dnf check-update || true

    echo ""
    echo "[2/5] Installing build essentials..."
    dnf install -y \
        gcc \
        gcc-c++ \
        cmake \
        make \
        git \
        pkgconfig

    echo ""
    echo "[3/5] Installing Python development files..."
    dnf install -y \
        python3 \
        python3-devel \
        python3-pip

    echo ""
    echo "[4/5] Installing OpenCV..."
    dnf install -y \
        opencv \
        opencv-devel

    echo ""
    echo "[5/5] Installing SANE (scanner library)..."
    dnf install -y \
        sane-backends \
        sane-backends-devel
}

install_arch() {
    echo "[1/5] Updating package lists..."
    pacman -Sy

    echo ""
    echo "[2/5] Installing build essentials..."
    pacman -S --noconfirm \
        base-devel \
        cmake \
        git

    echo ""
    echo "[3/5] Installing Python development files..."
    pacman -S --noconfirm \
        python \
        python-pip

    echo ""
    echo "[4/5] Installing OpenCV..."
    pacman -S --noconfirm \
        opencv \
        python-opencv

    echo ""
    echo "[5/5] Installing SANE (scanner library)..."
    pacman -S --noconfirm \
        sane
}

# Run appropriate installer
case $DISTRO in
    ubuntu|debian|linuxmint|pop)
        install_debian_ubuntu
        ;;
    fedora|rhel|centos|rocky|almalinux|redos)
        install_fedora_rhel
        ;;
    arch|manjaro|endeavouros)
        install_arch
        ;;
    *)
        echo "[WARNING] Unknown distro: $DISTRO"
        echo "Please install manually:"
        echo "  - build-essential / gcc / g++"
        echo "  - cmake"
        echo "  - python3-dev"
        echo "  - libopencv-dev"
        echo "  - libsane-dev"
        exit 1
        ;;
esac

echo ""
echo "========================================"
echo "Installing Python packages..."
echo "========================================"
echo ""

# Install Python packages (as current user, not root)
if [ "$SUDO_USER" ]; then
    sudo -u $SUDO_USER pip3 install --user pybind11 numpy pillow
else
    pip3 install --user pybind11 numpy pillow
fi

echo ""
echo "========================================"
echo "Verifying installations..."
echo "========================================"
echo ""

# Verify installations
check_installed() {
    if command -v $1 &> /dev/null; then
        echo "[OK] $1: $($1 --version 2>&1 | head -n1)"
    else
        echo "[MISSING] $1"
    fi
}

check_installed cmake
check_installed g++
check_installed python3

# Check OpenCV
if pkg-config --exists opencv4 2>/dev/null; then
    echo "[OK] OpenCV: $(pkg-config --modversion opencv4)"
elif pkg-config --exists opencv 2>/dev/null; then
    echo "[OK] OpenCV: $(pkg-config --modversion opencv)"
else
    echo "[MISSING] OpenCV"
fi

# Check SANE
if pkg-config --exists sane-backends 2>/dev/null; then
    echo "[OK] SANE: $(pkg-config --modversion sane-backends)"
elif [ -f /usr/include/sane/sane.h ]; then
    echo "[OK] SANE: headers found"
else
    echo "[MISSING] SANE"
fi

# Check pybind11
if python3 -c "import pybind11; print(f'[OK] pybind11: {pybind11.__version__}')" 2>/dev/null; then
    :
else
    echo "[MISSING] pybind11"
fi

echo ""
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. cd scanner_module && ./build_linux.sh"
echo "  2. cd output_module && ./build_linux.sh"
echo "  3. python3 main.py"
echo ""
