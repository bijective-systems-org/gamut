# Opening files from outside

A study file often comes from someone else: a partner, a public dataset, a
customer. Every reader in this repository treats a file as untrusted input.
This page says what that protects against, what it does not, and what to do
about the rest.

## What a reader does

- **Opening reads structure only.** Opening a file reads its groups and
  attributes, never field values or model data. Values are read when asked
  for.
- **Sizes are checked before memory is used.** Every count taken from a
  file is checked against a limit before a buffer is sized, so a file that
  claims a billion rows cannot make a reader allocate for them.
- **Links are never followed.** A soft or external link in a file is an
  error (E22) and is never opened, so a file cannot make a reader open
  another file or path.
- **No code runs.** A file holds no executable code: a model's numbers are
  plain data, read by software the reader has installed and registered. The
  packaged core loads no HDF5 filter plugins; the format allows only gzip
  and shuffle, which HDF5 has built in, and a file naming another filter
  is refused.
- **Everything is reported, nothing is assumed.** `mestra validate` reports
  every rule a file breaks, with where and why. A read a reader cannot
  carry out safely is refused with the rule and the path of what it
  concerns, never answered with a guess.

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
every language is tested against them.

## What it does not protect against

The HDF5 library reads a file's own bookkeeping before any code of this
repository sees it, and a damaged or crafted file can make HDF5 itself
fault or spin. `tools/damaged_files.py` measures this: it validates 420
damaged copies of three valid files, truncated, with single bits flipped,
or with runs of bytes zeroed, each in a child process.

Measured on 17 October 2026 with the packaged core (HDF5 1.14.6 linked in):
419 copies were answered by rule, none crashed, and one hung inside HDF5's
reader of a dimension-scale list. Every HDF5 reader, netCDF's included,
reads those lists the same way.

So for a file nobody vouches for, the process boundary is the defence:

- check it with `mestra validate FILE` (or `mestra info`) in a child
  process with a time limit, before opening it in a long-running program;
- in a service that opens files from users, read in a worker process it
  can kill.

## Reporting a problem

A file that crashes or hangs a reader outside HDF5, or that a reader
accepts against the [specification](../SPEC.md), is a bug. Please report it
privately through the repository's security advisories on GitHub, with
the file if you can share it.
