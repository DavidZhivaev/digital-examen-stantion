

set -e

BUILD_TYPE="Release"

INSTALL_PREFIX="/usr/local"

JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

PACKAGE_FORMATS="DEB TGZ"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}


info "Checking dependencies..."

if ! command -v cmake &> /dev/null; then
    error "CMake not found! Please install CMake 3.12 or higher."
    exit 1
fi
CMAKE_VERSION=$(cmake --version | head -n1 | cut -d' ' -f3)
info "CMake version: $CMAKE_VERSION"

if command -v g++ &> /dev/null; then
    COMPILER="g++"
    COMPILER_VERSION=$(g++ --version | head -n1)
    info "Compiler: $COMPILER_VERSION"
elif command -v clang++ &> /dev/null; then
    COMPILER="clang++"
    COMPILER_VERSION=$(clang++ --version | head -n1)
    info "Compiler: $COMPILER_VERSION"
else
    error "No C++ compiler found! Please install g++ or clang++."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    error "Python 3 not found! Please install Python 3."
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
info "Python version: $PYTHON_VERSION"

info "Checking for required libraries..."

check_library() {
    local lib=$1
    local header=$2
    local package=$3

    if ! pkg-config --exists $lib 2>/dev/null && [ ! -f "/usr/include/$header" ] && [ ! -f "/usr/local/include/$header" ]; then
        warning "$lib not found!"
        error "Please install: $package"
        return 1
    fi
    return 0
}

if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    info "Detected distribution: $NAME"
else
    DISTRO="unknown"
    warning "Could not detect Linux distribution"
fi

if ! pkg-config --exists opencv4 && ! pkg-config --exists opencv; then
    warning "OpenCV not found!"
    case $DISTRO in
        ubuntu|debian|astra)
            error "Install with: sudo apt install libopencv-dev"
            ;;
        fedora|rhel|centos|red)
            error "Install with: sudo dnf install opencv-devel"
            ;;
        *)
            error "Please install OpenCV development package"
            ;;
    esac
    exit 1
fi

if [ ! -f "/usr/include/sane/sane.h" ]; then
    warning "SANE development files not found!"
    case $DISTRO in
        ubuntu|debian|astra)
            error "Install with: sudo apt install libsane-dev"
            ;;
        fedora|rhel|centos|red)
            error "Install with: sudo dnf install sane-backends-devel"
            ;;
        *)
            error "Please install SANE development package"
            ;;
    esac
    exit 1
fi

if ! python3 -c "import pybind11" 2>/dev/null; then
    warning "pybind11 not found!"
    info "Installing via pip..."
    pip3 install --user pybind11 || {
        error "Failed to install pybind11"
        error "Try: pip3 install pybind11"
        exit 1
    }
fi

success "All dependencies found!"
echo ""


info "Build configuration:"
info "  Build type: $BUILD_TYPE"
info "  Install prefix: $INSTALL_PREFIX"
info "  Parallel jobs: $JOBS"
echo ""

info "Creating build directory..."
if [ -d "build" ]; then
    warning "Build directory already exists"
    read -p "Remove existing build directory? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf build
        mkdir build
    fi
else
    mkdir build
fi

cd build

info "Configuring CMake..."
cmake .. \
    -DCMAKE_BUILD_TYPE=$BUILD_TYPE \
    -DCMAKE_INSTALL_PREFIX=$INSTALL_PREFIX \
    || {
        error "CMake configuration failed!"
        exit 1
    }

success "CMake configuration completed!"
echo ""

info "Building project with $JOBS parallel jobs..."
info "This may take several minutes..."
echo ""

cmake --build . -j$JOBS || {
    error "Build failed!"
    exit 1
}

success "Build completed successfully!"
echo ""
info "Executable location: build/bin/scanner_module"
echo ""

read -p "Do you want to test the executable? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    info "Running scanner_module --help (if available)..."
    ./bin/scanner_module --help 2>/dev/null || {
        warning "Could not run --help (this might be normal if the app requires a scanner)"
    }
fi

echo ""
read -p "Do you want to install to $INSTALL_PREFIX? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    info "Installing..."

    if [ "$INSTALL_PREFIX" = "/usr/local" ] || [ "$INSTALL_PREFIX" = "/usr" ]; then
        warning "This requires sudo privileges"
        sudo cmake --install . || {
            error "Installation failed!"
            exit 1
        }
    else
        cmake --install . || {
            error "Installation failed!"
            exit 1
        }
    fi

    success "Installation completed!"
    info "Installed to: $INSTALL_PREFIX"

    if [[ ":$PATH:" != *":$INSTALL_PREFIX/bin:"* ]]; then
        warning "$INSTALL_PREFIX/bin is not in PATH"
        info "Add to ~/.bashrc or ~/.zshrc:"
        echo "  export PATH=\"\$PATH:$INSTALL_PREFIX/bin\""
    fi
fi

echo ""
read -p "Do you want to create distribution packages? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    info "Creating packages..."

    for format in $PACKAGE_FORMATS; do
        info "Creating $format package..."

        case $format in
            DEB)
                if ! command -v dpkg-deb &> /dev/null; then
                    warning "dpkg-deb not found, skipping DEB package"
                    continue
                fi
                ;;
            RPM)
                if ! command -v rpmbuild &> /dev/null; then
                    warning "rpmbuild not found, skipping RPM package"
                    info "Install with: sudo apt install rpm (Debian) or sudo dnf install rpm-build (Fedora)"
                    continue
                fi
                ;;
        esac

        cpack -G $format || {
            warning "Failed to create $format package"
            continue
        }
    done

    success "Package(s) created in build directory!"
    ls -lh *.deb *.rpm *.tar.gz 2>/dev/null || true
fi

cd ..

echo ""
echo "========================================"
echo "Build process completed!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Run the application: ./build/bin/scanner_module"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  2. Or run installed version: $INSTALL_PREFIX/bin/scanner_module"
fi
echo ""
success "Done!"
