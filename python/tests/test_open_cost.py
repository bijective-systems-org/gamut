"""Section 29: what opening a file is allowed to cost.

"Opening a file must not read any array. A reader must be able to
report the row count, the keys with their roles and bounds, the
supports with their ids, and every slot with its attributes, having
read attributes and dataspaces only."

Attributes and dataspaces are linear in the number of objects, so an
open is linear in the number of row-dimensioned datasets or it is not
doing what the sentence says. It was not: an open took 3.1 s at 125
key columns, 10.6 s at 250, 41.6 s at 500 and 155.5 s at 1000, which
quadruples for every doubling and is the signature of a scan inside a
scan. The scan inside the scan was
the section 21 scale index, which maps a scale's object address to
its link name: it was rebuilt from a walk of the whole file once per
dataset, because it was looked up through `dataset.file`, which
hands back a fresh wrapper each time and threw the cache away with
it. One index per pass is what section 21 describes and what the
reader and the validator now build.

A file with a few hundred quantities of interest is an ordinary file,
so these two tests are about an ordinary file and not an exotic one.
They are timings, which are never exact. The second is a ratio and so
is indifferent to how busy the machine is; it is the one that says
what section 29 asks, and the one that fails if the scan inside the
scan ever comes back. The first is an absolute bar, and its number is
chosen rather than derived. A thousand columns opens in about 1.2 s
on the machine this was written on when nothing else is running, and
in 2.6 s on the same machine under a load average of thirty; it took
181 s before. The bar is five seconds, which no machine this is
likely to run on will fail and which nothing quadratic can pass. The
ratio is where the sharp statement lives.

What is left at a thousand columns is not one hot spot but about
1 ms of h5py per object, spent twice: once by the check `read` makes
before it will vouch for a file, and once by the read itself.

The third reconciliation added a file four times wider still.
`cases/wide_keys` is 4200 row-dimensioned datasets on one `row`
scale, which is past the 4085 attachments a dimension scale could
carry before section 21 fixed how one is created, so it is the
first file of its size anybody could write. The two tests at the
end are the same pair of statements about it: an absolute bar that
nothing quadratic passes, and the ratio against the thousand-column
file, which is the one that does not care how busy the machine is.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import h5py
import pytest

from mestra import _v0 as mestra
from tests import corpus

#: The two column counts compared. The larger is four times the
#: smaller, so a linear open costs about four times as much and a
#: quadratic one about sixteen.
SMALL, LARGE = 250, 1000

#: The corpus case of section 21's ceiling: 4200 row-dimensioned
#: datasets on one `row` scale, about four times the file above.
#: It is generated on demand, as vectors/README.md says.
WIDE = "wide_keys"

#: How many opens each measurement takes the fastest of. Noise on a
#: shared machine only ever adds time, so the minimum is the honest
#: number and the mean is not.
RUNS = 5

#: The same for the wide file, which costs a few seconds a pass.
WIDE_RUNS = 3


def _with_columns(source: str, path: str, count: int) -> str:
    """A corpus case with `count` extra key columns.

    Each is a copy of an existing key: the same dtype, the same
    attributes with their exact HDF5 types, the same chunk, and the
    file's `row` scale on its one axis. Nothing in the result is
    malformed, which is the point -- this is an ordinary file with
    more columns than the corpus has.
    """
    import shutil

    shutil.copy(source, path)
    with h5py.File(path, "r+") as f:
        keys = f["/keys"]
        model = keys["mach"]
        row = f["row"]
        for at in range(count):
            column = keys.create_dataset(
                "k%05d" % at, data=model[()], dtype=model.dtype,
                maxshape=(None,), chunks=model.chunks, track_times=False)
            for name in model.attrs:
                attr = h5py.h5a.open(model.id, name.encode("utf-8"))
                column.attrs.create(name, model.attrs[name],
                                    dtype=attr.dtype)
            column.dims[0].attach_scale(row)
    return path


def _fastest(call: Callable[[], Any], runs: int = RUNS) -> float:
    """The shortest of `runs` calls, in seconds."""
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - started)
    return best


def _fastest_open(path: str) -> float:
    """The shortest of `RUNS` opens, in seconds."""
    return _fastest(lambda: mestra.read(path).close())


@pytest.fixture(scope="module")
def opens(tmp_path_factory):
    """The two files, and what an open of each costs."""
    where = tmp_path_factory.mktemp("open_cost")
    source = corpus.case_path("mesh_two_rows")
    out = {}
    for count in (SMALL, LARGE):
        path = _with_columns(source, str(where / ("k%d.mes" % count)),
                             count)
        out[count] = _fastest_open(path)
    return out


@pytest.fixture(scope="module")
def wide():
    """`cases/wide_keys`, and what each of three passes over it costs.

    The three are the ones section 29 puts a cost on: opening the
    file, validating it, and reading one slot from a lazy open. The
    read is timed with the file already open, because that is what a
    lazy read is -- the open is the other measurement.
    """
    path = corpus.case_path(WIDE)          # skips when not generated
    probe = corpus.expected(WIDE)["probes"][-1]
    with mestra.read(path) as dataset:
        read = _fastest(lambda: corpus.probe_value(dataset, probe),
                        WIDE_RUNS)
        value = corpus.probe_value(dataset, probe)
    assert corpus.bits_equal(value, corpus.as_float(probe["value"])), (
        "the lazy read of %s returned %r" % (probe["slot"], value))
    return {"datasets": _datasets(path),
            "open": _fastest(lambda: mestra.read(path).close(),
                             WIDE_RUNS),
            "validate": _fastest(lambda: mestra.validate(path),
                                 WIDE_RUNS),
            "read": read}


def _datasets(path: str) -> int:
    """How many datasets a file holds, scales included."""
    count = 0

    def one(_name, obj):
        nonlocal count
        if isinstance(obj, h5py.Dataset):
            count += 1

    with h5py.File(path, "r") as f:
        f.visititems(one)
    return count


@pytest.mark.slow
def test_the_widest_file_costs_seconds_and_a_read_costs_nothing(wide):
    """Section 21's own case, at the size that made the rule.

    `wide_keys` is 4200 row-dimensioned datasets on one `row` scale,
    which is past the 4085 attachments a scale could carry before
    the creation property rule, so no writer could produce this file
    before and no reader was ever measured on one. Measured on the
    machine this was written on, over several runs: 3.2 to 4.0 s to
    open, 2.7 to 4.3 s to validate, and a tenth of a millisecond for
    one value out of the 4200th dataset.

    The bars are generous on purpose. Fifteen seconds is three to
    four times the measurement, which no machine this is likely to
    run on will fail; what it does catch is a pass that grew with the
    square of the dataset count, which at this size is a minute and
    not a second. The lazy read has a bar of its own because it must
    not grow with the file at all: it finds one slot and reads one
    chunk, and it is four orders of magnitude under its bar.
    """
    assert wide["open"] < 15.0, (
        "opening %d datasets took %.2f s" % (wide["datasets"],
                                             wide["open"]))
    assert wide["validate"] < 15.0, (
        "validating %d datasets took %.2f s" % (wide["datasets"],
                                                wide["validate"]))
    assert wide["read"] < 1.0, (
        "one lazy slot read took %.3f s" % wide["read"])


@pytest.mark.slow
def test_the_open_is_linear_from_a_thousand_datasets_to_four_thousand(
        opens, wide):
    """The ratio again, one doubling further out.

    The thousand-column file holds 1021 datasets and `wide_keys`
    holds 4201, 4.1 times as many, so a linear open costs about four
    times as much and a quadratic one about seventeen. Measured
    across runs the ratio sits between 1.8 and 3.4, at or under
    linear: the wide file's datasets carry two attributes apiece
    where a copied key column carries four, and an open is mostly
    attribute reads.

    The bar is eight, as it is between 250 and 1000 columns: far
    above anything linear on a busy machine and far below anything
    quadratic. This is the pair that would have caught the 4085
    ceiling turning into a cost as well as a limit.
    """
    ratio = wide["open"] / opens[LARGE]
    assert ratio < 8.0, (
        "%d datasets cost %.3f s and %d cost %.3f s, a ratio of %.1f "
        "where four times the datasets should cost about four times "
        "as much" % (LARGE, opens[LARGE], wide["datasets"],
                     wide["open"], ratio))


@pytest.mark.slow
def test_a_thousand_columns_open_in_seconds_and_not_minutes(opens):
    """The file that once took 155 s to open.

    A thousand key columns is 2.8 MB and about 1030 row-dimensioned
    datasets: an ordinary file, and one a user will wait for. It now
    costs about a second, and a reader that re-walks the file once
    per dataset cannot come near the bar however idle the machine.
    """
    assert opens[LARGE] < 5.0, (
        "opening a %d column file took %.2f s" % (LARGE, opens[LARGE]))


@pytest.mark.slow
def test_the_open_is_linear_in_the_number_of_columns(opens):
    """Four times the columns costs about four times as much.

    Sixteen is what a scan inside a scan costs, and the bar is set
    at eight: high enough that a slow machine, a cold cache or a
    fixed overhead cannot fail it, and far below anything quadratic.
    """
    ratio = opens[LARGE] / opens[SMALL]
    assert ratio < 8.0, (
        "%d columns cost %.3f s and %d cost %.3f s, a ratio of %.1f "
        "where four times the columns should cost about four times "
        "as much" % (SMALL, opens[SMALL], LARGE, opens[LARGE], ratio))
