"""Damaged copies of valid files, each validated and read in child processes.

    python corpus/generate.py CORPUS
    python tools/damaged_files.py CORPUS [--copies N] [--jobs J] [--work DIR] [--timeout S]
                                         [--memory MIB]

For every valid file of the corpus (tables, meshes shared and changing,
families, point clouds, model files), writes N damaged copies (140 by
default: two sevenths truncations, four sevenths single-bit flips, one
seventh runs of 16 zeroed bytes, from a fixed seed per file). Each copy is
checked twice, each time in a child process: `gamut validate --json`, then
a reader that opens it and makes every read on every name (names,
describe, each get_ call with all rows and with row 0, categories, notes,
private records, model numbers, select on a parameter and a label,
table(), points and cells of row 0, evaluate for a model file, and the
fields again through the threaded reader).

Prints, for validating and for reading, how many copies were answered (a
report by rule, or every read returned or refused with GamutError),
crashed (ended by a signal, or a sanitizer report), hung (over the
timeout), escaped (ended otherwise, or a read raised anything but
GamutError, which is a defect of the language layer) or oversized (stopped
above the memory given a child: a damaged extent that stays within the
read limits), and each copy that was not answered, kept in the work
directory. Set GAMUT_LIBRARY to measure a particular build of the core.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

KINDS = ("answered", "crashed", "hung", "escaped", "oversized")


def damaged(data: bytes, rng: random.Random, copies: int) -> list[tuple[str, bytes]]:
    n = len(data)
    cuts = copies * 2 // 7
    flips = copies * 4 // 7
    zeroed = copies - cuts - flips
    out = [(f"truncated to {n * k // (cuts + 1)} bytes", data[: n * k // (cuts + 1)])
           for k in range(1, cuts + 1)]
    for _ in range(flips):
        i, bit = rng.randrange(n), rng.randrange(8)
        b = bytearray(data)
        b[i] ^= 1 << bit
        out.append((f"bit {bit} of byte {i} flipped", bytes(b)))
    for _ in range(zeroed):
        i = rng.randrange(n - 16)
        b = bytearray(data)
        b[i:i + 16] = bytes(16)
        out.append((f"16 bytes zeroed at {i}", bytes(b)))
    return out


# --- the reader child ---------------------------------------------------------------


def exercise(path: str) -> dict:
    """Every read of a file, each one's outcome counted; run in a child."""
    import warnings

    import gamut
    import numpy as np

    warnings.simplefilter("ignore")
    done = Counter()
    escaped: list[str] = []

    def attempt(what: str, fn):
        try:
            value = fn()
            done["returned"] += 1
            return value
        except gamut.GamutError:
            done["refused"] += 1
        except Exception as e:  # anything else escapes the layer: a defect
            escaped.append(f"{what}: {type(e).__name__}: {e}"[:300])
        return None

    study = attempt("open", lambda: gamut.open(path))
    if study is None:
        return {"reads": dict(done), "escaped": escaped}
    with study:
        for prop in ("kind", "type", "addons", "row_count"):
            attempt(prop, lambda: getattr(study, prop))
        groups = ("parameters", "labels", "scalars", "constants", "node_fields",
                  "cell_fields", "node_labels", "cell_labels", "tables", "models")
        names = {g: attempt(f"names({g})", lambda: study.names(g)) or [] for g in groups}
        attempt("describe()", lambda: study.describe())
        every = [n for g in groups[:8] for n in names[g]]
        for n in every + ["coordinates"] + [f"models/{m}" for m in names["models"]]:
            attempt(f"describe({n})", lambda: study.describe(n))
        attempt("get_row_ids", lambda: study.get_row_ids())
        reads = {"parameters": study.get_parameter, "labels": study.get_label,
                 "scalars": study.get_scalar, "node_fields": study.get_field,
                 "cell_fields": study.get_field}
        for g, fn in reads.items():
            for n in names[g]:
                for rows in (None, 0):
                    attempt(f"{fn.__name__}({n}, rows={rows})", lambda: fn(n, rows))
        for n in names["labels"]:
            attempt(f"get_label_codes({n})", lambda: study.get_label_codes(n))
        for n in names["constants"]:
            attempt(f"get_constant({n})", lambda: study.get_constant(n))
        for n in names["node_labels"] + names["cell_labels"]:
            for row in (None, 0):
                attempt(f"get_mesh_label({n}, row={row})", lambda: study.get_mesh_label(n, row))
        for n in names["labels"] + names["node_labels"] + names["cell_labels"]:
            attempt(f"categories({n})", lambda: study.categories(n))
        for n in names["scalars"] + names["node_fields"] + names["cell_fields"]:
            attempt(f"related({n})", lambda: study.related(n))
        for m in names["models"]:
            attempt(f"model_numbers({m})", lambda: study.model_numbers(m))
        attempt("notes", lambda: study.notes)
        for n in attempt("private_names", study.private_names) or []:
            attempt(f"get_private({n})", lambda: study.get_private(n))
        wheres = [f"{p} > 0" for p in names["parameters"][:1]]
        for n in names["labels"][:1]:
            entries = attempt(f"categories({n})", lambda: study.categories(n)) or ["x"]
            wheres.append(f"{n} == {entries[0]}")
        if len(wheres) == 2:
            wheres.append(f"{wheres[0]} and {wheres[1]}")
        for w in wheres:
            attempt(f"select({w})", lambda: study.select(w))
        attempt("table()", lambda: study.table())
        attempt("get_points(0)", lambda: study.get_points(0))
        attempt("get_points()", lambda: study.get_points())
        attempt("get_cells(0)", lambda: study.get_cells(0))
        attempt("get_cells()", lambda: study.get_cells())
        if attempt("kind", lambda: study.kind) == "model":
            inputs = {}
            for p in names["parameters"]:
                d = attempt(f"describe({p})", lambda: study.describe(p)) or {}
                try:
                    inputs[p] = [(float(d["lower"]) + float(d["upper"])) / 2]
                except (KeyError, ValueError):
                    inputs[p] = [0.0]
            for n in names["labels"]:
                entries = attempt(f"categories({n})", lambda: study.categories(n)) or ["x"]
                inputs[n] = [entries[0]]
            out = path + ".evaluated.gamut"

            def evaluate():
                with gamut.evaluate(path, inputs, path=out) as e:
                    return {k: np.asarray(v).tolist() for k, v in e.table().items()}

            attempt("evaluate", evaluate)
            if os.path.exists(out):
                os.remove(out)
    # Fields again through the threaded reader, which inflates chunks itself.
    threaded = attempt("open(threads=4)", lambda: gamut.open(path, threads=4))
    if threaded is not None:
        with threaded:
            for n in names["node_fields"] + names["cell_fields"]:
                for rows in (None, 0):
                    attempt(f"get_field({n}, rows={rows}) in threads",
                            lambda: threaded.get_field(n, rows))
    return {"reads": dict(done), "escaped": escaped}


