"""Damaged copies of valid files, each validated in a child process.

    python corpus/generate.py CORPUS
    python tools/damaged_files.py CORPUS [--work DIR] [--timeout S]

For three valid files of the corpus (a table, a shared mesh, a changing
mesh), writes 140 damaged copies each (40 truncations, 80 single-bit flips,
20 runs of 16 zeroed bytes, from a fixed seed) and runs `gamut validate
--json` on each in a child process. Prints how many were answered (a
report, by rule), crashed (ended by a signal), hung (over the timeout) or
escaped (ended otherwise, such as a Python traceback), and each that was
not answered. Set GAMUT_LIBRARY to measure a particular build of the core.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from collections import Counter

CASES = ("changing", "shared_fixed", "table")


def damaged(data: bytes, rng: random.Random) -> list[tuple[str, bytes]]:
    n = len(data)
    out = [(f"truncated to {n * k // 41} bytes", data[: n * k // 41]) for k in range(1, 41)]
    for _ in range(80):
        i, bit = rng.randrange(n), rng.randrange(8)
        b = bytearray(data)
        b[i] ^= 1 << bit
        out.append((f"bit {bit} of byte {i} flipped", bytes(b)))
    for _ in range(20):
        i = rng.randrange(n - 16)
        b = bytearray(data)
        b[i:i + 16] = bytes(16)
        out.append((f"16 bytes zeroed at {i}", bytes(b)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("corpus")
    ap.add_argument("--work", default=None)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    work = args.work or tempfile.mkdtemp(prefix="gamut-damaged-")
    os.makedirs(work, exist_ok=True)
    rng = random.Random(20261017)
    outcomes: Counter[str] = Counter()
    lost = []
    for case in CASES:
        with open(os.path.join(args.corpus, case + ".gamut"), "rb") as fh:
            data = fh.read()
        for what, content in damaged(data, rng):
            path = os.path.join(work, "damaged.gamut")
            with open(path, "wb") as fh:
                fh.write(content)
            try:
                r = subprocess.run([sys.executable, "-m", "gamut.cli", "validate", "--json", path],
                                   capture_output=True, text=True, timeout=args.timeout)
                if r.returncode < 0:
                    kind = "crashed"
                else:
                    try:
                        json.loads(r.stdout)
                        kind = "answered"
                    except ValueError:
                        kind = "escaped"
            except subprocess.TimeoutExpired:
                kind = "hung"
            outcomes[kind] += 1
            if kind != "answered":
                lost.append(f"  {case}, {what}: {kind}")
    total = sum(outcomes.values())
    print(f"{total} damaged copies of {', '.join(CASES)}: " +
          ", ".join(f"{outcomes[k]} {k}" for k in ("answered", "crashed", "hung", "escaped")))
    print("\n".join(lost))
    return 0 if outcomes["answered"] == total else 1


if __name__ == "__main__":
    sys.exit(main())
