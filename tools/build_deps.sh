#!/usr/bin/env bash
# Builds the core's two dependencies from source, static and position
# independent, into one prefix: zlib 1.3.1 and HDF5 1.14.6. Packages link
# them into the core so that it cannot meet another HDF5 in the same process
# (an h5py's, a host program's); see tests/two_hdf5_linux.sh.
#
#   bash tools/build_deps.sh PREFIX [DOWNLOAD_DIR]
#
# then configure the core with
#   -DGAMUT_STATIC_HDF5=ON -DHDF5_ROOT=PREFIX -DZLIB_ROOT=PREFIX
#
# Needs cmake 3.20 or later and a C compiler; uses Ninja when present.
# Sources are checked against their published SHA-256 before use.
# licenses/ holds their licence texts, which a new version may change.
set -euo pipefail

prefix=${1:?usage: build_deps.sh PREFIX [DOWNLOAD_DIR]}
downloads=${2:-$prefix/src}
mkdir -p "$prefix" "$downloads"
# Absolute paths; on Windows (Git Bash) in the C:/... form CMake expects.
prefix=$(cd "$prefix" && { pwd -W 2>/dev/null || pwd; })
downloads=$(cd "$downloads" && { pwd -W 2>/dev/null || pwd; })
jobs=${GAMUT_BUILD_JOBS:-2}

generator=()
if command -v ninja > /dev/null 2>&1 && [ "${OS:-}" != "Windows_NT" ]; then
  generator=(-G Ninja)
fi
# On Windows the C runtime is linked statically into everything, so the
# core's DLL needs no Visual C++ redistributable (MATLAB and Julia load it
# too, without Python's copy of the runtime).
runtime=()
if [ "${OS:-}" = "Windows_NT" ]; then
  runtime=(-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded -DCMAKE_POLICY_DEFAULT_CMP0091=NEW)
fi

fetch() {  # url, file, sha256
  local url=$1 file=$downloads/$2 sum=$3
  [ -f "$file" ] || curl -sSfL -o "$file" "$url"
  local have
  if command -v sha256sum > /dev/null 2>&1; then
    have=$(sha256sum "$file" | cut -d' ' -f1)
  else
    have=$(shasum -a 256 "$file" | cut -d' ' -f1)
  fi
  if [ "$have" != "$sum" ]; then
    echo "build_deps: $2 has SHA-256 $have, expected $sum" >&2
    exit 1
  fi
  # Relative names: GNU tar reads "C:/..." as a remote host on Windows.
  (cd "$downloads" && tar -xzf "$2")
}

build() {  # source dir, build dir, cmake arguments...
  local src=$1 bin=$2
  shift 2
  cmake -S "$src" -B "$bin" ${generator[@]+"${generator[@]}"} ${runtime[@]+"${runtime[@]}"} \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_POSITION_INDEPENDENT_CODE=ON "$@"
  cmake --build "$bin" --config Release --parallel "$jobs"
  cmake --install "$bin" --config Release
}

if [ ! -f "$prefix/.zlib-1.3.1" ]; then
  fetch https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz \
        zlib-1.3.1.tar.gz 9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23
  build "$downloads/zlib-1.3.1" "$downloads/zlib-build"
  # zlib 1.3.1 always builds a shared library too; only the static one stays.
  rm -f "$prefix"/lib/libz.so* "$prefix"/lib/libz.*.dylib "$prefix"/lib/libz.dylib \
        "$prefix"/lib/zlib.lib "$prefix"/bin/zlib*.dll
  touch "$prefix/.zlib-1.3.1"
fi
zlib_lib=$prefix/lib/libz.a
[ -f "$zlib_lib" ] || zlib_lib=$prefix/lib/zlibstatic.lib

if [ ! -f "$prefix/.hdf5-1.14.6" ]; then
  fetch https://github.com/HDFGroup/hdf5/releases/download/hdf5_1.14.6/hdf5-1.14.6.tar.gz \
        hdf5-1.14.6.tar.gz e4defbac30f50d64e1556374aa49e574417c9e72c6b1de7a4ff88c4b1bea6e9b
  build "$downloads/hdf5-1.14.6" "$downloads/hdf5-build" \
        -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=OFF -DHDF5_BUILD_TOOLS=OFF \
        -DHDF5_BUILD_EXAMPLES=OFF -DHDF5_BUILD_CPP_LIB=OFF -DHDF5_BUILD_FORTRAN=OFF \
        -DHDF5_BUILD_JAVA=OFF -DHDF5_BUILD_HL_LIB=ON -DHDF5_ENABLE_Z_LIB_SUPPORT=ON \
        -DHDF5_ENABLE_SZIP_SUPPORT=OFF -DZLIB_INCLUDE_DIR="$prefix/include" \
        -DZLIB_LIBRARY="$zlib_lib"
  touch "$prefix/.hdf5-1.14.6"
fi
echo "build_deps: zlib 1.3.1 and HDF5 1.14.6 (static) in $prefix"
