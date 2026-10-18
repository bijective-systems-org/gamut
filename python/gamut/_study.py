"""Study files: create and add runs, or open and read.  Every call goes to
the shared core."""

from __future__ import annotations

import ctypes
from typing import Any, Mapping, Sequence

import numpy as np

from . import _lib, _units
from ._lib import GamutError, Selection, b, call


def _same_geometry(a: tuple, b_: tuple) -> bool:
    """Points, cells and mesh labels equal value for value."""
    (pa, ca, la), (pb, cb, lb) = a, b_
    if not np.array_equal(np.asarray(pa), np.asarray(pb)):
        return False
    if (ca is None) != (cb is None):
        return False
    if ca is not None and not all(np.array_equal(np.asarray(x), np.asarray(y))
                                  for x, y in zip(ca, cb)):
        return False
    la, lb = la or {}, lb or {}
    return la.keys() == lb.keys() and all(np.array_equal(np.asarray(la[k]), np.asarray(lb[k]))
                                          for k in la)


def _one_row(row: Any) -> list[int]:
    """One row position, as the one-element list the core reads."""
    if isinstance(row, (bool, np.bool_)) or not isinstance(row, (int, np.integer)):
        raise GamutError("", f"row: one integer position; got {row!r}")
    return [int(row)]


def _spec(value: Any, key: str) -> dict:
    """A declaration given as a plain string (its units) or a mapping."""
    if isinstance(value, Mapping):
        return dict(value)
    return {key: value}


def _axes(coordinates: Mapping[str, Any] | None) -> int:
    value = (coordinates or {}).get("axes", 3)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise GamutError("E24", f"coordinates: axes is 1, 2 or 3, not {value!r}")
    return int(value)


def _precision(value: Any) -> int:
    if value is None:
        return _lib.GAMUT_AS_GIVEN
    table = {"float32": _lib.GAMUT_FLOAT32, "float64": _lib.GAMUT_FLOAT64,
             "int64": _lib.GAMUT_INT64}
    try:
        return table[str(np.dtype(value)) if not isinstance(value, str) else value]
    except (KeyError, TypeError):
        raise GamutError("E4", f"precision {value!r} is not float32, float64 or int64") from None


