"""Integration weights, computed from the connectivity.

Section 3 says a weight array is "computed from connectivity, never
imported", and no document said how one gets into a file. This is
how: `compute_weights(support, location)` makes the measure of every
cell from the coordinates and the connectivity, lumps it onto the
nodes when the weights are wanted there, and stores the result as an
array with the role `weight`, the units of the coordinates raised to
the dimension of the cells, and `recomputed` set.

The measure of a cell is the measure of the simplices it decomposes
into, in the node order section 20 fixes: a line is its length, a
triangle and a quadrilateral their area, a tetrahedron, a hexahedron,
a wedge and a pyramid their volume. One table of simplices covers
them all, and a cell type that is not in it is refused by name rather
than approximated. The quadratic types of section 20 are refused for
that reason: the corner simplices of a curved cell are not the cell.

An `axis` support has no cells. Its nodes are the ends of the
segments between them, which lumps to the trapezoid rule, and that is
what it gets.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..errors import MestraError
from .model import ArraySlot, Support

__all__ = [
    "compute_weights",
    "cell_measures",
    "node_measures",
    "CELL_SIMPLICES",
    "CELL_NAMES",
]

#: Section 20: how each cell type decomposes into simplices, by the
#: positions of its nodes in VTK order, and the topological dimension
#: the decomposition measures. `None` in place of the simplices means
#: a fan from the first node, for a polygon of any node count.
CELL_SIMPLICES: dict[int, tuple[int, tuple[tuple[int, ...], ...] | None]] = {
    1: (0, ()),
    3: (1, ((0, 1),)),
    5: (2, ((0, 1, 2),)),
    7: (2, None),
    9: (2, ((0, 1, 2), (0, 2, 3))),
    10: (3, ((0, 1, 2, 3),)),
    12: (3, ((0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
             (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6))),
    13: (3, ((0, 1, 2, 3), (1, 2, 3, 4), (2, 3, 4, 5))),
    14: (3, ((0, 1, 2, 4), (0, 2, 3, 4))),
}

#: Section 20's names, for a message about a cell type.
CELL_NAMES = {
    1: "vertex", 3: "line", 5: "triangle", 7: "polygon",
    9: "quadrilateral", 10: "tetrahedron", 12: "hexahedron",
    13: "wedge", 14: "pyramid", 21: "quadratic line",
    22: "quadratic triangle", 23: "quadratic quadrilateral",
    24: "quadratic tetrahedron", 25: "quadratic hexahedron",
    26: "quadratic wedge", 27: "quadratic pyramid",
}

#: What each topological dimension is called, for a message.
_MEASURE_OF = {0: "count", 1: "length", 2: "area", 3: "volume"}


# ------------------------------------------------------------ the cells

def cell_measures(support: Support) -> tuple[np.ndarray, int]:
    """The measure of every cell, and the dimension it measures.

    Length for a line, area for a triangle, a polygon and a
    quadrilateral, volume for a tetrahedron, a hexahedron, a wedge
    and a pyramid, and the counting measure for a vertex. A support
    whose cells are not all of one dimension has no single measure
    and is refused: a length and an area do not add up.
    """
    xy = _coordinates(support)
    types = support.cell_types
    offsets = support.cell_offsets
    connectivity = support.cell_connectivity
    if types is None or offsets is None or connectivity is None:
        raise MestraError(
            "E38", "a support of kind %s carries no cells, so it has "
            "no cell measure" % support.kind, support.name)
    out = np.zeros(len(types), dtype="f8")
    dimension: int | None = None
    for cell, code in enumerate(np.asarray(types).tolist()):
        nodes = connectivity[offsets[cell]:offsets[cell + 1]]
        d, simplices = _decomposition(int(code), len(nodes),
                                      support.name)
        if dimension is None:
            dimension = d
        elif dimension != d:
            raise MestraError(
                "", "this support mixes cells of %d and %d dimensions "
                "(%s and %s), whose measures do not add up; compute "
                "weights on a support whose cells share a dimension"
                % (dimension, d, _MEASURE_OF[dimension], _MEASURE_OF[d]),
                support.name)
        out[cell] = _measure(xy[nodes], d, simplices, support.name)
    return out, 0 if dimension is None else dimension


def _decomposition(code: int, count: int, where: str
                   ) -> tuple[int, tuple[tuple[int, ...], ...]]:
    """The simplices of one cell, from its type code."""
    if code not in CELL_SIMPLICES:
        known = ", ".join(
            "%d (%s)" % (c, CELL_NAMES[c]) for c in sorted(CELL_SIMPLICES))
        if code in CELL_NAMES:
            raise MestraError(
                "", "cell type %d (%s) has curved edges, and the measure "
                "of the straight cell through its corners is not its "
                "measure, so this implementation will not pretend to "
                "one; it computes weights for the cell types %s"
                % (code, CELL_NAMES[code], known), where)
        raise MestraError(
            "E21", "cell type %d is not in the table of section 20; the "
            "types this computes weights for are %s" % (code, known),
            where)
    dimension, simplices = CELL_SIMPLICES[code]
    if simplices is None:
        # A polygon of any node count: a fan from its first node.
        simplices = tuple((0, at, at + 1) for at in range(1, count - 1))
    return dimension, simplices


def _measure(nodes: np.ndarray, dimension: int,
             simplices: tuple[tuple[int, ...], ...], where: str) -> float:
    """The measure of one cell, from its nodes in VTK order."""
    if dimension == 0:
        # A vertex cell has no extent; the measure of a set of points
        # is the count of them, so each one weighs one.
        return 1.0
    total = 0.0
    for simplex in simplices:
        corners = nodes[list(simplex)]
        edges = corners[1:] - corners[0]
        if dimension == 3:
            if edges.shape[1] != 3:
                raise MestraError(
                    "", "a volume needs three coordinates per node, and "
                    "this support has %d" % edges.shape[1], where)
            total += abs(float(np.linalg.det(edges))) / 6.0
        elif dimension == 2:
            # The Gram determinant, so that a triangle has the same
            # area whatever the number of coordinates its nodes carry.
            gram = edges @ edges.T
            total += float(np.sqrt(max(np.linalg.det(gram), 0.0))) / 2.0
        else:
            total += float(np.linalg.norm(edges[0]))
    return total


# ------------------------------------------------------------ the nodes

def node_measures(support: Support) -> tuple[np.ndarray, int]:
    """Each node's lumped share of the cells that touch it.

    A cell gives an equal share of its measure to each of its nodes,
    which is the lumped weight every finite-element code writes. On
    an `axis` support, where there are no cells, the nodes are the
    ends of the segments between them and the lumping is the
    trapezoid rule.
    """
    if support.kind == "axis":
        return _axis_measures(support), 1
    lumped, dimension = cell_measures(support)
    out = np.zeros(support.n_nodes, dtype="f8")
    for cell in range(int(support.n_cells)):
        nodes = support.cells_of(cell)
        if len(nodes):
            np.add.at(out, nodes, lumped[cell] / len(nodes))
    return out, dimension


def _axis_measures(support: Support) -> np.ndarray:
    """The trapezoid weights of an axis support's own coordinate."""
    xy = _coordinates(support)
    if xy.shape[1] != 1:
        raise MestraError(
            "", "an axis support has one coordinate per node, and this "
            "one has %d" % xy.shape[1], support.name)
    axis = xy[:, 0]
    if axis.size < 2:
        return np.ones(axis.size, dtype="f8") * 0.0
    steps = np.abs(np.diff(axis))
    out = np.zeros(axis.size, dtype="f8")
    out[:-1] += steps / 2.0
    out[1:] += steps / 2.0
    return out


