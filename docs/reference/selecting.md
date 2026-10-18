# Selecting runs

`select` (Python, MATLAB, Julia), `mes_select` (C) and `--where` (the
command line) take a condition and return the positions of the rows that
meet it, in increasing order. The language is the same everywhere, because
the core evaluates it.

```text
mach > 0.7
status == converged
model == "k-omega SST" or alpha <= 0
(mach>0.4)and(alpha<5)
speed >= 20 and not (gamma > 1)
```

## Comparisons

A comparison is a name, an operator and a value.

| Name | Operators | Value |
|---|---|---|
| a parameter or a scalar | `==` `!=` `<` `<=` `>` `>=` | a decimal number: `0.7`, `-2`, `1e-5` |
| a label | `==` `!=` | one of the label's names, in double quotes if it has spaces or any of `( ) = ! < >` |

Operators and parentheses need no spaces around them. A single `=` is not
an operator; the message says which ones are. A name that itself holds a
double quote cannot be written in a condition; choose those runs by
position instead.

## Combining

`not` binds tightest, then `and`, then `or`; parentheses group.
`a or b and c` is `a or (b and c)`.

## Missing values

A result that is missing (NaN) meets no comparison, `!=` included, so a
failed run's `cl` is neither `<= 0.5` nor `> 0.5`. `not` turns that into a
match: `not (cl > 0.5)` keeps the failed runs, while `cl <= 0.5` leaves
them out.

## Refusals

A condition that does not parse, a name the file does not have, a label
compared with `<`, or a label value that is not in its table is refused
with a message saying what and where (the character position for a
syntax error), and nothing is returned.

## Limits

A selection reads the columns it compares a block of rows at a time, so
memory stays bounded. Files with more than 2²⁷ rows (about 134 million)
are refused; select on a subset extracted first.