# --- the parent ---------------------------------------------------------------------


def resident_mib(pid: int) -> int:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) >> 10


def validate_answered(code: int, out: dict) -> bool:
    """`gamut validate --json` answered: a report (exit 0 when the file is
    valid, 1 when not) or a refusal by rule (exit 1)."""
    return ((code == 0 and out.get("ok") is True)
            or (code == 1 and (out.get("ok") is False or "error" in out)))


def read_answered(code: int, out: dict) -> bool:
    """The reading child answered: it ran to the end and listed its reads."""
    return code == 0 and "reads" in out


def run_child(argv: list[str], timeout: float, memory: int,
              answered: Callable[[int, dict], bool]) -> tuple[str, str]:
    """The outcome of a child and, when it was not answered, why."""
    start = time.monotonic()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while True:
        try:
            stdout, stderr = p.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            # A damaged extent can stay under the read limits (2^30 values)
            # and still be more than a shared machine should give one read.
            over = resident_mib(p.pid) > memory
            if over or time.monotonic() - start > timeout:
                p.kill()
                p.communicate()
                return ("oversized", f"over {memory} MiB") if over else ("hung", "")
    # A sanitizer's report, not its warnings (a refused allocation is one).
    report = [ln for ln in stderr.splitlines()
              if ("ERROR: " in ln and "Sanitizer" in ln) or "runtime error" in ln]
    if p.returncode < 0 or report:
        return "crashed", report[0] if report else f"signal {-p.returncode}"
    last = stderr.strip().splitlines()
    try:
        out = json.loads(stdout)
    except ValueError:
        out = None
    if isinstance(out, dict) and out.get("escaped"):
        return "escaped", "; ".join(out["escaped"][:3])
    if not isinstance(out, dict) or not answered(p.returncode, out):
        report = "an unexpected report" if isinstance(out, dict) else "no report"
        return "escaped", last[-1] if last else f"exit {p.returncode}, {report}"
    return "answered", ""


def check(job: tuple[str, int, str, bytes], work: str, timeout: float,
          memory: int) -> tuple[tuple[str, str], tuple[str, str]]:
    case, i, what, content = job
    path = os.path.join(work, f"{case}-{i:04d}.gamut")
    with open(path, "wb") as fh:
        fh.write(content)
    validated = run_child([sys.executable, "-m", "gamut.cli", "validate", "--json", path],
                          timeout, memory, validate_answered)
    read = run_child([sys.executable, os.path.abspath(__file__), "--exercise", path],
                     timeout, memory, read_answered)
    if validated[0] == "answered" and read[0] == "answered":
        os.remove(path)
    return validated, read


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("corpus", nargs="?")
    ap.add_argument("--copies", type=int, default=140, help="damaged copies of each file")
    ap.add_argument("--jobs", type=int, default=1, help="copies checked at once")
    ap.add_argument("--work", default=None)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--memory", type=int, default=1024, help="MiB a child may hold")
    ap.add_argument("--exercise", metavar="FILE", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.exercise:
        print(json.dumps(exercise(args.exercise)))
        return 0
    if not args.corpus:
        ap.error("the corpus directory is required")
    with open(os.path.join(args.corpus, "expected.json")) as fh:
        cases = sorted(k for k, v in json.load(fh).items() if v["group"] == "valid")
    work = args.work or tempfile.mkdtemp(prefix="gamut-damaged-")
    os.makedirs(work, exist_ok=True)
    jobs = []
    for case in cases:
        with open(os.path.join(args.corpus, case + ".gamut"), "rb") as fh:
            data = fh.read()
        rng = random.Random(f"20261017 {case}")
        jobs += [(case, i, what, content)
                 for i, (what, content) in enumerate(damaged(data, rng, args.copies))]
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = list(pool.map(lambda j: check(j, work, args.timeout, args.memory), jobs))
    total = len(jobs)
    print(f"{total} damaged copies of {len(cases)} files ({', '.join(cases)}), in {work}")
    for step, at in (("validating", 0), ("reading", 1)):
        outcomes = Counter(r[at][0] for r in results)
        print(f"{step}: " + ", ".join(f"{outcomes[k]} {k}" for k in KINDS))
    lost = []
    for (case, i, what, _), (validated, read) in zip(jobs, results):
        for step, (kind, why) in (("validate", validated), ("read", read)):
            if kind != "answered":
                lost.append(f"  {case}-{i:04d} ({what}), {step}: {kind}" + (f": {why}" if why else ""))
    print("\n".join(lost))
    return 0 if not lost else 1


if __name__ == "__main__":
    sys.exit(main())
