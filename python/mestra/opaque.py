"""Keeping a group this reader must not interpret.

Section 12 gives a file a `private` group for a producer's own
records, and section 28 lets a version add groups an older reader
does not know. Both must be ignored, not failed on, and a reader
that rewrites a file should not silently drop them. This module
copies such a group into memory as it stands and puts it back
unchanged.

Nothing here interprets what it copies, and nothing here trusts it
either: the walk follows no link, goes no deeper than
`limits.MAX_DEPTH`, and copies no dataset larger than
`limits.MAX_READ_ELEMENTS`. What it could not copy is reported as a
finding and named in the dataset's `lossy` list, and `write` refuses
while any remain rather than writing the file short.

Two things about the copy are worth stating, because both are about
not interpreting what is copied.

The values wait. An open reads attributes, dataspaces and link
types, and section 29 says it "must not read any array"; a private
group is somebody's array like any other, and a file whose /private
holds a gigabyte must still open in the time an open costs. So a
lazy open records each dataset's shape, type, storage and
attachments and leaves the bytes in the file until something asks
for them, which in practice is a rewrite. What a read cannot do
without -- the size limit, the depth cap, a link it will not follow
-- is still decided at open, from the dataspace, so `lossy` says at
open what a rewrite would lose. An eager read reads the values with
everything else.

Dimension scales inside a copied group are kept as they are, and so
is each dataset's attachment to them, because dropping them would
change the file in a way section 30's structural equality sees: the
scale would come back as a plain dataset and the axis it named would
have no dimension. A scale is copied with its CLASS and NAME as they
stand, and the attachments are made after every member exists.
Nothing here decides what a scale of this group means; it decides
only that the file gets back what it gave. An axis attached to a
scale outside the copied group is put back by that scale's link
name, looked for where the group hangs and then at the root, which
is where the file-level scales of section 21 are; one that is
neither is left unattached, because this walk cannot name it without
searching the hierarchy, and section 21 forbids that.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import h5py
import numpy as np

from . import h5safe, limits
from .errors import Finding, MestraError

__all__ = ["capture", "restore", "read_all", "capture_member",
           "restore_member", "read_member", "Attribute",
           "capture_attribute", "capture_attributes", "restore_attribute"]

#: What a member is replaced by when it could not be copied.
LOST = "mestra.opaque.lost"

#: What a member's data is while it is still in the file.
UNREAD = "mestra.opaque.unread"


def capture(group: h5py.Group, path: str = "", depth: int = 0,
            problems: list[Finding] | None = None,
            lossy: list[str] | None = None, lazy: bool = False,
            scales: Mapping[int, str] | None = None) -> dict[str, Any]:
    """Copy a group, its attributes and its members, into memory.

    With `lazy` the values are left in the file until `read_all` or a
    rewrite asks for them; everything else is read here. `scales` is
    the pass's scale index (section 21), used to name a scale
    attached from outside this group.
    """
    walk = _Walk(problems, lossy, lazy, scales or {})
    out = walk.group(group, path or group.name, depth, "")
    walk.resolve()
    return out


def read_all(captured: dict[str, Any]) -> None:
    """Read every value a lazy capture left in the file."""
    for kind, body in captured["members"].values():
        if kind == "group":
            read_all(body)
        else:
            values(body)


def values(body: dict[str, Any]) -> Any:
    """One captured dataset's values, reading them if a lazy capture
    left them in the file."""
    if isinstance(body["data"], str) and body["data"] == UNREAD:
        dset = body.pop("dset", None)
        where = body.get("where", "")
        if dset is None:                                # pragma: no cover
            raise MestraError("E41", "this dataset was never copied "
                                     "and cannot be read now", where)
        try:
            body["data"] = (h5safe.read_values(dset, where)
                            if dset.size
                            else np.zeros(dset.shape, dset.dtype))
        except MestraError:
            body["data"] = LOST
            raise
        except Exception:
            body["data"] = LOST
            raise MestraError(
                "E41", "this dataset cannot be copied", where) from None
    return body["data"]


class _Walk:
    """One copy of one group, and what it found on the way."""

    def __init__(self, problems: list[Finding] | None,
                 lossy: list[str] | None, lazy: bool,
                 scales: Mapping[int, str]) -> None:
        self.problems = problems
        self.lossy = lossy
        self.lazy = lazy
        self.scales = scales
        #: Every scale inside the copied group, by its address, with
        #: the path it has inside the group.
        self.here: dict[int, str] = {}
        #: Every dataset copied, with the addresses attached to its
        #: axes, which `resolve` turns into names.
        self.attached: list[tuple[dict[str, Any], list[int | None]]] = []

    def group(self, group: h5py.Group, path: str, depth: int,
              inside: str) -> dict[str, Any]:
        out: dict[str, Any] = {"attrs": _attrs(group), "members": {}}
        if depth > limits.MAX_DEPTH:
            self.lost(path, "this group nests more than %d levels "
                            "deep, which this reader does not follow"
                      % limits.MAX_DEPTH)
            return out
        for member in h5safe.members(group):
            where = "%s/%s" % (path.rstrip("/"), member.name)
            under = "%s/%s" % (inside, member.name) if inside \
                else member.name
            if not member.usable:
                self.lost(where, member.problem
                          or "this member cannot be read", member.rule)
                continue
            if isinstance(member.obj, h5py.Group):
                out["members"][member.name] = (
                    "group", self.group(member.obj, where, depth + 1,
                                        under))
                continue
            out["members"][member.name] = (
                "dataset", self.dataset(member.obj, where, under))
        return out

    def dataset(self, dset: h5py.Dataset, where: str,
                under: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "attrs": _attrs(dset),
            "dtype": dset.dtype,
            "shape": dset.shape,
            "maxshape": dset.maxshape,
            "chunks": dset.chunks,
            "compression": dset.compression,
            "compression_opts": dset.compression_opts,
            "shuffle": dset.shuffle,
            "fletcher32": dset.fletcher32,
            "scale": h5safe.is_scale(dset),
            "dims": [],
            "where": where,
            "data": None,
        }
        if h5safe.is_scale(dset):
            self.here[h5safe.address(dset) or -1] = under
        else:
            self.attached.append((body, _attached(dset)))
        self.read(dset, body, where)
        return body

    def read(self, dset: h5py.Dataset, body: dict[str, Any],
             where: str) -> None:
        """The values, or a note of why there are none.

        The size limit is decided here in both modes, from the
        dataspace and without reading: a dataset this reader will
        not materialise is one a rewrite would lose, and `lossy`
        must say so when the file is opened.
        """
        try:
            h5safe.check_size(dset, where)
        except MestraError as exc:
            body["data"] = LOST
            self.lost(where, exc.message)
            return
        if self.lazy:
            body["data"] = UNREAD
            body["dset"] = dset
            return
        try:
            body["data"] = (h5safe.read_values(dset, where) if dset.size
                            else np.zeros(dset.shape, dset.dtype))
        except MestraError as exc:
            body["data"] = LOST
            self.lost(where, exc.message)
        except Exception:
            body["data"] = LOST
            self.lost(where, "this dataset cannot be copied")

    def resolve(self) -> None:
        """Name the scale on each axis, now that the whole group has
        been walked and every scale inside it is known."""
        for body, addresses in self.attached:
            dims: list[tuple[str, str] | None] = []
            for at in addresses:
                if at is None:
                    dims.append(None)
                elif at in self.here:
                    dims.append(("here", self.here[at]))
                elif at in self.scales:
                    dims.append(("named", self.scales[at]))
                else:
                    dims.append(None)
            body["dims"] = dims

    def lost(self, where: str, message: str, rule: str = "E41") -> None:
        if self.problems is not None:
            self.problems.append(Finding(rule, where, message))
        if self.lossy is not None:
            self.lossy.append(where)


def _attached(dset: h5py.Dataset) -> list[int | None]:
    """The address of the one scale on each axis, or None.

    An address and never a path: asking the library for the path of
    an attached scale searches the group hierarchy, which section 21
    says runs off the stack on a deep file.
    """
    out: list[int | None] = []
    try:
        dims = dset.dims
    except Exception:                                   # pragma: no cover
        return out
    for dim in dims:
        try:
            out.append(h5safe.address(dim[0]) if len(dim) else None)
        except Exception:                               # pragma: no cover
            out.append(None)
    return out


def _attrs(obj: Any) -> dict[str, tuple[Any, Any]]:
    out = {}
    for name in h5safe.attr_names(obj):
        if name in ("DIMENSION_LIST", "REFERENCE_LIST"):
            # Object references into the file being read. What they
            # say is kept as `dims` and written again by attaching.
            continue
        try:
            out[name] = _attr_copy(obj, name)
        except Exception:
            continue
    return out


def _attr_copy(obj: Any, name: str) -> tuple[Any, Any]:
    """One attribute as it is stored. A fixed-length string keeps its
    HDF5 type, because its character set and its padding are part of
    it and a numpy dtype carries neither; its bytes are read through
    that same type, so nothing is converted on the way."""
    attr = obj.attrs.get_id(name)
    kind = attr.get_type()
    if isinstance(kind, h5py.h5t.TypeStringID) and \
            not kind.is_variable_str():
        raw = np.empty(attr.shape, dtype="S%d" % kind.get_size())
        attr.read(raw, mtype=kind)
        return raw, kind
    return obj.attrs[name], attr.dtype


def restore(parent: h5py.Group, name: str,
            captured: dict[str, Any]) -> h5py.Group:
    """Write a captured group back under `parent`."""
    group = parent.create_group(name)
    _put_attrs(group, captured["attrs"])
    made: dict[str, h5py.Dataset] = {}
    _put_members(group, captured, "", made)
    _attach(group, parent, captured, "", made)
    return group


def _put_members(group: h5py.Group, captured: dict[str, Any],
                 inside: str, made: dict[str, h5py.Dataset]) -> None:
    for member, (kind, body) in captured["members"].items():
        under = "%s/%s" % (inside, member) if inside else member
        if kind == "group":
            below = group.create_group(member)
            _put_attrs(below, body["attrs"])
            _put_members(below, body, under, made)
        else:
            made[under] = _put_dataset(group, member, body)


def _attach(group: h5py.Group, parent: h5py.Group,
            captured: dict[str, Any], inside: str,
            made: Mapping[str, h5py.Dataset]) -> None:
    """Put back each axis's scale, once every member exists."""
    for member, (kind, body) in captured["members"].items():
        under = "%s/%s" % (inside, member) if inside else member
        if kind == "group":
            _attach(group[member], parent, body, under, made)
            continue
        for axis, dim in enumerate(body.get("dims") or []):
            if dim is None:
                continue
            kind_of, where = dim
            scale = (made.get(where) if kind_of == "here"
                     else _by_name(parent, where))
            if scale is None:
                continue
            try:
                made[under].dims[axis].attach_scale(scale)
            except Exception:                           # pragma: no cover
                continue


