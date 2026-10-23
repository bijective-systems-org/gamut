#!/usr/bin/env bash
# Builds the core as a release carries it: HDF5 and zlib linked in (built by
# tools/build_deps.sh into DEPS), installed into PREFIX with its headers, its
# CMake package (find_package(gamut) gives gamut::gamut), its licence and, from
# licenses/, those of the libraries linked into it.
#
#   bash tools/build_core.sh PREFIX DEPS
#
# The release builds the Linux core in the manylinux_2_28 image, as the Linux
# wheel is built, so that it loads on glibc 2.28 and later.
set -euo pipefail

prefix=${1:?usage: build_core.sh PREFIX DEPS}
deps=${2:?usage: build_core.sh PREFIX DEPS}
top=$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })
bash "$top/tools/build_deps.sh" "$deps"
mkdir -p "$prefix"
# Absolute paths; on Windows (Git Bash) in the C:/... form CMake expects.
prefix=$(cd "$prefix" && { pwd -W 2>/dev/null || pwd; })
deps=$(cd "$deps" && { pwd -W 2>/dev/null || pwd; })

build=$deps/src/gamut-build
cmake -S "$top" -B "$build" -DCMAKE_BUILD_TYPE=Release -DGAMUT_BUILD_TESTS=OFF \
      -DGAMUT_STATIC_HDF5=ON -DHDF5_ROOT="$deps" -DZLIB_ROOT="$deps" -DCMAKE_INSTALL_LIBDIR=lib
cmake --build "$build" --config Release --parallel "${GAMUT_BUILD_JOBS:-2}"
cmake --install "$build" --config Release --prefix "$prefix"

cp "$top/LICENSE" "$prefix/"
cp -R "$top/licenses" "$prefix/"
echo "build_core: the core, its headers, CMake package and licences in $prefix"
