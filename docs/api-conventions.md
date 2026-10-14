API conventions across the four implementations
================================================

These are conventions for the reader, writer, builder, and helper
APIs; they do not change the file format. Every implementation
follows them, so a user moving between languages meets the same
names, the same order,
the same defaults, and the same messages. Where a language's idiom
forces a difference (keyword arguments, name-value pairs, a struct),
the shared operation retains its meaning. Available helpers and
implementation limits are listed in `compatibility.md` and each
language's README; this convention is not a claim that every helper
ships in every language.


1. Building
-----------

Keys: `add_key(name, values, role, units)` in that order. The role and
the units are required for design, condition, and time keys. A
categorical, group, split, or status key takes `category` naming
its table instead of units. An id key stores unique integer or string
identifiers and requires neither units nor a category table.
Bounds: when the caller gives none, the
builder records the observed finite minimum and maximum as `lower`
and `upper`, so that every writer produces the same file from the same
arrays and W04 and W08 are decidable on every file. A caller who wants
a wider domain of validity passes `lower` and `upper` explicitly.

Category tables: one way per language, `add_category_table(name,
entries)` before the key or label that uses it; the key or label then
names it with `category`. This is the explicit form the documents use;
an inline convenience such as Python's `categories=` may create that
same table before adding the key.