def _by_name(parent: h5py.Group, name: str) -> h5py.Dataset | None:
    """A scale this group's datasets were attached to from outside,
    where it hangs and then at the root: the two places section 21
    puts a scale a dataset may name."""
    for group in (parent, parent.file):
        try:
            found = group.get(name)
        except Exception:                               # pragma: no cover
            continue
        if isinstance(found, h5py.Dataset) and h5safe.is_scale(found):
            return found
    return None


def _put_attrs(obj: Any, attrs: dict[str, tuple[Any, Any]]) -> None:
    for name, (value, dtype) in attrs.items():
        if isinstance(dtype, h5py.h5t.TypeStringID):
            space = (h5py.h5s.create(h5py.h5s.SCALAR) if value.shape == ()
                     else h5py.h5s.create_simple(value.shape))
            attr = h5py.h5a.create(obj.id, name.encode("utf-8"), dtype,
                                   space)
            attr.write(value, mtype=dtype)
            continue
        obj.attrs.create(name, value, dtype=dtype)


def _put_dataset(group: h5py.Group, name: str,
                 body: dict[str, Any]) -> h5py.Dataset:
    if isinstance(body["data"], str) and body["data"] == LOST:
        raise MestraError(
            "E41", "this dataset could not be copied when the file "
            "was read, so it cannot be written back", name)
    data = values(body)
    kw: dict[str, Any] = {}
    if body["chunks"] is not None:
        kw["chunks"] = body["chunks"]
    if body["maxshape"] != body["shape"]:
        kw["maxshape"] = body["maxshape"]
    if body["compression"] is not None:
        kw["compression"] = body["compression"]
        kw["compression_opts"] = body["compression_opts"]
    if body["shuffle"]:
        kw["shuffle"] = True
    if body["fletcher32"]:
        kw["fletcher32"] = True
    dset = group.create_dataset(name, shape=body["shape"],
                                dtype=body["dtype"], data=data,
                                track_times=False, **kw)
    _put_attrs(dset, body["attrs"])
    return dset


