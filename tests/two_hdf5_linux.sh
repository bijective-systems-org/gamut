#!/usr/bin/env bash
# Whether the core works beside another HDF5 in one Linux process, where
# shared libraries share one symbol namespace. HDF5 1.14.6 is built from
# source, shared and static, and the core twice: linked to the shared
# HDF5, and with HDF5 linked in (MESTRA_STATIC_HDF5, only mes_* exported).
# Each runs the Python suite with h5py's own HDF5 loaded, and with a foreign
# HDF5 preloaded into the global namespace, as a host program such as
# MATLAB holds one: h5py's (2.x) and the system's (1.10).
#
#   WORK=/tmp/two-hdf5 PYTHON=python3 bash tests/two_hdf5_linux.sh
#
# Needs cmake, ninja, a C++17 compiler, the system HDF5 (libhdf5-dev),
# zlib, curl, and numpy, h5py, pytest, pint, xarray, netCDF4 for PYTHON.
# Writes WORK/report.md; exit status 0 when the static build passes every
# case (the shared build's results are recorded, not required).
set -uo pipefail
core=$(cd "$(dirname "$0")/.." && pwd)
work=${WORK:-$PWD/two-hdf5}
py=${PYTHON:-python3}
mkdir -p "$work"
report="$work/report.md"
{
  echo "# The core beside another HDF5 (Linux)"
  echo
  echo "| case | result |"
  echo "|---|---|"
} > "$report"
row() { echo "| $1 | $2 |" >> "$report"; }

h5py_version=$($py -c 'import h5py; print(h5py.version.hdf5_version)')
h5py_lib=$($py - <<'PY'
import glob, os, h5py
here = os.path.dirname(h5py.__file__)
found = sorted(glob.glob(os.path.join(here, "..", "h5py.libs", "libhdf5-*.so*")) +
               glob.glob(os.path.join(here, ".dylibs", "libhdf5*.so*")))
print(os.path.realpath(found[0]) if found else "")
PY
)
system_lib=$(ls /usr/lib/*/libhdf5_serial.so.[0-9]* /usr/lib/*/hdf5/serial/libhdf5.so.[0-9]* \
             2>/dev/null | head -1)
system_version=$(dpkg-query -W -f '${Version}' 'libhdf5-[0-9]*' 2>/dev/null | head -c 40)
row "h5py's HDF5" "$h5py_version, \`$(basename "$h5py_lib")\`"
row "system HDF5" "$system_version, \`$(basename "$system_lib")\`"

# The system's HDF5 is older than the core needs: refused at configure.
if cmake -S "$core" -B "$work/system" -G Ninja -DMESTRA_BUILD_TESTS=OFF \
     > "$work/system-configure.log" 2>&1; then
  row "core against the system HDF5" "configured"
else
  row "core against the system HDF5" "refused at configure: $(grep -m1 -o 'needs HDF5 1.12 or later; found [0-9.]*' "$work/system-configure.log")"
fi

# HDF5 1.14.6 from source, built twice: static and position independent
# (for MESTRA_STATIC_HDF5), and shared (the baseline).
tarball="$work/hdf5-1.14.6.tar.gz"
if [ ! -d "$work/hdf5-static" ]; then
  curl -sSfL -o "$tarball" \
    https://github.com/HDFGroup/hdf5/releases/download/hdf5_1.14.6/hdf5-1.14.6.tar.gz &&
  row "HDF5 source" "1.14.6, sha256 $(sha256sum "$tarball" | cut -d' ' -f1)" &&
  tar -xzf "$tarball" -C "$work" || row "HDF5 source" "FAIL"
  for kind in static shared; do
    if [ $kind = static ]; then libs="-DBUILD_SHARED_LIBS=OFF"; else libs="-DBUILD_SHARED_LIBS=ON -DBUILD_STATIC_LIBS=OFF"; fi
    cmake -S "$work/hdf5-1.14.6" -B "$work/hdf5-build-$kind" -G Ninja -DCMAKE_BUILD_TYPE=Release \
          $libs -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_TESTING=OFF \
          -DHDF5_BUILD_TOOLS=OFF -DHDF5_BUILD_EXAMPLES=OFF -DHDF5_BUILD_CPP_LIB=OFF \
          -DHDF5_BUILD_FORTRAN=OFF -DHDF5_BUILD_HL_LIB=ON -DHDF5_ENABLE_Z_LIB_SUPPORT=ON \
          -DCMAKE_INSTALL_PREFIX="$work/hdf5-$kind" > "$work/hdf5-$kind-configure.log" 2>&1 &&
    cmake --build "$work/hdf5-build-$kind" -j2 > "$work/hdf5-$kind-build.log" 2>&1 &&
    cmake --install "$work/hdf5-build-$kind" > "$work/hdf5-$kind-install.log" 2>&1 ||
    row "HDF5 1.14.6 $kind build" "FAIL (see hdf5-$kind-*.log)"
  done
