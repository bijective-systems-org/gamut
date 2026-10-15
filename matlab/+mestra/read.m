function d = read(path, varargin)
%MESTRA.READ  Read a mestra file into a mestra.Dataset.
%
%   D = MESTRA.READ(PATH) reads everything: the keys with their roles
%   and bounds, the scalars, the supports with their coordinates, cell
%   types, offsets, connectivity, labels and ids, the node and cell
%   arrays, the category tables, the alignment flag, the per-row
%   support column, the callables and the metadata.
%
%   AXIS ORDER.  HDF5 stores an array in C order and MATLAB is column
%   major, so every array comes back with its axes REVERSED with
%   respect to the file.  A node array stored as
%
%       (row, node, component)
%
%   is returned as a MATLAB array of size
%
%       (component, node, row)
%
%   and its `dims` field names those axes in that same order.  This is
%   correct and expected (specification section 4): what two readers
%   in two languages must agree on is the value at (row r, node n,
%   component c), found by the dimension names and never by the axis
%   positions.  Use MESTRA.PERMUTE to get the order you want.
%
%       d = mestra.read('mesh_two_rows.mes');
%       a = d.nodeArray('s0', 'pressure');
%       a.dims                          % {'component', 'node', 'row'}
%       p = mestra.permute(a.values, a.dims, {'row', 'node', 'component'});
%       p(2, 4, 1)                      % 204
%
%   UNTRUSTED INPUT.  A file this package did not write is not
%   trusted.  A link that is not a hard link is never followed, an
%   object that cannot be read is never guessed at, nesting is
%   bounded, and an eager read refuses a dataset above
%   mestra.limits('maxElements').  By default such a file is REFUSED
%   rather than half read, and the identifier is mestra: followed by
%   the rule, or mestra:reader for a file that will not open at all.
%   These are the nine structural rules a strict read refuses on
%   (section 2 of docs/api-conventions.md), and they are the only
%   ones: a semantic fault never stops a read, so that info and
%   validate work on the files a user most needs to inspect.
%
%       E01   a file whose format names another major version, which
%             section 28 says must not be read even partially
%       E16   a leading extent that disagrees with the row dimension
%             it is attached to, so the dataset cannot be lined up
%             against the keys
%       E19   an attribute not encoded as section 18 requires: a
%             variable-length string, an array where a scalar
%             belongs, an integer that is not int64, a float that is
%             not float64, a boolean holding anything but 0 or 1
%       E25   an axis with no dimension scale, with more than one, or
%             with one this reader cannot name
%       E26   a string whose bytes are not valid UTF-8, or that holds
%             a NUL anywhere but in its trailing padding
%       E29   a filter that is not gzip or shuffle, which section 23
%             tells a reader to refuse
%       E30   a slot whose source says data and which is stored as a
%             group, or which names a callable and is stored as a
%             dataset; section 19 makes the two tell themselves apart
%             without reading any data
%       E40   a link in the public tree that is not a hard link: a
%             soft link, whether it resolves, dangles or loops, or an
%             external link, which names another file.  None is ever
%             followed
%       E41   an object the reader could not read, with its path: a
%             malformed header or attribute, a member of the wrong
%             kind, nesting past maxDepth, a group already visited in
%             this walk, or, on an eager read only, a dataset above
%             maxElements or a string wider than maxStringSize
%
%   D = MESTRA.READ(PATH, 'Strict', false) returns what could be read
%   instead, with one line in D.skipped for everything passed over.
%   An attribute or a group this version does not know is always
%   ignored, kept, and reported by MESTRA.VALIDATE as W11.
%
%   STRINGS ARE ASCII HERE.  A string whose stored bytes go above
%   127 raises mestra:matlabAscii rather than coming back corrupted;
%   MATLAB's HDF5 interface decodes a fixed-length string before this
%   package sees it and will not hand over the bytes.  `help
%   mestra.write` says why, and why there is no way round it from
%   inside MATLAB.
%
%   MESTRA.OPEN reads metadata while deferring slot values and callable-
%   dictionary datasets. Category tables and /row_support may be read,
%   as API conventions section 7 and specification section 29 state.
%
%   See also mestra.open, mestra.write, mestra.validate,
%   mestra.evaluate, mestra.permute, mestra.Dataset.

    strict = mestra.internal.Reader.strictOption(varargin);
    d = mestra.internal.Reader.load(path, true, strict);
end
