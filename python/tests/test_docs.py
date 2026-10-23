"""The documentation holds together: every relative link and image points to
a file that exists, and the benchmark page's tables and figures are what
bench/results/ gives."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap

import pytest

import gamut

from _pages import ROOT

PAGES = sorted([*ROOT.glob("*.md"), ROOT / "llms.txt", *(ROOT / "docs").rglob("*.md"),
                *(ROOT / "bench").glob("*.md")]) if (ROOT / "docs").is_dir() else []


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(page):
    text = page.read_text(encoding="utf-8")
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)       # not inside code
    targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'(?:src|srcset)="([^"]+)"', text)
    for target in targets:
        # This repository's own absolute links (the README is also PyPI's
        # page, where relative ones break) are checked as local paths.
        own = re.match(r"https://(?:github\.com/bijective-systems-org/gamut/(?:blob|tree)/main/|"
                       r"raw\.githubusercontent\.com/bijective-systems-org/gamut/main/)(.+)", target)
        if own:
            path = (ROOT / own.group(1).split("#")[0]).resolve()
            assert path.exists(), f"{page.relative_to(ROOT)} links to {target}, which does not exist"
            continue
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = (page.parent / target.split("#")[0]).resolve()
        assert path.exists(), f"{page.relative_to(ROOT)} links to {target}, which does not exist"


@pytest.mark.skipif(not (ROOT / "bench" / "results").is_dir(), reason="no benchmark results here")
def test_benchmark_page_matches_its_results():
    result = subprocess.run([sys.executable, str(ROOT / "bench" / "figures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_julia_install_names_this_release():
    # The Julia package is added from a tag, so that its layer matches the
    # wheel's core; each release moves the tag the pages name.
    version = re.search(r'^version = "(.+)"', (ROOT / "julia" / "Project.toml").read_text(), re.M)[1]
    for page in (ROOT / "README.md", ROOT / "docs" / "install.md"):
        revs = set(re.findall(r'rev="v([^"]+)"', page.read_text(encoding="utf-8")))
        assert revs == {version}, f"{page.name} adds Julia at {sorted(revs)}, not v{version}"


def test_the_package_overview_runs(tmp_path, monkeypatch):
    # help(gamut) opens on the whole pattern; it runs as shown.
    code = re.search(r"The whole pattern:\n\n(.*?)\n\n\S", gamut.__doc__, re.S)[1]
    monkeypatch.chdir(tmp_path)
    exec(textwrap.dedent(code), {})
    assert gamut.validate(str(tmp_path / "polar.gamut")).ok


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_llms_txt_shows_the_package_overview(tmp_path, monkeypatch):
    # llms.txt, for coding agents, opens on the same pattern as help(gamut).
    shown = re.search(r"```python\n(.*?)```", (ROOT / "llms.txt").read_text(encoding="utf-8"), re.S)[1]
    overview = re.search(r"The whole pattern:\n\n(.*?)\n\n\S", gamut.__doc__, re.S)[1]
    assert shown.strip() == textwrap.dedent(overview).strip()
