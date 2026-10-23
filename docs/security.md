# Opening files from outside

A study file often comes from someone else: a partner, a public dataset, a
customer. Every reader in this repository treats a file as untrusted input.
This page says what that protects against, what it does not, and what to do
about the rest.

## What a reader does

Opening a file reads its groups and attributes, never field values or
model data; values are read when asked for. Every count taken from a file
is checked against a limit before a buffer is sized, so a file that claims
a billion rows cannot make a reader allocate for them. A soft or external
link in a file is an error (E22) and is never followed, so a file cannot
make a reader open another file or path.

A file holds no executable code. A model's numbers are plain data, read by
software the reader has installed and registered. The packaged core loads
no HDF5 filter plugins: the format allows only gzip and shuffle, which
HDF5 has built in, and a file naming another filter is refused.

`gamut validate` reports the rules a file breaks, with where and why,
within the limits below. A
read that cannot be carried out safely is refused with the rule and the
path of what it concerns.

## The limits

| A reader refuses | Above |
|---|---|
| a read of one array into memory | 2³¹ elements or 8 GiB |
| a read touching small chunks | 2²⁰ chunks |
| a selection scanning rows | 2²⁷ rows |
| label names read at once | 2²⁵ rows |
| category tables read when a file opens | 2²⁴ entries or 256 MiB |
| groups nested inside each other | 64 levels |

Each refusal is rule E23, with the path of what was refused. The limits are
far above what a study needs: a field of 8 GiB is read a part at a time,
which any of the reads in the [guide](guide/08-reading-parts.md) does. The
[corpus](../corpus) holds hostile files built to cross each limit, and
every language is tested against them. Below the limits, validating takes
time in proportion to what a file declares: a small file that declares two
billion cells keeps `gamut validate` busy for about a minute before it
reports what is wrong. To check label codes and missing results,
`gamut validate` reads every value of an array of up to 2²⁶ values (about
67 million); in a larger array it checks the structure only, and reports
the array as unchecked (W11).

## What it does not protect against

The HDF5 library reads a file's own bookkeeping before any code of this
repository sees it, and a damaged or crafted file can make HDF5 itself
fault or spin. `tools/damaged_files.py` measures this: it damages every
valid file of the [corpus](../corpus) 140 ways (truncated, with single
bits flipped, or with runs of bytes zeroed), then validates each copy and
makes every read on it, each in a child process.

Measured on 23 October 2026 with the core built as the packages are (HDF5
1.14.6 linked in), and again under the address and undefined-behaviour
sanitizers: all 840 copies were answered by rule, and every read of them
returned or was refused. Runs with more copies find the rare one HDF5
itself cannot meet: in 4,200 copies under the sanitizers, seven crashed and
three hung, each inside HDF5's own code, most while reading a file's
dimension-scale attributes. Such a hang has been reported to the HDF Group.

So for a file nobody vouches for, a separate process is the protection.
Check it with `gamut validate FILE` (or `gamut info`) in a child process
with a time limit before opening it in a long-running program, and in a
service that opens files from users, read them in a worker process it can
kill.

## Reporting a problem

A file that crashes or hangs a reader outside HDF5, or that a reader
accepts against the [specification](../SPEC.md), is a bug. Please report it
privately through GitHub's
[vulnerability reporting](https://github.com/bijective-systems-org/gamut/security/advisories/new)
for this repository, with the file if you can share it.
