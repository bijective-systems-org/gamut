# 14. C and C++

The library every language uses is a C interface over a C++ core, declared
in one header, [`gamut/gamut.h`](../../include/gamut/gamut.h). A solver
or tool written in C or C++ links it to write its results as runs finish,
or to read a study. Building and installing it
is on the [installing](../install.md#c-and-c) page; with CMake,
`find_package(gamut)` and `gamut::gamut` are all a project needs.

The example writes the study of [page 2](02-one-mesh.md) run by run, then
reads one node of the runs that meet a condition.

## The conventions

- Every call returns 0, or returns nonzero and fills a `gamut_error` with the
  rule of the specification it concerns (when one applies), the path of
  what it concerns, and a message. No call keeps a pointer it was given.
- Handles are opaque: `gamut_file` for an open file, `gamut_strings` for a
  list of names.
- Arrays are the caller's, in C order. Positions count from 0.

```c
static gamut_error err;

/* Stops at the first failure and says what it was. */
#define CHECK(call)                                                                \
  do {                                                                             \
    if ((call) != 0) {                                                             \
      fprintf(stderr, "%s%s%s\n", err.rule, *err.rule ? ": " : "", err.message);   \
      exit(1);                                                                     \
    }                                                                              \
  } while (0)
```

## Writing

Declarations come first, then the mesh, then runs. A batch of one or more
runs is staged and committed all or nothing:

```c
CHECK(gamut_create("cylinder.gamut", "example sweep", "shared", "fixed", &f, &err));
CHECK(gamut_declare_coordinates(f, "m", GAMUT_FLOAT64, 2, "", "", &err));
CHECK(gamut_declare_parameter(f, "gamma", "design", "m2 s-1", GAMUT_FLOAT64, 0, 0, 0, "", &err));
CHECK(gamut_declare_mesh_label(f, "surface", "node", categories, 2, &err));
CHECK(gamut_declare_result(f, "cp", "node", "1", GAMUT_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                         "", "", &err));
CHECK(gamut_geometry_begin(f, &err));
CHECK(gamut_geometry_points(f, GAMUT_FLOAT64, points, N_NODES, 2, &err));
CHECK(gamut_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
CHECK(gamut_geometry_label(f, "surface", surface, N_NODES, &err));
CHECK(gamut_set_mesh(f, &err));
```

```c
CHECK(gamut_batch_begin(f, 1, &err));             /* one run, all or nothing */
CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 1, &err));
CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, N_NODES, &err));
CHECK(gamut_batch_commit(f, NULL, &err));
```

`gamut_declare_result` takes every attribute a result can have; an empty
string leaves a text attribute out, `has_q = 0` the quantile and
`round_bits = -1` the rounding. The header comments each argument.

## Reading

```c
CHECK(gamut_open("cylinder.gamut", &f, &err));
int64_t rows[9], n = 0, node = 12;
CHECK(gamut_select(f, "gamma > 2", rows, 9, &n, &err));
const gamut_sel chosen = {GAMUT_SEL_INDEX, 0, 0, rows, n};
const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
double values[9];
CHECK(gamut_read(f, "cp", &chosen, &one_node, GAMUT_FLOAT64, values, sizeof values, &err));
```

A selection is everything (`GAMUT_SEL_ALL`, or `NULL`), a range
(`GAMUT_SEL_RANGE`, from `start` up to `stop`), or a strictly increasing list
of positions (`GAMUT_SEL_INDEX`). `gamut_shape` gives the shape a read will
have; `gamut_read` converts to the type asked for and fills the buffer from
the start. It prints the same values Python reads for those runs and that
node:

```text
cp at node 12 where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

## Worth knowing

- `gamut_close` finishes a file. If it refuses (a shared mesh never set),
  the handle stays open to fix and close again; `gamut_abandon` gives up,
  and can delete a file the handle created.
- `gamut_validate`, `gamut_append`, `gamut_extract` and `gamut_write_copy` work on
  paths, as in every language.
- Only the `gamut_` functions leave the library. A build with
  `GAMUT_STATIC_HDF5` carries its own HDF5, so a program that also links
  HDF5 never meets a second copy.

Build it: `cc one_mesh.c -I<prefix>/include -L<prefix>/lib -lgamut -lm`.
The full program is [`examples/c/one_mesh.c`](../../examples/c/one_mesh.c).