# ------------------------------------------- one member at the root

def capture_member(obj: Any, path: str,
                   problems: list[Finding] | None = None,
                   lossy: list[str] | None = None, lazy: bool = False,
                   scales: Mapping[int, str] | None = None
                   ) -> tuple[str, dict[str, Any]]:
    """Copy one dataset or group this reader does not interpret, such
    as a root object with a role it does not know. Returns the kind
    ("dataset" or "group") and the copy."""
    if isinstance(obj, h5py.Group):
        return "group", capture(obj, path, 0, problems, lossy, lazy,
                                scales)
    walk = _Walk(problems, lossy, lazy, scales or {})
    body = walk.dataset(obj, path, path.rsplit("/", 1)[-1])
    walk.resolve()
    return "dataset", body


def read_member(kind: str, body: dict[str, Any]) -> None:
    """Read every value a lazy `capture_member` left in the file."""
    if kind == "group":
        read_all(body)
    else:
        values(body)


def restore_member(parent: h5py.Group, name: str, kind: str,
                   body: dict[str, Any]) -> None:
    """Write a `capture_member` copy back under `parent`, attaching a
    dataset's axes to scales by name where it hangs or at the root."""
    if kind == "group":
        restore(parent, name, body)
        return
    dset = _put_dataset(parent, name, body)
    for axis, dim in enumerate(body.get("dims") or []):
        if dim is None:
            continue
        scale = _by_name(parent, dim[1])
        if scale is not None:
            try:
                dset.dims[axis].attach_scale(scale)
            except Exception:                           # pragma: no cover
                continue


