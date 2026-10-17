"""Integration weights computed from the connectivity (section 3).

Every cell measure is checked against a shape whose measure is known
by hand, so that a decomposition that is upside down or double counts
is caught rather than merely running.
"""

from __future__ import annotations

import numpy as np
import pytest

from mestra import _v0 as mestra
from mestra._v0 import post
from mestra._v0.weights import cell_measures, node_measures
from mestra.errors import MestraError

XY = np.array([[0., 0.], [1., 0.], [2., 0.],
               [0., 1.], [1., 1.], [2., 1.]])
QUADS = (np.array([9, 9]), np.array([0, 4, 8]),
         np.array([0, 1, 4, 3, 1, 2, 5, 4]))


def mesh(coordinates, cells, units="m"):
    ds = mestra.Dataset(writer="t")
    return ds.add_support("s0", coordinates=coordinates, cells=cells,
                          units=units)


def cell(code, nodes, coordinates):
    """One cell of one type, as its own support."""
    return mesh(np.asarray(coordinates, dtype="f8"),
                (np.array([code]), np.array([0, len(nodes)]),
                 np.array(nodes)))


# ----------------------------------------------------- the cell measures

def test_a_line_is_its_length():
    support = cell(3, [0, 1], [[0., 0., 0.], [3., 4., 0.]])
    measures, dimension = cell_measures(support)
    assert dimension == 1
    assert measures.tolist() == [5.0]


def test_a_triangle_is_its_area():
    support = cell(5, [0, 1, 2], [[0., 0.], [4., 0.], [0., 3.]])
    measures, dimension = cell_measures(support)
    assert dimension == 2
    assert measures[0] == pytest.approx(6.0)


def test_a_triangle_in_three_dimensions_is_the_same_triangle():
    flat = cell(5, [0, 1, 2], [[0., 0., 0.], [4., 0., 0.],
                               [0., 3., 0.]])
    tilted = cell(5, [0, 1, 2], [[0., 0., 0.], [0., 4., 0.],
                                 [0., 0., 3.]])
    assert cell_measures(flat)[0][0] == pytest.approx(
        cell_measures(tilted)[0][0])


def test_a_quadrilateral_is_its_area():
    support = mesh(XY, QUADS)
    measures, dimension = cell_measures(support)
    assert dimension == 2
    assert measures.tolist() == [1.0, 1.0]


def test_a_polygon_of_any_node_count():
    pentagon = [[0., 0.], [2., 0.], [3., 1.], [1.5, 2.], [0., 1.]]
    support = cell(7, [0, 1, 2, 3, 4], pentagon)
    # The shoelace area of the same five points.
    xy = np.array(pentagon)
    shoelace = 0.5 * abs(sum(
        xy[at, 0] * xy[(at + 1) % 5, 1] - xy[(at + 1) % 5, 0] * xy[at, 1]
        for at in range(5)))
    assert cell_measures(support)[0][0] == pytest.approx(shoelace)


def test_a_tetrahedron_is_its_volume():
    support = cell(10, [0, 1, 2, 3], [[0., 0., 0.], [1., 0., 0.],
                                      [0., 1., 0.], [0., 0., 1.]])
    measures, dimension = cell_measures(support)
    assert dimension == 3
    assert measures[0] == pytest.approx(1.0 / 6.0)


def test_a_hexahedron_is_its_volume():
    unit = [[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.],
            [0., 0., 1.], [1., 0., 1.], [1., 1., 1.], [0., 1., 1.]]
    support = cell(12, list(range(8)), unit)
    assert cell_measures(support)[0][0] == pytest.approx(1.0)
    stretched = (np.array(unit) * [2.0, 3.0, 4.0]).tolist()
    assert cell_measures(cell(12, list(range(8)), stretched))[0][0] == \
        pytest.approx(24.0)


def test_a_wedge_is_its_volume():
    prism = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
             [0., 0., 2.], [1., 0., 2.], [0., 1., 2.]]
    support = cell(13, list(range(6)), prism)
    assert cell_measures(support)[0][0] == pytest.approx(1.0)


def test_a_pyramid_is_its_volume():
    pyramid = [[0., 0., 0.], [2., 0., 0.], [2., 2., 0.], [0., 2., 0.],
               [1., 1., 3.]]
    support = cell(14, list(range(5)), pyramid)
    assert cell_measures(support)[0][0] == pytest.approx(4.0)


def test_a_vertex_cell_counts_once():
    support = cell(1, [0], [[1., 2., 3.]])
    measures, dimension = cell_measures(support)
    assert dimension == 0
    assert measures.tolist() == [1.0]