fi
# The core linked to the shared HDF5 1.14.6.
cmake -S "$core" -B "$work/shared" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DMESTRA_BUILD_TESTS=OFF -DHDF5_ROOT="$work/hdf5-shared" > "$work/shared-configure.log" 2>&1 &&
  cmake --build "$work/shared" -j2 > "$work/shared-build.log" 2>&1 ||
  row "shared build" "FAIL (see shared-build.log)"
cmake -S "$core" -B "$work/static" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DMESTRA_BUILD_TESTS=OFF -DMESTRA_STATIC_HDF5=ON -DHDF5_ROOT="$work/hdf5-static" \
      > "$work/static-configure.log" 2>&1 &&
  cmake --build "$work/static" -j2 > "$work/static-build.log" 2>&1 ||
  row "static build" "FAIL (see static-build.log)"

shared_core="$work/shared/libmestra.so"
static_core="$work/static/libmestra.so"
status=0
# The claim itself: no HDF5 symbol leaves the static core, and it needs no
# shared HDF5.
if [ -f "$static_core" ]; then
  h5=$(nm -D --defined-only "$static_core" | awk '{print $3}' | grep -c '^H5')
  others=$(nm -D --defined-only "$static_core" | awk '{print $3}' | grep -cv '^mes_')
  linked=$(ldd "$static_core" | grep -c hdf5)
  if [ "$h5" = 0 ] && [ "$linked" = 0 ]; then
    row "static core exports" "$(nm -D --defined-only "$static_core" | grep -c ' mes_') mes_* symbols, $h5 H5 symbols, $others others; $linked shared HDF5 dependencies"
  else
    row "static core exports" "FAIL: $h5 H5 symbols exported, $linked shared HDF5 dependencies"
    status=1
  fi
else
  status=1
fi
fail() {  # name, required, message
  row "$1" "FAIL: $3"
  [ "$2" = yes ] && status=1
}
run() {   # name, core, preload ("none" or a library), required
  local name=$1 lib=$2 pre=$3 required=$4 env=()
  [ -f "$lib" ] || { fail "$name" "$required" "not built"; return; }
  if [ "$pre" != none ]; then
    # A missing library would make LD_PRELOAD a silent no-op.
    [ -f "$pre" ] || { fail "$name" "$required" "the library to preload is missing"; return; }
    env=(LD_PRELOAD="$pre")
    if ! env ${env[@]+"${env[@]}"} $py -c "import sys; sys.exit(0 if '$(basename "$pre")' in open('/proc/self/maps').read() else 1)"; then
      fail "$name" "$required" "the preload did not take effect"
      return
    fi
  fi
  env ${env[@]+"${env[@]}"} PYTHONPATH="$core/python" MESTRA_LIBRARY="$lib" \
    $py -m pytest -q -rs -p no:cacheprovider "$core/python/tests" > "$work/$name.log" 2>&1
  local code=$?
  local last
  last=$(tail -1 "$work/$name.log")
  # A pass needs tests that ran: skips are recorded, an empty run fails.
  if [ $code = 0 ] && echo "$last" | grep -qE '[0-9]+ passed'; then
    row "$name" "pass: $last"
  else
    fail "$name" "$required" "exit $code: $(grep -E 'passed|failed|error|Fatal|Segmentation' "$work/$name.log" | tail -2 | tr '\n' ' ' | cut -c1-180)"
  fi
}
# Under the system's 1.10, h5py itself cannot import (its symbols bind to
# the preloaded copy), so those suite runs are recorded, not required; the
# corpus check, which imports no h5py, is the core's own test there.
run shared-beside-h5py "$shared_core" none no
run shared-under-h5py-global "$shared_core" "$h5py_lib" no
run shared-under-system-global "$shared_core" "$system_lib" no
run static-beside-h5py "$static_core" none yes
run static-under-h5py-global "$static_core" "$h5py_lib" yes
run static-under-system-global "$static_core" "$system_lib" no

$py "$core/corpus/generate.py" "$work/corpus" > "$work/corpus-generate.log" 2>&1 ||
  row "corpus" "FAIL: not generated (see corpus-generate.log)"
corpus() {   # name, core, preload, required
  local name=$1 lib=$2 pre=$3 required=$4
  [ -f "$lib" ] || { fail "$name" "$required" "not built"; return; }
  [ -f "$pre" ] || { fail "$name" "$required" "the library to preload is missing"; return; }
  if env LD_PRELOAD="$pre" MESTRA_LIBRARY="$lib" $py "$core/corpus/check.py" "$work/corpus" \
       > "$work/$name.log" 2>&1; then
    row "$name" "pass: $(grep -m1 cases "$work/$name.log")"
  else
    fail "$name" "$required" "exit $?: $(grep -E 'cases|Fatal|Segmentation|Error' "$work/$name.log" | head -2 | tr '\n' ' ' | cut -c1-160)"
  fi
}
corpus corpus-shared-under-h5py-global "$shared_core" "$h5py_lib" no
corpus corpus-shared-under-system-global "$shared_core" "$system_lib" no
corpus corpus-static-under-h5py-global "$static_core" "$h5py_lib" yes
corpus corpus-static-under-system-global "$static_core" "$system_lib" yes
cat "$report"
exit $status
