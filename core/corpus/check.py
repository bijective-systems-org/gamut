"""Holds the Python binding to the corpus written by generate.py.

    python core/corpus/check.py CORPUS_DIR

For every case: the findings of `validate` (a valid file has none; a rule
case has its rule among them; a hostile file is refused without a crash),
and for valid files the probe values, compared exactly.  Exit status 0 when
every case holds.  Other bindings get a checker of the same shape.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import mestra  # noqa: E402
from mestra import _lib  # noqa: E402


def probe(path: str, p: dict) -> str | None:
    """None when the probe holds, else what differed."""
    if "evaluate" in p:
        with mestra.evaluate(path, p["evaluate"]) as out:
            got = out.get_scalar(p["scalar"]).tolist()
        return None if got == p["values"] else f"evaluate {p['scalar']}: {got} != {p['values']}"
    with mestra.open(path) as f:
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


def main() -> int:
    corpus = sys.argv[1]
    with open(os.path.join(corpus, "expected.json")) as fh:
        expected = json.load(fh)
    failures = []
    counts = {"valid": 0, "rules": 0, "hostile": 0}
    for name, e in sorted(expected.items()):
        path = os.path.join(corpus, f"{name}.mes")
        counts[e["group"]] += 1
        try:
            report = mestra.validate(path)
        except Exception as exc:   # a binding error, not a finding
            failures.append(f"{name}: validate raised {type(exc).__name__}: {exc}")
            continue
        found = {f.rule for f in report.findings}
        if e["group"] == "valid":
            if report.findings:
                failures.append(f"{name}: a valid file drew " + "; ".join(
                    f"{f.rule} {f.path}: {f.message}" for f in report.findings))
            for p in e.get("probes", []):
                try:
                    why = probe(path, p)
                except Exception as exc:
                    why = f"probe {p} raised {type(exc).__name__}: {exc}"
                if why:
                    failures.append(f"{name}: {why}")
        else:
            missing = [r for r in e["rules"] if r not in found]
            if missing:
                failures.append(f"{name}: expected {missing}, found {sorted(found)}: " + "; ".join(
                    f"{f.rule} {f.path}: {f.message}" for f in report.findings))
            if e["group"] == "hostile":
                try:
                    with mestra.open(path) as f:
                        f.names("parameters")
                except mestra.MestraError:
                    pass
    total = sum(counts.values())
    print(f"{total} cases ({counts['valid']} valid, {counts['rules']} rule, {counts['hostile']} "
          f"hostile): {total - len({x.split(':')[0] for x in failures})} hold")
    for f in failures:
        print("  FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