# ------------------------------------------------ one attribute, exact

class Attribute:
    """An attribute this reader does not interpret, kept as stored.

    `string` says how: ("typed", type) for any fixed-size type, with
    the value as its raw bytes and the HDF5 type serialised, so byte
    order, enum names, compound members and string padding all come
    back; ("vlen", character set) for a variable-length string, kept as
    text; ("empty", type) for an attribute with no dataspace. Plain
    data, so a dataset holding one copies and deep-copies."""

    __slots__ = ("value", "string", "shape")

    def __init__(self, value: Any, string: Any = None,
                 shape: Any = None) -> None:
        self.value = value
        self.string = string
        self.shape = shape

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Attribute):
            return NotImplemented
        if (self.string, self.shape) != (other.string, other.shape):
            return False
        if isinstance(self.value, np.ndarray) and \
                self.value.dtype.kind == "V":
            return bool(self.value.tobytes() == np.asarray(
                other.value).tobytes())
        return bool(np.array_equal(np.asarray(self.value, dtype=object),
                                   np.asarray(other.value, dtype=object)))

    def __repr__(self) -> str:
        return "Attribute(%s)" % (self.string[0] if self.string else "?")


def _copyable(kind: Any) -> bool:
    """False for a type whose bytes mean nothing in another file: a
    reference, or variable-length data other than a string, at any
    depth of a compound or an array."""
    cls = kind.get_class()
    if cls in (h5py.h5t.REFERENCE, h5py.h5t.VLEN):
        return False
    if cls == h5py.h5t.COMPOUND:
        return all(_copyable(kind.get_member_type(at))
                   for at in range(kind.get_nmembers()))
    if cls == h5py.h5t.ARRAY:
        return _copyable(kind.get_super())
    if cls == h5py.h5t.STRING:
        return not kind.is_variable_str()
    return True


