# Rules and validation

Every rule of the format is numbered in the
[specification](../reference/specification.md#16-validation).
An **error** (`E`) makes a file invalid: units that do not parse, a name
used twice, a label code outside its table, cells that point at a node
the mesh does not have. A **warning** (`W`) says what a reader should
know about a valid file: runs that failed, results that are missing, a
parameter outside its bounds. One numbered rule is neither: E25 is the
refusal to append to a valid file whose dimensions cannot grow.

## Checked when written

A writer checks its input against the rules as it goes, and refuses what
would break one: the call fails, names the rule, and leaves the file as
it was. A file a Gamut library has finished is valid, so problems surface
where they are made, not when someone else opens the file.

## Checked when received

`gamut validate` checks a file from anywhere, written by any tool, and
reports every finding at once, not only the first:

```console
$ gamut validate polar.gamut
no errors, 3 warnings
  W2 status: 1 row is not converged (1 failed), the first row 17; tools that train on the file skip such rows unless told otherwise
  W3 cd: 1 value is missing or not finite, the first at row 17
  W3 cl: 1 value is missing or not finite, the first at row 17
$ gamut validate cylinder.gamut
no errors, no warnings
```

The run that failed in [the first example](../guide/01-run-tables.md) is
reported, so whoever receives the file sees it without being told. A row
in a finding is a position in the file, counted from 0. An array of more
than 67,108,864 values is reported (W11) rather than checked value by
value. `validate` is
also a call in every language, and `gamut validate --json` gives the
findings to a script. Readers make the checks a read needs on what they
read, within the limits in [files from outside](../security.md).

## Versions

A file says which version of the format it follows: `gamut/1`. Within
version 1, additions only add. A reader that meets something newer than
itself, an attribute or role it does not know, reports it (W5) and goes
on, so a file that uses a later addition stays readable. A change that
would make an existing file mean something else is version 2 of the
format, and a reader refuses a version it does not know, naming it.

The version of the format is not the version of the libraries: Gamut 2
writes and reads `gamut/1` files, the same files Gamut 1 wrote.