The unit of generalisation: a dataset property, set by
`set_generalisation_group(name)` (spelled to the language's idiom),
naming a key of role group. A language may keep a key-level shortcut
as sugar, but the dataset-level setter exists everywhere and is the
one the documents show.

Scalars: `add_scalar(name, values, units)`.

Arrays: `add_node_array(support, name, values, units, dims)` and
`add_cell_array(...)` with the same order. `dims` names the axes of
the array the caller passes, in the caller's own axis order; the
builder derives `varies` from `dims` (a `row` axis means row, a
`group:<k>` axis means that group, neither means none) and derives
`components` from the component axis or adds a component axis of
length one. A caller who passes `varies` as well as `dims` gets an
error at build time if they disagree. Builders refuse invalid arguments
they can decide at that call, with the rule id; the model message is
Python's for E04. Whole-dataset invariants still need validation and a
checked write.

Callables: `add_callable(id, callable)` then `add_callable_slot(...)`
with the same argument order as the array builders plus `callable`
and `output`. A band slot, stored or served, is the same builder
with `statistic="band"` and `of`; a stored one also takes `level` and
`method`, and is refused without them (E12). A mesh support's
coordinates are served the same way, by the coordinates builder with
the values dropped and `callable` and `output` added:
`set_callable_coordinates(support, units, dims | components,
callable, output)`, spelled to the language's idiom, on a mesh
support added with its node count and no coordinates. `output`
defaults to `coordinates`.


2. Writing and reading
----------------------

`write(dataset, path)` validates first and refuses on any error, with
the findings, unless the caller passes `check=false`. That option does
not bypass every writer refusal; see the preservation limits below.
Checked output must obey the shared public contract, within the
implementation capabilities in `compatibility.md`.

A checked write stages beside the destination, closes the file and
publishes it only on success. A prepublication failure preserves an
existing destination. There is no delete-then-copy fallback. This is
single-writer replacement, not concurrent-update coordination or a
power-loss durability promise. See `compatibility.md` for platform and
implementation requirements.

`read(path)` is strict by default and refuses a file that breaks a
structural rule (E01, E16, E19, E25, E26, E29, E30, E40, E41); a
non-strict read returns the dataset with the refused parts listed. A
semantic fault (a missing unit, a bad split) never stops a read, so
that `info` works on the files a user most needs to inspect.

`append_rows(rows, path, replace_by=)` grows a file by the rows of a
dataset built like a whole file, without rewriting the rows it holds.
The dataset must have the file's structure: the same keys, scalars,
supports and arrays with the same attributes, and the same values in
every array that does not vary by row; a category id is matched by its
entry's name, so a table built from the new rows alone maps onto the
file's, and an entry the file's table lacks is refused. Key bounds
widen to cover the new values, notes on the appended dataset replace
the file's, and `created`, `writer` and `/private` stay as they are.
The grown file is validated before it replaces the original, so a
failure of any kind leaves the original untouched, and it is what one
write of all the rows would have produced in content though not in
bytes: the chunk shapes are the ones the file was created with (W12
once they are no longer the default for the row count). `replace_by`
names the id key; a row sharing an existing row's id is written over
that row instead of after the last one. An unaligned file is not grown.
C++ carries this call; a language that adds it follows the same rules.


3. Weights and integration
--------------------------

The spec says a weight array is computed from connectivity and never
imported. Every implementation therefore provides
`compute_weights(support, location)`: cell measure (length, area,
volume by cell type) for cells, and the lumped share of adjacent cell
measure for nodes, stored as an array with role `weight`, units of
the coordinates raised to the support's dimension, and the
`recomputed` flag set. The array is named `weight` at both locations
unless the caller names it. `integrate(dataset, slot)` uses the weight
array at the slot's location on its support by default, and computes
one on the fly, saying so, when the file has none; `weight=` overrides
by name.


4. Post-processing
------------------

Where a language has the helpers, they take a slot by name and a label
by name: `field_statistics(dataset, slot, by=<label name>)`, with the
output keyed by the label's name (never a fixed word), and no grouping
column at all when `by` is not given. `time_series(dataset, slot,
node, trajectory)`. `grouped_split(dataset, fractions, seed)` assigns
whole units of generalisation to parts, never returns an empty part
when there are at least as many units as parts, takes a seed with a
documented default, and refuses without a declared unit of
generalisation. `split_leaks(dataset)` names the units of
generalisation that lie on both sides of a split: the unit by its
category name, each with the names of the split parts it lies in,
sorted; it refuses a file with no unit of generalisation or no split
key, because an empty answer means no leak and nothing else. A
language without the helpers says so in its README under a heading of
its own.


5. Validator output
-------------------

One finding per rule per object. A finding that could repeat per row
(W02, W03, W04) reports once with the count and the first three row
indices in its message. Each finding is printed as
`<id> <path>: <message>` and the run ends with
`<n> error(s), <m> warning(s)`; the command-line tools of every
language print exactly that. `info` prints, for every key: name, role,
units, bounds, category, trajectory group, parent; for every support:
kind, counts, id; for every slot: shape with named axes, units,
source, for callable slots the callable id and output, and for a band
its level and method.


6. Messages
-----------

An error names the rule id first, then the object path, then what to
do. A builder error says which argument to change. The models are the
Python E04 and W01 messages.


7. Questions the four languages once answered differently
----------------------------------------------------------

What an evaluated file carries. Evaluating a file turns every callable
slot into a stored slot, so the result has no callable to keep: the
`/callables` group is absent from an evaluated file, not present and
empty. This is the same rule as section 13's container groups, and it
keeps the four writers' output identical.

What a metadata open may read. Opening a file reads attributes,
dataspaces, link types, and dimension-scale structure, and may read a
category table in full, because tables are small by construction and
the open needs them to name E10, E26, and E41 on the same files the
read names them on. An open never reads a slot's data and never reads
a dataset inside a callable's dictionary; those wait for the read.
The nine structural rules of section 2 are decided from exactly this
much, so the open and the read name the same rule for the same file.

`/row_support` is the one other dataset an open reads. It is a
column of the file and not a slot: it says which support each row is
on, it is the length of the row count, and E16 in an unaligned file
is decided from it and from nothing else. So an open reads it in
full, as it reads a category table, and the list of what an open
reads is: attributes, dataspaces, link types, dimension-scale
structure, category tables and `/row_support`. Nothing else, and no
slot.

What an evaluated file does not carry. The `/private` group of the
file that was evaluated is not copied into the result. Evaluation
produces a new dataset, whose rows are the keys table it was given
and whose slots hold values that were not in the source; a producer's
private records describe the file they were written into, and
carrying them forward would attach them to numbers they are not
about. A producer that wants records on the result attaches its own
at write time. `/notes` is carried, because it is the format's own
optional text about the content, and the content is the same.

An unknown dataset inside a known group. Public byte-level rules still
apply: `err_e25_unknown_dataset` is a corpus example, and W11 does not
cover unknown datasets. A reader does not know their meaning, so the
interface convention requires listing what a rewrite cannot preserve
as lossy and refusing a checked rewrite rather than dropping it silently.
Current Python source does not establish complete inventory of unknown
public datasets; do not rely on a successful rewrite to prove retention.
`check=false` is not a portable conversion guarantee: Python refuses
a dataset with recorded lossy paths even with that option. See the
preservation limits in `compatibility.md`. Unknown *groups* have the
separate W11 and section 28 treatment; supported opaque content is preserved.


8. Predictions
--------------

A callable returns one record per output, a `Prediction` with the
fields `mean`, `uncertainty`, `level` and `method` (SPEC section 10).
Python, C++ and Julia spell it as a type of that name; MATLAB, which
cannot hold a class and a function of one name in one package, spells
it as a struct with those fields, built by
`mestra.Callable.prediction`. Building one refuses a band without its
level in (0, 1) or its method, of another shape than the mean, or
negative anywhere, so a malformed record never reaches a file.

`prediction(dataset, slot, keys)` is the one question a viewer asks:
for a stored slot the mean is its data and the band is the band slot
at the same location that names it with `of`, and `keys` is refused;
for a served slot the callable is called on `keys`, or on the file's
own rows when `keys` is omitted, and its record is returned as it is.
A band slot, or a std, quantile or draw slot, is refused: name the
base slot. Evaluation follows the same rule in every language: a slot
whose statistic is `value` or `mean`, or none, takes the mean; a
`band` slot takes the uncertainty and is given the record's level and
method; a band slot whose output has no uncertainty is refused with
E12.
