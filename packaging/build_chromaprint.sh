#!/bin/bash
# Builds libchromaprint for the Intel app from a pinned, checksummed
# source and installs it where packaging/bundle_info.py stages it from:
#
#     packaging/build_chromaprint.sh [PREFIX]    # PREFIX defaults to /usr/local
#
# The library lands in PREFIX/lib, where bundle_info.chromaprint_binaries
# stages it from when the build runs with SEEKER_CHROMAPRINT_DIR set to
# that folder (unset, it reads /usr/local/lib). A Mac with no
# /usr/local/lib names a folder of the repository, which needs no sudo
# (the folder must be one `git status` ignores, and not build/, which
# PyInstaller's --clean empties):
#
#     packaging/build_chromaprint.sh "$PWD/<prefix>"
#     SEEKER_CHROMAPRINT_DIR="$PWD/<prefix>/lib" <the Intel build>
#
# Homebrew has stopped building bottles for Intel Macs
# (docs.brew.sh/Support-Tiers: "Homebrew has stopped building new
# bottles for Intel systems"; its API lists none for chromaprint 1.6.2,
# ffmpeg or mpg123), so `brew install chromaprint` there compiles
# ffmpeg and ten more formulae. The library needs none of them: built
# without FFmpeg it links Accelerate, libc++ and libSystem alone
# (`otool -L` of Homebrew's arm64 copy, 2026-11-03), and the audio
# conversion comes from the copy of avresample inside the source.
#
# Needs cmake, a compiler, curl and shasum (every macOS runner has them).
# Creates PREFIX/lib itself and runs the install through sudo only when
# the current user cannot, so a PREFIX inside the repository needs none.
set -euo pipefail

VERSION=1.6.2
SHA256=d54ada62c16b2db396d3251ec54fc7a58909c163131a1cfcf7fa6407dbc14360
# bundle_info.MINIMUM_SYSTEM_VERSION: bundle_check.py fails a binary
# above it (tests/test_build_chromaprint.py compares the two).
DEPLOYMENT_TARGET=15.0

# Reads `otool -L` output on stdin and fails on a dependency outside
# macOS's own folders: such a library loads on the machine that built it
# and not on a user's Mac, so a smoke test run there cannot see it.
only_system_dependencies() {
    # Line 1 names the file, line 2 is the library's own install name.
    local outside
    outside=$(tail -n +3 | awk '{print $1}' \
        | grep -vE '^(/usr/lib/|/System/Library/)' || true)
    if [ -n "$outside" ]; then
        echo "libchromaprint links libraries outside macOS:" >&2
        echo "$outside" >&2
        return 1
    fi
}

# Installs the finished build in $1 under the prefix $2, through sudo
# only when the current user can neither create nor write the prefix's
# lib/. A prefix that does not exist yet (a folder in the repository)
# is not unwritable, so it is created before it is asked about;
# `[ -w ]` alone says no to a folder that is not there.
install_library() {
    local build=$1 prefix=$2
    if mkdir -p "$prefix/lib" 2>/dev/null && [ -w "$prefix/lib" ]; then
        cmake --install "$build"
    else
        sudo cmake --install "$build"
    fi
}

main() {
    local prefix=${1:-/usr/local}
    local archive="$WORK/chromaprint-$VERSION.tar.gz"
    local source="$WORK/chromaprint-$VERSION"
    local library="$prefix/lib/libchromaprint.1.dylib"

    curl --fail --silent --show-error --location --output "$archive" \
        "https://github.com/acoustid/chromaprint/releases/download/v$VERSION/chromaprint-$VERSION.tar.gz"
    echo "$SHA256  $archive" | shasum -a 256 -c -
    tar -xzf "$archive" -C "$WORK"

    cmake -S "$source" -B "$WORK/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=ON \
        -DBUILD_TOOLS=OFF \
        -DBUILD_TESTS=OFF \
        -DFFT_LIB=vdsp \
        -DCMAKE_OSX_ARCHITECTURES=x86_64 \
        -DCMAKE_OSX_DEPLOYMENT_TARGET="$DEPLOYMENT_TARGET" \
        -DCMAKE_INSTALL_PREFIX="$prefix"
    cmake --build "$WORK/build"
    install_library "$WORK/build" "$prefix"

    lipo -archs "$library"
    otool -L "$library"
    otool -L "$library" | only_system_dependencies
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    WORK=$(mktemp -d)
    trap 'rm -rf "$WORK"' EXIT
    main "$@"
fi
