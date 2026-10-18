"""The documentation holds together: every relative link and image points to
a file that exists, and the benchmark page's tables and figures are what
bench/results/ gives."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from _pages import ROOT

PAGES = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"), *(ROOT / "bench").glob("*.md")]) \
    if (ROOT / "docs").is_dir() else []


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(page):
    text = page.read_text(encoding="utf-8")
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)       # not inside code
    targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'src="([^"]+)"', text)
    for target in targets:
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = (page.parent / target.split("#")[0]).resolve()
        assert path.exists(), f"{page.relative_to(ROOT)} links to {target}, which does not exist"


@pytest.mark.skipif(not (ROOT / "bench" / "results").is_dir(), reason="no benchmark results here")
def test_benchmark_page_matches_its_results():
    result = subprocess.run([sys.executable, str(ROOT / "bench" / "figures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