def _coordinates(support: Support) -> np.ndarray:
    """The node coordinates, as (node, component)."""
    slot = support.coordinates
    if slot is not None and slot.is_callable:
        raise MestraError(
            "", "the coordinates of this support are served by %s and "
            "hold no values; evaluate the file first" % slot.source,
            support.name)
    if slot is None or slot.data is None:
        raise MestraError(
            "", "this support carries no coordinates, so it has no "
            "measure", support.name)
    values = np.asarray(slot.read().values)
    if slot.varies != "none":
        raise MestraError(
            "", "these coordinates vary along %s, so there is a measure "
            "per %s and not one for the support; select one instance "
            "first" % (slot.varies, slot.varies), support.name)
    return values.reshape(values.shape[-2], values.shape[-1])


# ----------------------------------------------------------- the weights

def measures(support: Support, location: str) -> tuple[np.ndarray, int]:
    """The measure at one location, and the dimension it measures."""
    if location == "cell":
        return cell_measures(support)
    if location == "node":
        return node_measures(support)
    raise MestraError(
        "", "weights are at the nodes or at the cells, and this says "
        "%r; pass location=\"node\" or location=\"cell\"" % location,
        support.name)


def compute_weights(support: Support, location: str = "node",
                    name: str = "weight") -> ArraySlot:
    """Add the integration weights of a support, at one location.

    Section 3: a weight array is computed from the connectivity and
    never imported, so this is the only way one gets into a file.
    The array carries the role `weight`, the units of the
    coordinates raised to the dimension of the cells, and the
    `recomputed` flag; it is called `weight` at both locations
    unless you name it. Calling it again recomputes it.
    """
    values, dimension = measures(support, location)
    arrays = (support.node_arrays if location == "node"
              else support.cell_arrays)
    arrays.pop(name, None)
    return _add(support, location, name, values,
                _raised(_units_of(support), dimension))


def _add(support: Support, location: str, name: str, values: np.ndarray,
         units: str) -> ArraySlot:
    add: Any = (support.add_node_array if location == "node"
                else support.add_cell_array)
    return add(name, values, units=units, dims=(location,),
               role="weight", recomputed=True)


def _units_of(support: Support) -> str:
    slot = support.coordinates
    return (slot.units or "1") if slot is not None else "1"


def _raised(units: str, dimension: int) -> str:
    """A units string raised to a power, still in the CF grammar."""
    if dimension == 0:
        return "1"
    if dimension == 1:
        return units
    if units.isalpha():
        return "%s%d" % (units, dimension)
    return "(%s)%d" % (units, dimension)
