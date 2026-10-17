#!/usr/bin/env bash
# Whether the core works beside another HDF5 in one Linux process, where
# shared libraries share one symbol namespace. The core is built twice:
# against the system's shared HDF5, and with HDF5 linked in statically
# (MESTRA_STATIC_HDF5, only mes_* exported). Each runs the Python suite with
# h5py's own HDF5 loaded, and with a foreign HDF5 preloaded into the global
# namespace, as a host program such as MATLAB holds one.
#
#   WORK=/tmp/two-hdf5 PYTHON=python3 bash core/tests/two_hdf5_linux.sh
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
system_lib=$(ls /usr/lib/*/hdf5/serial/libhdf5.so.* 2>/dev/null | head -1)
row "h5py's HDF5" "$h5py_version, \`$(basename "$h5py_lib")\`"
row "system HDF5" "\`$(basename "$system_lib")\`"

# The core against the system's shared HDF5.
cmake -S "$core" -B "$work/shared" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DMESTRA_BUILD_TESTS=OFF > "$work/shared-configure.log" 2>&1 &&
  cmake --build "$work/shared" -j2 > "$work/shared-build.log" 2>&1 ||
  row "shared build" "FAIL (see shared-build.log)"

# HDF5 1.14.6 from source, static and position independent, then the core.
tarball="$work/hdf5-1.14.6.tar.gz"
if [ ! -d "$work/hdf5" ]; then
  curl -sSfL -o "$tarball" \
    https://github.com/HDFGroup/hdf5/releases/download/hdf5_1.14.6/hdf5-1.14.6.tar.gz &&
  row "HDF5 source" "1.14.6, sha256 $(sha256sum "$tarball" | cut -d' ' -f1)" &&
  tar -xzf "$tarball" -C "$work" &&
  cmake -S "$work/hdf5-1.14.6" -B "$work/hdf5-build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_TESTING=OFF \
        -DHDF5_BUILD_TOOLS=OFF -DHDF5_BUILD_EXAMPLES=OFF -DHDF5_BUILD_CPP_LIB=OFF \
        -DHDF5_BUILD_FORTRAN=OFF -DHDF5_BUILD_HL_LIB=ON -DHDF5_ENABLE_Z_LIB_SUPPORT=ON \
        -DCMAKE_INSTALL_PREFIX="$work/hdf5" > "$work/hdf5-configure.log" 2>&1 &&
  cmake --build "$work/hdf5-build" -j2 > "$work/hdf5-build.log" 2>&1 &&
  cmake --install "$work/hdf5-build" > "$work/hdf5-install.log" 2>&1 ||
  row "static HDF5" "FAIL (see hdf5-*.log)"
fi
cmake -S "$core" -B "$work/static" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DMESTRA_BUILD_TESTS=OFF -DMESTRA_STATIC_HDF5=ON -DHDF5_ROOT="$work/hdf5" \
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
run shared-beside-h5py "$shared_core" none no
run shared-under-foreign-global "$shared_core" "$h5py_lib" no
run static-beside-h5py "$static_core" none yes
run static-under-foreign-global "$static_core" "$h5py_lib" yes
run static-under-system-global "$static_core" "$system_lib" yes

# The corpus through the static core, h5py's HDF5 preloaded.
if [ -f "$static_core" ] && [ -f "$h5py_lib" ] &&
   $py "$core/corpus/generate.py" "$work/corpus" > "$work/corpus.log" 2>&1 &&
   MESTRA_LIBRARY="$static_core" LD_PRELOAD="$h5py_lib" \
     $py "$core/corpus/check.py" "$work/corpus" >> "$work/corpus.log" 2>&1; then
  row "corpus, static, foreign global" "$(grep cases "$work/corpus.log")"
else
  row "corpus, static, foreign global" "FAIL (see corpus.log)"
  status=1
fi
cat "$report"
exit $status