def test_a_quadratic_cell_is_refused_by_name():
    """The corner simplices of a curved cell are not the cell."""
    support = cell(22, [0, 1, 2, 3, 4, 5],
                   [[0., 0.], [2., 0.], [0., 2.],
                    [1., 0.], [1., 1.], [0., 1.]])
    with pytest.raises(MestraError) as caught:
        cell_measures(support)
    assert "quadratic triangle" in str(caught.value)
    assert "triangle" in str(caught.value)
    assert caught.value.rule == ""


def test_cells_of_two_dimensions_have_no_common_measure():
    support = mesh(XY, (np.array([3, 5]), np.array([0, 2, 5]),
                        np.array([0, 1, 0, 1, 4])))
    with pytest.raises(MestraError) as caught:
        cell_measures(support)
    assert "do not add up" in str(caught.value)


# ----------------------------------------------------- the node measures

def test_node_weights_are_the_lumped_share_of_the_cells():
    support = mesh(XY, QUADS)
    measures, dimension = node_measures(support)
    assert dimension == 2
    # Two unit squares: the four corners take a quarter each, and the
    # two nodes both squares share take a half.
    assert measures.tolist() == [0.25, 0.5, 0.25, 0.25, 0.5, 0.25]
    assert measures.sum() == pytest.approx(cell_measures(support)[0].sum())


def test_an_axis_support_gets_the_trapezoid_rule():
    ds = mestra.Dataset(writer="t")
    support = ds.add_support("s0", kind="axis",
                             coordinates=[0.0, 1.0, 3.0, 4.0],
                             units="Hz")
    measures, dimension = node_measures(support)
    assert dimension == 1
    assert measures.tolist() == [0.5, 1.5, 1.5, 0.5]
    assert measures.sum() == pytest.approx(4.0)


# --------------------------------------------------------- the weights

def test_compute_weights_stores_what_section_3_requires(tmp_path):
    ds = mestra.Dataset(writer="t")
    ds.add_key("mach", [0.4, 0.8], role="condition", units="1")
    support = ds.add_support("s0", coordinates=XY, cells=QUADS,
                             units="m")
    support.add_node_array("p", np.zeros((2, 6)), units="Pa",
                           dims=("row", "node"))
    slot = mestra.compute_weights(support, "node")
    assert slot.name == "weight"
    assert slot.role == "weight"
    assert slot.recomputed is True
    assert slot.units == "m2"
    assert slot.varies == "none"
    assert slot.dims == ("node", "component")

    cells = mestra.compute_weights(support, "cell")
    assert cells.units == "m2"
    assert np.asarray(cells.read().values).reshape(-1).tolist() == \
        [1.0, 1.0]

    path = str(tmp_path / "weights.mes")
    mestra.write(ds, path)
    report = mestra.validate(path)
    assert report.error_ids == []
    # W06 is weights that are *not* marked recomputed.
    assert "W06" not in report.warning_ids
    with mestra.read(path) as back:
        again = back.supports["s0"].node_arrays["weight"]
        assert again.units == "m2" and again.recomputed is True


def test_the_units_are_the_coordinates_raised_to_the_dimension():
    ds = mestra.Dataset(writer="t")
    axis = ds.add_support("s0", kind="axis", coordinates=[0.0, 1.0],
                          units="Hz")
    assert mestra.compute_weights(axis, "node").units == "Hz"
    volume = mesh([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                   [0., 0., 1.]],
                  (np.array([10]), np.array([0, 4]),
                   np.array([0, 1, 2, 3])), units="m")
    assert mestra.compute_weights(volume, "cell").units == "m3"


def test_computing_them_again_replaces_them():
    support = mesh(XY, QUADS)
    first = mestra.compute_weights(support, "node")
    second = mestra.compute_weights(support, "node")
    assert len(support.node_arrays) == 1
    assert first is not second


def test_a_named_weight_array():
    support = mesh(XY, QUADS)
    slot = mestra.compute_weights(support, "cell", name="area")
    assert slot.name == "area"
    assert "area" in support.cell_arrays


def test_weights_of_a_support_whose_coordinates_vary():
    ds = mestra.Dataset(writer="t")
    ds.add_key("member", [0, 1], role="group",
               categories=["a", "b"])
    support = ds.add_support(
        "s0", coordinates=np.stack([XY, XY * 2.0]),
        varies="group:member", cells=QUADS)
    with pytest.raises(MestraError) as caught:
        mestra.compute_weights(support, "node")
    assert "vary along" in str(caught.value)


def test_the_helper_is_reachable_from_post_as_well():
    assert post.compute_weights is mestra.compute_weights
    assert "compute_weights" in dir(post)
    assert "np" not in dir(post)