class Study:
    """A study file open to write (from `create`) or to read (from `open`).

    Arrays it returns are the caller's own; it is a context manager, and
    `close()` releases the file."""

    def __init__(self, handle: ctypes.c_void_p, path: str, writing: bool) -> None:
        self._h = handle
        self.path = path
        self._writing = writing
        self._group: str | None = None
        self._mesh_kind = ""
        self._per = ""
        self._axes = 3
        self._described: dict[str, dict[str, str]] = {}
        self._rows: int | None = None
        self._declared_units: dict[str, str] = {}
        if not writing:
            self._mesh_kind = self._info("mesh_kind")
            self._per = self._info("per")

    # --- life cycle -------------------------------------------------------

    def close(self) -> None:
        """Finishes the file.  A refused close (a shared mesh never set, a
        model file without a model) keeps it open to fix and close again."""
        if self._h is not None:
            call("gamut_close", self._h)
            self._h = None

    def _abandon(self, remove: bool) -> None:
        """Releases the file without finishing it; with `remove`, deletes a
        file this handle created.  For giving up after an error."""
        if self._h is not None:
            h, self._h = self._h, None
            _lib._lib.gamut_abandon(h, int(remove))

    def __enter__(self) -> "Study":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            # Nothing can be fixed once the block has ended: a file that
            # cannot be finished is discarded, and the refusal raised.
            try:
                self.close()
            except GamutError:
                self._abandon(remove=True)
                raise
            return
        # Leaving on an error: finish the file if it can be finished, else
        # discard a file this study created; the first error stands.
        try:
            self.close()
        except GamutError:
            self._abandon(remove=True)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            try:
                self._abandon(remove=False)
            except Exception:
                pass

    def _handle(self) -> ctypes.c_void_p:
        if self._h is None:
            raise GamutError("", f"{self.path} is closed")
        return self._h

    def _need_writer(self) -> None:
        if not self._writing:
            raise GamutError("", f"{self.path} was opened to read; add runs to a file "
                                  "from gamut.create or gamut.open(path, mode='a')")

    def _need_reader(self) -> None:
        if self._writing:
            raise GamutError("", f"{self.path} is open to write; close it and open it "
                                  "with gamut.open to read")

    # --- writing ----------------------------------------------------------

    def set_mesh(self, points: Any = None, cells: Any = None,
                 labels: Mapping[str, Any] | None = None, n_nodes: int | None = None) -> None:
        """A shared mesh: its cells (types, offsets, connectivity), its fixed
        mesh labels, and its points when the geometry is fixed.  When the
        coordinates come with the runs, give `n_nodes` instead of points."""
        self._need_writer()
        h = self._handle()
        call("gamut_geometry_begin", h)
        if points is None:
            if n_nodes is None:
                raise GamutError("", "give the points, or n_nodes when the coordinates "
                                      "come with the runs")
            call("gamut_geometry_points", h, _lib.GAMUT_FLOAT64, None, int(n_nodes), self._axes)
        self._stage_geometry(points, cells, labels or {}, nodes_hint=n_nodes)
        call("gamut_set_mesh", h)

    def _stage_geometry(self, points: Any, cells: Any, labels: Mapping[str, Any],
                        nodes_hint: int | None) -> None:
        h = self._handle()
        if points is not None:
            pts = _lib.as_array(points)
            if pts.ndim != 2:
                raise GamutError("E5", "points are nodes x axes")
            call("gamut_geometry_points", h, _lib.dtype_code(pts), pts.ctypes.data_as(ctypes.c_void_p),
                 pts.shape[0], pts.shape[1])
        elif nodes_hint is None and cells is not None:
            raise GamutError("", "give the points, or n_nodes through points of the right shape")
        if cells is not None:
            types, offsets, conn = cells
            t = np.ascontiguousarray(np.asarray(types, dtype=np.uint8))
            o = np.ascontiguousarray(np.asarray(offsets, dtype=np.int64))
            c = np.ascontiguousarray(np.asarray(conn, dtype=np.int64))
            call("gamut_geometry_cells", h, t.ctypes.data_as(ctypes.c_void_p), len(t),
                 o.ctypes.data_as(ctypes.c_void_p), c.ctypes.data_as(ctypes.c_void_p), len(c))
        for name, values in labels.items():
            v = np.ascontiguousarray(np.asarray(values, dtype=np.int64))
            call("gamut_geometry_label", h, b(name), v.ctypes.data_as(ctypes.c_void_p), len(v))

    def add_run(self, values: Mapping[str, Any], *, fields: Mapping[str, Any] | None = None,
                points: Any = None, cells: Any = None,
                mesh_labels: Mapping[str, Any] | None = None) -> int:
        """Adds one run; returns its id.  `values` gives each parameter, label
        (by name) and scalar; `fields` one value per node or cell."""
        columns = {k: [self._given(k, v)] for k, v in values.items()}
        flds = {k: np.asarray(v).reshape(1, -1) if self._mesh_kind != "changing" else np.asarray(v)
                for k, v in (fields or {}).items()}
        return self._commit(1, columns, flds, [points] if points is not None else None,
                            [cells] if cells is not None else None,
                            [mesh_labels] if mesh_labels is not None else None)[0]

    def _given(self, name: str, value: Any) -> Any:
        """A value as (number, units) is converted to the declared units."""
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
            target = self._declared_units.get(name)
            if target is None:
                raise GamutError("", f"{name} has no declared units to convert to")
            return float(_units.convert(value[0], value[1], target))
        return value

    def add_runs(self, columns: Mapping[str, Any], *, fields: Mapping[str, Any] | None = None,
                 points: Sequence[Any] | None = None, cells: Sequence[Any] | None = None,
                 mesh_labels: Sequence[Mapping[str, Any]] | None = None) -> list[int]:
        """Adds many runs at once: `columns` maps each name to one value per
        run; `fields` to runs x sites (a changing mesh: every run's values
        end to end); `points`, `cells`, `mesh_labels` one per run (or per new
        group member) when the geometry changes."""
        lengths = {len(v) if _lib.iterable(v) else 1 for v in columns.values()}
        if len(lengths) != 1:
            raise GamutError("E5", "every column needs the same number of runs")
        return self._commit(lengths.pop(), dict(columns), dict(fields or {}), points, cells,
                            mesh_labels)

    def _commit(self, n: int, columns: Mapping[str, Any], fields: Mapping[str, Any],
                points: Sequence[Any] | None, cells: Sequence[Any] | None,
                mesh_labels: Sequence[Mapping[str, Any]] | None) -> list[int]:
        self._need_writer()
        h = self._handle()
        call("gamut_batch_begin", h, n)
        keep = []
        group_names: list[str] | None = None
        for name, vals in columns.items():
            # NumPy drops trailing NULs from text, so names are checked as given.
            for x in ([vals] if isinstance(vals, str) else
                      vals if isinstance(vals, (list, tuple)) else []):
                if isinstance(x, str):
                    b(x)
            arr = np.asarray(vals)
            if arr.dtype.kind in "US" or arr.dtype == object or arr.dtype == np.bool_:
                names = ["true" if x is True or x is np.True_ else
                         "false" if x is False or x is np.False_ else str(x) for x in arr.tolist()]
                call("gamut_batch_names", h, b(name), _lib.string_array(names), len(names))
                if name == self._group:
                    group_names = names
                continue
            a = _lib.as_array(arr).ravel()
            keep.append(a)
            call("gamut_batch_values", h, b(name), _lib.dtype_code(a), a.ctypes.data_as(ctypes.c_void_p),
                 a.size)
        for name, vals in fields.items():
            a = _lib.as_array(vals).ravel()
            keep.append(a)
            call("gamut_batch_values", h, b(name), _lib.dtype_code(a), a.ctypes.data_as(ctypes.c_void_p),
                 a.size)
        if points is not None:
            points = list(points)
            cells = list(cells) if cells is not None else [None] * len(points)
            mesh_labels = list(mesh_labels) if mesh_labels is not None else [None] * len(points)
            if self._group is not None:
                # One geometry per group member's first run: in run order,
                # keyed by the member's name.  A repeat must be the same
                # geometry; a different one is refused, not dropped.
                if group_names is None:
                    raise GamutError("E2", f"give {self._group} by name so geometry can be "
                                            "matched to members")
                first: dict[str, int] = {}
                for i, member in enumerate(group_names):
                    if points[i] is None:
                        continue
                    if member in first:
                        j = first[member]
                        if not _same_geometry((points[i], cells[i], mesh_labels[i]),
                                              (points[j], cells[j], mesh_labels[j])):
                            raise GamutError("", f"{self._group} \"{member}\" is given two "
                                                  f"different geometries in one batch (runs {j} "
                                                  f"and {i})", self._group)
                        continue
                    first[member] = i
                    call("gamut_geometry_begin", h)
                    self._stage_geometry(points[i], cells[i], mesh_labels[i] or {}, None)
                    call("gamut_batch_geometry_for_member", h, b(member))
            else:
                for i in range(len(points)):
                    call("gamut_geometry_begin", h)
                    self._stage_geometry(points[i], cells[i], mesh_labels[i] or {}, None)
                    call("gamut_batch_geometry_for_row", h)
        first = ctypes.c_int64()
        call("gamut_batch_commit", h, ctypes.byref(first))
        del keep
        return list(range(first.value, first.value + n))

    # --- reading ------------------------------------------------------------

    def _info(self, key: str) -> str:
        values = _lib.strings_out("gamut_info", self._handle(), b(key))
        return values[0] if values else ""

    @property
    def kind(self) -> str:
        self._need_reader()
        return self._info("kind")

    @property
    def type(self) -> str:
        self._need_reader()
        return self._info("type")

    @property
    def addons(self) -> list[str]:
        self._need_reader()
        return _lib.strings_out("gamut_info", self._handle(), b("addons"))

    @property
    def row_count(self) -> int:
        self._need_reader()
        if self._rows is None:
            self._rows = int(self._info("row_count"))
        return self._rows

    def names(self, group: str) -> list[str]:
        self._need_reader()
        return _lib.strings_out("gamut_names", self._handle(), b(group))

    def describe(self, name: str | None = None) -> dict[str, str]:
        """A concept's attributes as text, or with no name the file's own."""
        self._need_reader()
        key = name or ""
        cached = self._described.get(key)
        if cached is None:
            keys, values = _lib.two_strings_out("gamut_describe", self._handle(), b(key))
            cached = self._described[key] = dict(zip(keys, values))
        return dict(cached)

    def _get(self, name: str, rows: Any = None, sites: Any = None,
             dtype: Any = np.float64, squeeze_row: bool = True) -> np.ndarray:
        self._need_reader()
        r = Selection(rows, "rows")
        s = Selection(sites, "sites")
        r.resolve(self.row_count)
        if s._slice is not None:
            # A slice of sites needs their count first.
            s.resolve(self._site_count(name, r))
        out = _lib.read(self._handle(), name, r, s, np.dtype(dtype))
        # One row asked as a single position drops the row axis.
        if squeeze_row and r.single and out.ndim >= 1 and out.shape[0] == 1:
            out = out[0]
        return out

    def _site_count(self, name: str, rows: Selection) -> int:
        shape = (ctypes.c_int64 * 4)()
        rank = ctypes.c_int()
        all_sites = Selection(None, "sites")
        call("gamut_shape", self._handle(), b(name), rows.pointer(), all_sites.pointer(), shape,
             ctypes.byref(rank))
        dims = [shape[i] for i in range(rank.value)]
        if name == "coordinates":
            return dims[-2]
        return dims[-1]

    def get_row_ids(self, rows: Any = None) -> np.ndarray:
        return self._get("row", rows, dtype=np.int64)

    def get_parameter(self, name: str, rows: Any = None, units: str | None = None) -> np.ndarray:
        d = self.describe(name)
        values = self._get(name, rows, dtype=np.int64 if d.get("dtype") == "int64" and units is None
                           else np.float64)
        return self._in_units(name, values, units)

    def get_label(self, name: str, rows: Any = None) -> np.ndarray:
        self._need_reader()
        r = Selection(rows, "rows")
        r.resolve(self.row_count)
        out = np.array(_lib.strings_out("gamut_label_names", self._handle(), b(name), r.pointer()),
                       dtype=str)
        return out[0] if r.single else out

    def get_label_codes(self, name: str, rows: Any = None) -> np.ndarray:
        return self._get(name, rows, dtype=np.int64)

    def get_scalar(self, name: str, rows: Any = None, units: str | None = None) -> np.ndarray:
        return self._in_units(name, self._get(name, rows, dtype=self._result_dtype(name)), units)

    def get_constant(self, name: str, units: str | None = None) -> Any:
        d = self.describe(name)
        if d.get("dtype") == "int64" and units is None:
            return int(self._get(name, dtype=np.int64))
        return float(self._in_units(name, self._get(name), units))

    def get_cells(self, row: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rows = None if row is None else _one_row(row)
        return (self._get("cells/types", rows, dtype=np.uint8),
                self._get("cells/offsets", rows, dtype=np.int64),
                self._get("cells/connectivity", rows, dtype=np.int64))

    def get_points(self, row: int | None = None, units: str | None = None) -> np.ndarray:
        if row is None and self._per not in ("fixed",):
            raise GamutError("", "this mesh's geometry changes; give the row")
        rows = None if row is None else _one_row(row)
        out = self._get("coordinates", rows, dtype=self._coordinate_dtype(), squeeze_row=False)
        if row is not None and self._mesh_kind == "shared":
            out = out[0]
        return self._in_units("coordinates", out, units)

    def get_field(self, name: str, rows: Any = None, nodes: Any = None, cells: Any = None,
                  units: str | None = None) -> np.ndarray:
        sites = nodes if nodes is not None else cells
        if self._mesh_kind == "changing":
            one = isinstance(rows, (list, tuple, np.ndarray)) and len(rows) == 1
            if not one and (rows is None or _lib.iterable(rows) or isinstance(rows, slice)):
                raise GamutError("", f"{name}: a changing mesh is read one row at a time; "
                                      "reads across rows need a shared mesh")
            rows = list(rows) if one else _one_row(rows)
        # A changing mesh's field has no row axis (one row at a time).
        return self._in_units(name, self._get(name, rows, sites, dtype=self._result_dtype(name),
                                              squeeze_row=self._mesh_kind != "changing"),
                              units)

    def get_mesh_label(self, name: str, row: int | None = None) -> np.ndarray:
        rows = None if row is None else _one_row(row)
        return self._get(name, rows, dtype=np.int64, squeeze_row=False)

    def categories(self, name: str) -> list[str]:
        """The category table of a label or mesh label: code c names entry c."""
        table = self.describe(name).get("category")
        if not table:
            raise GamutError("", f"{name} has no category table; its codes are its values")
        return _lib.strings_out("gamut_table", self._handle(), b(table))

    def table(self, names: Sequence[str] | None = None, rows: Any = None) -> dict[str, np.ndarray]:
        """The run table as columns: parameters, labels (as names), scalars."""
        self._need_reader()
        if names is None:
            names = self.names("parameters") + self.names("labels") + self.names("scalars")
        labels = set(self.names("labels"))
        params = set(self.names("parameters"))
        out: dict[str, np.ndarray] = {}
        for n in names:
            if n in labels:
                out[n] = self.get_label(n, rows)
            elif n in params:
                out[n] = self.get_parameter(n, rows)
            else:
                out[n] = self.get_scalar(n, rows)
        return out

    # --- notes and private records ---------------------------------------------

    @property
    def notes(self) -> Any:
        """Free-form public notes: a dict when reading; assign items when
        writing (`study.notes["solver"] = "OpenFOAM v2406"`)."""
        if self._writing:
            return _NotesWriter(self)
        keys, kinds, values = [], [], []
        k, t, v = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        call("gamut_notes", self._handle(), ctypes.byref(k), ctypes.byref(t), ctypes.byref(v))
        try:
            for h, dst in ((k, keys), (t, kinds), (v, values)):
                for i in range(_lib._lib.gamut_strings_count(h)):
                    dst.append(_lib._lib.gamut_strings_get(h, i).decode("utf-8"))
        finally:
            for h in (k, t, v):
                _lib._lib.gamut_strings_free(h)
        cast = {"int": int, "float": float, "bool": lambda x: x == "1", "text": str}
        return {key: cast[kind](val) for key, kind, val in zip(keys, kinds, values)}

    def set_private(self, name: str, data: bytes) -> None:
        """A producer's own record: bytes no other reader interprets."""
        self._need_writer()
        buf = bytes(data)
        call("gamut_set_private", self._handle(), b(name), buf, len(buf))

    def private_names(self) -> list[str]:
        self._need_reader()
        return _lib.strings_out("gamut_private_names", self._handle())

    def get_private(self, name: str) -> bytes:
        self._need_reader()
        n = ctypes.c_int64()
        call("gamut_get_private", self._handle(), b(name), None, 0, ctypes.byref(n))
        out = ctypes.create_string_buffer(max(n.value, 1))
        call("gamut_get_private", self._handle(), b(name), out, n.value, ctypes.byref(n))
        return out.raw[: n.value]

    def _in_units(self, name: str, values: np.ndarray, units: str | None) -> np.ndarray:
        if units is None:
            return values
        have = self.describe(name).get("units", "")
        return _units.convert(values, have, units)

    def select(self, where: str) -> np.ndarray:
        """The positions of the rows `where` selects, e.g.
        "mach > 0.5 and status == converged" (docs/reference/selecting.md)."""
        self._need_reader()
        out = np.empty(max(self.row_count, 1), dtype=np.int64)
        n = ctypes.c_int64()
        call("gamut_select", self._handle(), b(where), out.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
             out.size, ctypes.byref(n))
        return out[: n.value].copy()

    def related(self, name: str) -> dict[str, Any]:
        """What describes `name`: its std, quantiles, derivatives, and the
        other parts of its vector."""
        self._need_reader()
        out: dict[str, Any] = {"std": None, "quantiles": {}, "derivatives": {}, "vector": []}
        mine = self.describe(name)
        for group in ("scalars", "node_fields", "cell_fields"):
            for other in self.names(group):
                d = self.describe(other)
                if d.get("of") == name:
                    if d.get("statistic") == "std":
                        out["std"] = other
                    elif d.get("statistic") == "quantile":
                        out["quantiles"][float(d["q"])] = other
                    elif d.get("with_respect_to"):
                        wrt = d["with_respect_to"]
                        if wrt == "coordinates":
                            wrt = f"coordinates:{d.get('axis', '')}"
                        out["derivatives"][wrt] = other
                if mine.get("vector") and d.get("vector") == mine.get("vector"):
                    out["vector"].append(other)
        return out

    def _result_dtype(self, name: str) -> Any:
        return np.float32 if self.describe(name).get("dtype") == "float32" else np.float64

    def _coordinate_dtype(self) -> Any:
        return np.float32 if self.describe("coordinates").get("dtype") == "float32" else np.float64


class _NotesWriter:
    """`study.notes[key] = value` while writing: text, integers, floats."""

    def __init__(self, study: Study) -> None:
        self._study = study

    def __setitem__(self, key: str, value: Any) -> None:
        h = self._study._handle()
        if isinstance(value, bool) or isinstance(value, (int, np.integer)):
            call("gamut_set_note_int", h, b(key), int(value))
        elif isinstance(value, (float, np.floating)):
            call("gamut_set_note_float", h, b(key), float(value))
        elif isinstance(value, str):
            call("gamut_set_note_text", h, b(key), b(value))
        else:
            raise GamutError("", f"a note is text, an integer or a float, not {type(value).__name__}")


def create(path: str, *, writer: str, parameters: Mapping[str, Any] | None = None,
           labels: Mapping[str, Any] | None = None, scalars: Mapping[str, Any] | None = None,
           fields: Mapping[str, Any] | None = None, mesh_labels: Mapping[str, Any] | None = None,
           constants: Mapping[str, Any] | None = None, mesh: str | None = None,
           per: str | None = None, coordinates: Mapping[str, Any] | None = None,
           precision: Mapping[str, Any] | None = None, round_bits: Mapping[str, int] | None = None,
           title: str | None = None, license: str | None = None, references: str | None = None,
           source: str | None = None, generalisation_group: str | None = None,
           compression: bool = True) -> Study:
    """Creates a data file and returns it open to add runs."""
    if mesh is not None and per is None:
        raise GamutError("E6", "a mesh needs per: 'fixed', 'run' or 'group:<label>'")
    axes = _axes(coordinates)        # before the file exists: a refusal leaves none
    handle = ctypes.c_void_p()
    call("gamut_create", b(path), b(writer), b(mesh or ""), b(per or "fixed"), ctypes.byref(handle))
    study = Study(handle, path, writing=True)
    study._mesh_kind = mesh or ""
    study._per = per or ""
    study._group = per[6:] if per and per.startswith("group:") else None
    study._axes = axes
    try:
        for group in (parameters, scalars):
            for name, value in (group or {}).items():
                study._declared_units[name] = _spec(value, "units").get("units", "")
        precision = dict(precision or {})
        round_bits = dict(round_bits or {})
        if not compression:
            call("gamut_set_compression", handle, 0, 0)
        for key, value in (("title", title), ("license", license),
                           ("references", references), ("source", source)):
            if value is not None:
                call("gamut_set_attribute", handle, b(key), b(value))
        for name, value in (labels or {}).items():
            if value is bool:
                spec = {"role": "categorical", "categories": ["false", "true"]}
            elif isinstance(value, str):
                spec = {"role": value}
            else:
                spec = dict(value)
            cats = list(spec.get("categories", []))
            call("gamut_declare_label", handle, b(name), b(spec.get("role", "categorical")),
                 _lib.string_array(cats), len(cats))
        for name, value in (parameters or {}).items():
            spec = _spec(value, "units")
            has = "lower" in spec or "upper" in spec
            call("gamut_declare_parameter", handle, b(name), b(spec.get("role", "design")),
                 b(spec.get("units")), _precision(precision.get(name, spec.get("dtype"))),
                 1 if has else 0, float(spec.get("lower", 0.0)), float(spec.get("upper", 0.0)),
                 b(spec.get("run_group", "")))
        if coordinates is not None:
            call("gamut_declare_coordinates", handle, b(coordinates.get("units")),
                 _precision(coordinates.get("precision")), int(coordinates.get("axes", 3)),
                 b(coordinates.get("model", "")), b(coordinates.get("output", "")))
        for name, value in (mesh_labels or {}).items():
            spec = dict(value)
            cats = list(spec.get("categories", []))
            call("gamut_declare_mesh_label", handle, b(name), b(spec.get("at", "cell")),
                 _lib.string_array(cats), len(cats))

        def declare(name: str, spec: dict, where: str) -> None:
            q = spec.get("q")
            call("gamut_declare_result", handle, b(name), b(where), b(spec.get("units")),
                 _precision(precision.get(name, spec.get("precision"))),
                 b(spec.get("of", "")), b(spec.get("statistic", "")), 0 if q is None else 1,
                 float(q or 0.0), b(spec.get("method", "")), b(spec.get("with_respect_to", "")),
                 b(spec.get("axis", "")), b(spec.get("vector", "")),
                 int(round_bits.get(name, spec.get("round_bits", -1))),
                 b(spec.get("model", "")), b(spec.get("output", "")))

        for name, value in (scalars or {}).items():
            declare(name, _spec(value, "units"), "scalar")
        for name, value in (fields or {}).items():
            spec = _spec(value, "units")
            declare(name, spec, spec.get("at", "node"))
        if generalisation_group is not None:
            call("gamut_set_generalisation_group", handle, b(generalisation_group))
        for name, value in (constants or {}).items():
            number, units = value
            if isinstance(number, np.float32):
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_FLOAT32, float(number), 0)
            elif isinstance(number, (int, np.integer)) and not isinstance(number, bool):
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_INT64, 0.0, int(number))
            else:
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_FLOAT64, float(number), 0)
    except BaseException:
        # A half-declared file is not wanted; the declaration error stands.
        study._abandon(remove=True)
        raise
    return study


def open(path: str, mode: str = "r", threads: int = 1) -> Study:  # noqa: A001
    """Opens a file to read (mode "r") or to add runs in place (mode "a").
    `threads` decompresses field reads in that many threads."""
    handle = ctypes.c_void_p()
    if mode == "r":
        call("gamut_open", b(path), ctypes.byref(handle))
        if threads != 1:
            call("gamut_set_threads", handle, int(threads))
        return Study(handle, path, writing=False)
    if mode == "a":
        reader = open(path, "r")
        kind, per = reader._mesh_kind, reader._per
        declared = {n: reader.describe(n).get("units", "")
                    for n in reader.names("parameters") + reader.names("scalars")}
        reader.close()
        call("gamut_open_append", b(path), ctypes.byref(handle))
        study = Study(handle, path, writing=True)
        study._mesh_kind, study._per = kind, per
        study._group = per[6:] if per.startswith("group:") else None
        study._declared_units = declared
        return study
    raise GamutError("", f"mode {mode!r} is 'r' or 'a'")
