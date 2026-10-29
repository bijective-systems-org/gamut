"""Holds the Python binding to the corpus written by generate.py.

    python corpus/check.py CORPUS_DIR

For every case: the findings of `validate` (a valid file has none; a rule
case has its rule among them; a hostile file is refused without a crash),
and for valid files the probe values, compared exactly.  Exit status 0 when
every case holds.  Other bindings get a checker of the same shape.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import gamut  # noqa: E402
from gamut import _lib  # noqa: E402


def described(f, p: dict) -> str | None:
    """A file-level attribute as `describe` gives it: None when absent."""
    got = f.describe().get(p["describe"])
    return None if got == p["value"] else f"describe {p['describe']}: {got!r} != {p['value']!r}"


def probe(path: str, p: dict) -> str | None:
    """None when the probe holds, else what differed."""
    if "evaluate" in p:
        with gamut.evaluate(path, p["evaluate"]) as out:
            if "describe" in p:
                return described(out, p)
            got = out.get_scalar(p["scalar"]).tolist()
        return None if got == p["values"] else f"evaluate {p['scalar']}: {got} != {p['values']}"
    if "copy" in p:
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "copy.gamut")
            if p["copy"] == "extract":
                gamut.extract(path, dst, p["rows"])
            else:
                gamut.write_copy(path, dst)
            with gamut.open(dst) as f:
                return described(f, p)
    with gamut.open(path) as f:
        if "describe" in p:
            return described(f, p)
        if "info" in p:
            got = getattr(f, p["info"])
            return None if got == p["value"] else f"{p['info']}: {got!r} != {p['value']!r}"
        if "label" in p:
            got = f.get_label(p["label"], rows=p["rows"]).tolist()
            return None if got == p["names"] else f"label {p['label']}: {got} != {p['names']}"
        if "select" in p:
            got = f.select(p["select"]).tolist()
            return None if got == p["positions"] else f"select: {got} != {p['positions']}"
        rows = _lib.Selection(p.get("rows"), "rows")
        rows.resolve(f.row_count)
        sites = _lib.Selection(p.get("sites"), "sites")
        dtype = np.dtype(p["dtype"])
        got = _lib.read(f._handle(), p["read"], rows, sites, dtype)
        want = np.asarray(p["values"], dtype=dtype)
        if got.shape != want.shape:
            return f"read {p['read']}: shape {got.shape} != {want.shape}"
        if not np.array_equal(got.view(np.uint8), want.view(np.uint8)):
            return f"read {p['read']}: {got.tolist()} != {want.tolist()}"
    return None


def hostile_read(path: str, f, r: dict) -> None:
    """One read of a hostile file; a refusal is a GamutError."""
    if "label" in r:
        f.get_label(r["label"])
    elif "cells" in r:
        f.get_cells(row=r["cells"])
    elif "select" in r:
        f.select(r["select"])
    elif "scalar" in r:
        f.get_scalar(r["scalar"])
    elif "evaluate" in r:
        with gamut.evaluate(path, r["evaluate"]):
            pass


def appends_to_itself(path: str) -> str:
    """A valid data file can be appended to: its own rows appended to a copy
    leave the copy free of errors, with twice the rows. A read-only file (a
    fixed layout, §11.5) is refused for appending, and its write_copy is not."""
    with gamut.open(path) as f:
        if f.kind != "data" or not f.row_count:
            return ""
        rows = f.row_count
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "copy.gamut")
        shutil.copy(path, copy)
        try:
            gamut.append(copy, path)
        except gamut.GamutError as exc:
            if not (exc.rule == "E25" and "read-only" in exc.message):
                return f"appending it to itself was refused: {exc}"
            os.remove(copy)
            gamut.write_copy(path, copy)
            try:
                gamut.append(copy, path)
            except gamut.GamutError as again:
                return f"read-only, and its write_copy refused appending too: {again}"
        # Repeating every row repeats each run's times (W9): only errors count.
        errors = [f for f in gamut.validate(copy).findings if f.severity == "error"]
        if errors:
            return "appended to itself, it drew " + "; ".join(f"{f.rule} {f.path}: {f.message}"
                                                             for f in errors)
        with gamut.open(copy) as f:
            if f.row_count != 2 * rows:
                return f"appended to itself, it has {f.row_count} rows, not {2 * rows}"
    return ""


def main() -> int:
    corpus = sys.argv[1]
    with open(os.path.join(corpus, "expected.json")) as fh:
        expected = json.load(fh)
    failures = []
    counts = {"valid": 0, "rules": 0, "hostile": 0}
    for name, e in sorted(expected.items()):
        path = os.path.join(corpus, f"{name}.gamut")
        counts[e["group"]] += 1
        try:
            report = gamut.validate(path)
        except Exception as exc:   # a binding error, not a finding
            failures.append(f"{name}: validate raised {type(exc).__name__}: {exc}")
            continue
        found = {f.rule for f in report.findings}
        if e["group"] == "valid":
            if report.findings:
                failures.append(f"{name}: a valid file drew " + "; ".join(
                    f"{f.rule} {f.path}: {f.message}" for f in report.findings))
            why = appends_to_itself(path)
            if why:
                failures.append(f"{name}: {why}")
            for p in e.get("probes", []):
                try:
                    why = probe(path, p)
                except Exception as exc:
                    why = f"probe {p} raised {type(exc).__name__}: {exc}"
                if why:
                    failures.append(f"{name}: {why}")
        else:
            # A rule case breaks exactly its rules; a hostile case must draw the
            # rules it names and may draw more, since a reader may refuse sooner.
            want = set(e["rules"])
            wrong = found != want if e["group"] == "rules" else not want <= found
            if wrong:
                failures.append(f"{name}: expected {sorted(want)}, found {sorted(found)}: " + "; ".join(
                    f"{f.rule} {f.path}: {f.message}" for f in report.findings))
            if e["group"] == "hostile":
                # Opened and read without a crash: a refusal is a GamutError,
                # with the expected rule when the case names one.
                try:
                    with gamut.open(path) as f:
                        f.names("parameters")
                        for r in e.get("reads", []):
                            try:
                                hostile_read(path, f, r)
                            except gamut.GamutError:
                                pass
                    if "refused" in e:
                        failures.append(f"{name}: opened; expected refusal {e['refused']}")
                except gamut.GamutError as exc:
                    if "refused" in e and exc.rule != e["refused"]:
                        failures.append(f"{name}: refused with {exc.rule!r}, expected "
                                        f"{e['refused']}: {exc}")
                except Exception as exc:
                    failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
    total = sum(counts.values())
    print(f"{total} cases ({counts['valid']} valid, {counts['rules']} rule, {counts['hostile']} "
          f"hostile): {total - len({x.split(':')[0] for x in failures})} hold")
    for f in failures:
        print("  FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
