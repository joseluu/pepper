#!/bin/bash
#
# Build script for _qi.so Python 3 module for NAOqi 2.7
#
# Prerequisites:
#   - 32-bit build environment (one of the following):
#     a) Native 32-bit Linux system
#     b) Docker with i386 image
#     c) x86_64 with multilib: sudo apt-get install gcc-multilib g++-multilib libc6-dev-i386
#   - Python 3.5 development headers (32-bit)
#
# The build_env directory should contain:
#   - Python-3.5.10/Include/ (from python.org source tarball)
#   - boost_1_59_0/ (from boost.org)
#
# The opn_work/mnt directory should be the mounted NAOqi 2.7 filesystem
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build_env"
NAOQI_ROOT="${SCRIPT_DIR}/opn_work/mnt"

# Paths
PYTHON_INCLUDE="${BUILD_DIR}/Python-3.5.10/Include"
BOOST_INCLUDE="${BUILD_DIR}/boost_1_59_0"
QI_INCLUDE="${NAOQI_ROOT}/opt/aldebaran/include"
QI_LIB="${NAOQI_ROOT}/opt/aldebaran/lib"
BOOST_LIB="${NAOQI_ROOT}/usr/lib"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "================================================"
echo " _qi.so Python 3 Build Script for NAOqi 2.7"
echo "================================================"
echo ""

# Check prerequisites
check_prereqs() {
    local errors=0

    if [ ! -d "$PYTHON_INCLUDE" ]; then
        echo -e "${RED}ERROR: Python 3.5 headers not found at ${PYTHON_INCLUDE}${NC}"
        echo "  Download from: https://www.python.org/ftp/python/3.5.10/Python-3.5.10.tgz"
        errors=$((errors + 1))
    fi

    if [ ! -d "$BOOST_INCLUDE" ]; then
        echo -e "${RED}ERROR: Boost 1.59 headers not found at ${BOOST_INCLUDE}${NC}"
        echo "  Download from: https://archives.boost.io/release/1.59.0/source/boost_1_59_0.tar.gz"
        errors=$((errors + 1))
    fi

    if [ ! -f "${QI_LIB}/libqipython3.so" ]; then
        echo -e "${RED}ERROR: libqipython3.so not found in ${QI_LIB}${NC}"
        echo "  Mount NAOqi 2.7 filesystem at ${NAOQI_ROOT}"
        errors=$((errors + 1))
    fi

    if [ ! -f "${SCRIPT_DIR}/_qi_py3.cpp" ]; then
        echo -e "${RED}ERROR: _qi_py3.cpp source not found${NC}"
        errors=$((errors + 1))
    fi

    return $errors
}

# Detect build environment
detect_env() {
    ARCH=$(uname -m)
    CFLAGS=""
    LDFLAGS=""

    if [ "$ARCH" = "i686" ] || [ "$ARCH" = "i386" ]; then
        echo -e "${GREEN}Native 32-bit system detected${NC}"
        return 0
    fi

    if [ "$ARCH" = "x86_64" ]; then
        echo -e "${YELLOW}64-bit system detected, checking for 32-bit support...${NC}"

        # Check for multilib
        if gcc -m32 -E - < /dev/null > /dev/null 2>&1; then
            # Check for 32-bit libc headers
            if [ -f /usr/include/i386-linux-gnu/bits/libc-header-start.h ] || \
               [ -f /usr/include/x86_64-linux-gnu/32/bits/libc-header-start.h ]; then
                echo -e "${GREEN}32-bit multilib support available${NC}"
                CFLAGS="-m32"
                LDFLAGS="-m32"
                return 0
            else
                echo -e "${RED}32-bit libc headers not found${NC}"
                echo "  Install with: sudo apt-get install libc6-dev-i386"
                return 1
            fi
        else
            echo -e "${RED}32-bit compilation not supported${NC}"
            echo "  Install with: sudo apt-get install gcc-multilib g++-multilib libc6-dev-i386"
            return 1
        fi
    fi

    echo -e "${RED}Unsupported architecture: $ARCH${NC}"
    return 1
}

# Build the module
build_module() {
    echo ""
    echo "Build configuration:"
    echo "  Python headers: ${PYTHON_INCLUDE}"
    echo "  Boost headers:  ${BOOST_INCLUDE}"
    echo "  QI headers:     ${QI_INCLUDE}"
    echo "  QI libs:        ${QI_LIB}"
    echo "  CFLAGS:         ${CFLAGS}"
    echo ""

    # Compile
    echo "Compiling..."
    g++ ${CFLAGS} -shared -fPIC \
        -I "${PYTHON_INCLUDE}" \
        -I "${BOOST_INCLUDE}" \
        -I "${QI_INCLUDE}" \
        -std=c++11 \
        -w \
        -c "${SCRIPT_DIR}/_qi_py3.cpp" -o "${BUILD_DIR}/_qi_32.o"

    echo -e "${GREEN}Compilation successful!${NC}"

    # Link
    echo ""
    echo "Linking..."
    g++ ${LDFLAGS} -shared -fPIC \
        "${BUILD_DIR}/_qi_32.o" \
        -L "${QI_LIB}" -lqipython3 \
        -L "${BOOST_LIB}" -lboost_python3 \
        -Wl,-rpath,/opt/aldebaran/lib \
        -Wl,-rpath,/usr/lib \
        -Wl,--no-as-needed \
        -o "${BUILD_DIR}/_qi.so"

    echo -e "${GREEN}Linking successful!${NC}"
    echo ""
    echo "Output: ${BUILD_DIR}/_qi.so"
    file "${BUILD_DIR}/_qi.so"
}

# Print installation instructions
print_install_instructions() {
    echo ""
    echo "================================================"
    echo " Installation Instructions"
    echo "================================================"
    echo ""
    echo "1. Install Python 3.5 on robot:"
    echo "   ssh nao@<robot_ip>"
    echo "   sudo su -"
    echo "   # If package manager available:"
    echo "   apt-get install python3.5"
    echo ""
    echo "2. Copy _qi.so to robot:"
    echo "   scp ${BUILD_DIR}/_qi.so nao@<robot_ip>:/tmp/"
    echo ""
    echo "3. Install on robot:"
    echo "   ssh nao@<robot_ip>"
    echo "   sudo su -"
    echo "   mkdir -p /usr/lib/python3.5/site-packages"
    echo "   cp /tmp/_qi.so /usr/lib/python3.5/site-packages/"
    echo "   cp -r /opt/aldebaran/lib/python2.7/site-packages/qi \\"
    echo "         /usr/lib/python3.5/site-packages/"
    echo ""
    echo "4. Test:"
    echo "   python3.5 -c 'import qi; print(qi.Session)'"
    echo ""
}

# Main
main() {
    if ! check_prereqs; then
        echo ""
        echo -e "${RED}Prerequisites check failed. Please fix the above errors.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Prerequisites OK${NC}"

    if ! detect_env; then
        echo ""
        echo -e "${RED}Build environment not suitable.${NC}"
        echo ""
        echo "Alternative: Use Docker"
        echo "  docker run -it --rm -v \$(pwd):/build i386/debian:stretch bash"
        echo "  # Then inside container:"
        echo "  apt-get update && apt-get install -y g++ python3.5-dev"
        echo "  cd /build && ./build_qi_py3.sh"
        exit 1
    fi

    build_module
    print_install_instructions
}

main "$@"
