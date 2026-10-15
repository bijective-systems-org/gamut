The skeleton every per-language README is cut to
================================================

This is the authoring guide for per-language READMEs, not a statement of
runtime guarantees or a line-count test. Keep the core concepts in the
format guide and the full API details beside the calls. A per-language README
is not a layer: it is the door to one interface. Anything about the
format belongs in `guide.md`, anything normative in `../SPEC.md`, and
anything about one call belongs in that call's docstring or help text,
where a user will actually meet it.

Use these five sections in this order. Keep the first three concise, while
retaining the prerequisites and working-directory instructions needed to
run the example.


1. Install
----------

How to get the package and run its tests: the installation steps, direct
dependencies, optional test dependencies and commands for the configured
test lane. State platform/configuration differences where they affect those
commands. No prose about what the format is.


2. The small example (this language)
---------------------------------------

The top-level README's example, written in this language: build a
small dataset from plain arrays, write it, read it back, and take one
value by name. It is the same data and the same value in all four
languages, so a reader who knows one can read the others. Link to
`docs/examples/` for the seven worked examples and to `guide.md` for
what the concepts mean.


3. Axis order and permute by name
---------------------------------

What order this language hands an array back in, that the dimension
names are what two languages agree on, and the call that permutes or
indexes by name. State the value at one named coordinate of the
example above, so a reader can check their own run against it. This
section is the one that has to be right: it is the part of the
documents a user should never have to read twice.


4. What the reader refuses
--------------------------

Name the rules that cause refusal, what a non-strict read gives instead,
and where findings are reported. Distinguish metadata opening from eager
reads and validation where those differ. Briefly state the native-library
safety boundary and link to `compatibility.md`; detailed limits belong in
the module's documentation. Do not promise complete loss inventories or
failure isolation that the implementation does not provide.


5. Where to go next
-------------------

`../docs/guide.md` first, then `../SPEC.md` by section, then
`../docs/api-conventions.md` for anyone comparing two languages. Three
lines, not a table of contents.


Everything else
---------------

Everything a README carries today that is not one of those five moves
in one of two directions. If it is about the format -- roles, varies,
alignment, statistics, the public and private line, what the validator
reports -- it moves to `guide.md`, and the README links there. If it
is about this API -- an argument's default, what one call refuses,
what a helper returns -- put the full detail in the docstring, help text or
header comment. The README may retain a short qualification needed to use
its example correctly, with a route to the authoritative detail.

Section 4 of `api-conventions.md` requires a language without the
post-processing helpers to say so under a heading of its own, after
"What the reader refuses". Additional implementation-specific workflow
sections are useful when needed to complete a task, such as C++ row-wise
appending; keep full API detail beside the calls and link to it.
