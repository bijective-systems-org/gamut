"""The documentation holds together: every relative link and image points to
a file that exists, and the benchmark page's tables and figures are what
bench/results/ gives."""

from __future__ import annotations

import inspect
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
        # A link to the documentation site names a page built from docs/.
        site = re.match(r"https://bijective-systems-org\.github\.io/gamut/([^#]*)", target)
        if site:
            name = site.group(1) or "index.html"
            name = name[:-len("index.html")] + "README" if name.endswith("index.html") else name[:-len(".html")]
            path = ROOT / "docs" / (name + ".md")
            assert path.exists(), f"{page.relative_to(ROOT)} links to {target}, which no page of docs/ makes"
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


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_the_old_name_installs_this_release():
    # gamut-format, the name through 2.0.0, installs bijective-gamut at the
    # same version with the same extras.
    import tomllib
    package = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    old = tomllib.loads((ROOT / "packaging" / "gamut-format" / "pyproject.toml").read_text())["project"]
    version = package["version"]
    assert (package["name"], old["name"], old["version"]) == ("bijective-gamut", "gamut-format", version)
    assert old["dependencies"] == [f"bijective-gamut=={version}"]
    assert old["optional-dependencies"] == {extra: [f"bijective-gamut[{extra}]=={version}"]
                                            for extra in package["optional-dependencies"]}


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_rust_install_names_this_release():
    # The crates carry the package's version and are added from its tag.
    package = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(), re.M)[1]
    crates = re.search(r'^version = "(.+)"', (ROOT / "rust" / "Cargo.toml").read_text(), re.M)[1]
    assert crates == package, f"the Rust crates are {crates}, the package {package}"
    for page in (ROOT / "README.md", ROOT / "docs" / "install.md"):
        tags = set(re.findall(r'gamut", tag = "v([^"]+)"', page.read_text(encoding="utf-8")))
        assert tags <= {package}, f"{page.name} adds the Rust crate at {sorted(tags)}, not v{package}"


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


def _model_pattern() -> str:
    doc = inspect.getdoc(gamut.create_model)
    return textwrap.dedent(re.search(r"The whole pattern, with a model type of one's own:\n\n(.*)",
                                     doc, re.S)[1]).strip()


def test_the_model_pattern_runs(tmp_path, monkeypatch, capsys):
    # help(gamut.create_model) ends on the whole model pattern; it runs as
    # shown, and the model file and the answer it gives are valid.
    monkeypatch.chdir(tmp_path)
    exec(_model_pattern(), {})
    assert capsys.readouterr().out.strip() == "[0.11 0.55]"
    assert gamut.validate(str(tmp_path / "lift.gamut")).ok


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_llms_txt_shows_the_model_pattern():
    shown = re.findall(r"```python\n(.*?)```", (ROOT / "llms.txt").read_text(encoding="utf-8"), re.S)
    assert any(block.strip() == _model_pattern() for block in shown), \
        "llms.txt shows the model pattern of help(gamut.create_model)"


@pytest.mark.skipif(not PAGES, reason="the documentation is not beside this test (an installed package)")
def test_the_python_reference_covers_the_package():
    # The reference is generated from the docstrings of what it names; a
    # name the package exports and the page leaves out would go undocumented.
    page = (ROOT / "docs" / "reference" / "python.md").read_text(encoding="utf-8")
    shown = set(re.findall(r"^::: gamut\.(\w+)$", page, re.M))
    exported = set(gamut.__all__) - {"FORMAT"}          # a constant, named in the page's text
    assert shown == exported, f"missing {sorted(exported - shown)}, not exported {sorted(shown - exported)}"

