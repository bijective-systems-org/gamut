"""Appending several files at once (spec section 11.5): the result of
appending them one by one, made in one session, so the destination is
copied once and gets every file's rows or none."""

from __future__ import annotations

import json
import shutil

import pytest

import gamut
from gamut import cli

from test_files import marked, table


def parts(tmp_path):
    dst = str(tmp_path / "study.gamut")
    table(dst, ["p", "q"], [1.0, 2.0])
    srcs = []
    for k, (cases, xs) in enumerate(((["r"], [3.0]), (["p", "s"], [4.0, 5.0]), (["t"], [6.0]))):
        srcs.append(str(tmp_path / f"part{k}.gamut"))
        table(srcs[-1], cases, xs)
    return dst, srcs


def test_several_files_give_what_one_by_one_gives(tmp_path):
    dst, srcs = parts(tmp_path)
    one_by_one = str(tmp_path / "one_by_one.gamut")
    shutil.copy(dst, one_by_one)
    for src in srcs:
        gamut.append(one_by_one, src)
    assert gamut.append(dst, srcs) == 4
    with gamut.open(dst) as f, gamut.open(one_by_one) as g:
        assert f.row_count == g.row_count == 6
        assert f.get_row_ids().tolist() == g.get_row_ids().tolist()
        assert f.get_label("case").tolist() == g.get_label("case").tolist()
        assert f.get_parameter("x").tolist() == g.get_parameter("x").tolist()
        assert f.get_scalar("y").tolist() == g.get_scalar("y").tolist()
    assert not gamut.validate(dst).findings
    assert gamut.append(dst, (srcs[0],)) == 1     # a list of one is a list


def test_a_source_that_does_not_fit_adds_nothing_and_is_named(tmp_path):
    dst, srcs = parts(tmp_path)
    other = str(tmp_path / "other.gamut")
    with gamut.create(other, writer="t", parameters={"x": "cm"}, labels={"case": "categorical"},
                      scalars={"y": "1"}) as s:
        s.add_run({"x": 1.0, "case": "p", "y": 1.0})
    before = open(dst, "rb").read()
    for given, named in (([srcs[0], other, srcs[1]], f'source 2 of 3, "{other}"'),
                         ([srcs[0], srcs[0]], f'source 2 of 2, "{srcs[0]}": it is source 1 too'),
                         ([srcs[0], dst], "source 2 of 2"),
                         ([], "no source file")):
        with pytest.raises(gamut.GamutError) as e:
            gamut.append(dst, given)
        assert named in str(e.value)
        assert open(dst, "rb").read() == before


def test_the_marking_rule_holds_for_each_source(tmp_path):
    a, a2, b, u = (str(tmp_path / n) for n in ("a.gamut", "a2.gamut", "b.gamut", "u.gamut"))
    marked(a, "PLACEHOLDER-A")
    marked(a2, "PLACEHOLDER-A")
    marked(b, "PLACEHOLDER-B")
    marked(u, None)
    before = open(a, "rb").read()
    with pytest.raises(gamut.GamutError) as e:
        gamut.append(a, [a2, u, b])
    assert e.value.rule == "E27" and f'source 3 of 3, "{b}"' in str(e.value)
    assert open(a, "rb").read() == before
    assert gamut.append(a, [a2, u, b], marking="PLACEHOLDER-C") == 3
    with gamut.open(a) as f:
        assert f.describe()["portion_marking"] == "PLACEHOLDER-C" and f.row_count == 4


def test_the_command_line_appends_several_files(tmp_path, capsys):
    dst, srcs = parts(tmp_path)
    assert cli.main(["append", dst, *srcs, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"appended": dst, "rows": 4}
    assert cli.main(["append", dst, srcs[0], srcs[1]]) == 0
    assert "appended 3 runs from 2 files" in capsys.readouterr().out
    doc = tmp_path / "runs.json"
    doc.write_text("{}")
    assert cli.main(["append", dst, srcs[0], str(doc)]) == 2
    assert "a JSON document is appended on its own" in capsys.readouterr().err
    assert cli.main(["append", dst, srcs[0], dst]) == 2
    with gamut.open(dst) as f:
        assert f.row_count == 9