def capture_attribute(obj: Any, name: str) -> Attribute:
    """One attribute exactly as stored. Raises (E41) for a type this
    reader cannot copy exactly, so that the caller refuses a rewrite
    rather than drop or change it."""
    attr = obj.attrs.get_id(name)
    kind = attr.get_type()
    if attr.get_space().get_simple_extent_type() == h5py.h5s.NULL:
        return Attribute(None, ("empty", kind.encode()))
    if isinstance(kind, h5py.h5t.TypeStringID) and kind.is_variable_str():
        return Attribute(obj.attrs[name], ("vlen", kind.get_cset()),
                         tuple(attr.shape))
    if not _copyable(kind):
        raise MestraError("E41", "the attribute %s is of a type this reader "
                                 "cannot copy (a reference or "
                                 "variable-length data)" % name)
    shape = tuple(attr.shape)
    raw = np.empty(shape, dtype="V%d" % kind.get_size())
    attr.read(raw, mtype=kind)
    return Attribute(raw, ("typed", kind.encode()), shape)


def capture_attributes(obj: Any, known: Any, where: str,
                       problems: list[Finding] | None = None,
                       lossy: list[str] | None = None
                       ) -> dict[str, Attribute]:
    """Every attribute of `obj` not in `known` (and not the machinery of
    the dimension scales), exactly as stored. One that cannot be read
    is a finding and makes `where` lossy, so a rewrite refuses rather
    than drop it."""
    out: dict[str, Attribute] = {}
    for name in h5safe.attr_names(obj):
        if name in known:
            continue
        try:
            out[name] = capture_attribute(obj, name)
        except Exception as exc:
            message = exc.message if isinstance(exc, MestraError) else \
                "the attribute %s cannot be copied" % name
            if problems is not None:
                problems.append(Finding("E41", where, message))
            if lossy is not None:
                lossy.append(where)
    return out


def restore_attribute(obj: Any, name: str, attribute: Attribute) -> None:
    """Write a captured attribute back exactly as it was stored."""
    string = attribute.string
    if string[0] == "vlen":
        encoding = "utf-8" if string[1] == h5py.h5t.CSET_UTF8 else "ascii"
        obj.attrs.create(name, attribute.value, shape=attribute.shape,
                         dtype=h5py.string_dtype(encoding))
        return
    kind = h5py.h5t.decode(string[1])
    if string[0] == "empty":
        h5py.h5a.create(obj.id, name.encode("utf-8"), kind,
                        h5py.h5s.create(h5py.h5s.NULL))
        return
    space = (h5py.h5s.create(h5py.h5s.SCALAR) if attribute.shape == ()
             else h5py.h5s.create_simple(attribute.shape))
    made = h5py.h5a.create(obj.id, name.encode("utf-8"), kind, space)
    made.write(attribute.value, mtype=kind)
