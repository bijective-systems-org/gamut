# 14. C and C++

The library every language uses is a C interface over a C++ core, declared
in one header, [`mestra/mestra.h`](../../include/mestra/mestra.h). A solver
or tool written in C or C++ links it to write its results as runs finish,
or to read a study. Building and installing it
is on the [installing](../install.md#c-and-c) page; with CMake,
`find_package(mestra)` and `mestra::mestra` are all a project needs.

The example writes the study of [page 2](02-one-mesh.md) run by run, then
reads one node of the runs that meet a condition.

## The conventions

- Every call returns 0, or returns nonzero and fills a `mes_error` with the
  rule of the specification it concerns (when one applies), the path of
  what it concerns, and a message. No call keeps a pointer it was given.
- Handles are opaque: `mes_file` for an open file, `mes_strings` for a
  list of names.
- Arrays are the caller's, in C order. Positions count from 0.

```c
static mes_error err;

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
CHECK(mes_create("cylinder.mes", "example sweep", "shared", "fixed", &f, &err));
CHECK(mes_declare_coordinates(f, "m", MES_FLOAT64, 2, "", "", &err));
CHECK(mes_declare_parameter(f, "gamma", "design", "m2 s-1", MES_FLOAT64, 0, 0, 0, "", &err));
CHECK(mes_declare_mesh_label(f, "surface", "node", categories, 2, &err));
CHECK(mes_declare_result(f, "cp", "node", "1", MES_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                         "", "", &err));
CHECK(mes_geometry_begin(f, &err));
CHECK(mes_geometry_points(f, MES_FLOAT64, points, N_NODES, 2, &err));
CHECK(mes_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
CHECK(mes_geometry_label(f, "surface", surface, N_NODES, &err));
CHECK(mes_set_mesh(f, &err));
```

```c
CHECK(mes_batch_begin(f, 1, &err));             /* one run, all or nothing */
CHECK(mes_batch_values(f, "gamma", MES_FLOAT64, &gamma, 1, &err));
CHECK(mes_batch_values(f, "cp", MES_FLOAT64, cp, N_NODES, &err));
CHECK(mes_batch_commit(f, NULL, &err));
```

`mes_declare_result` takes every attribute a result can have; an empty
string leaves a text attribute out, `has_q = 0` the quantile and
`round_bits = -1` the rounding. The header comments each argument.

## Reading

```c
CHECK(mes_open("cylinder.mes", &f, &err));
int64_t rows[9], n = 0, node = 12;
CHECK(mes_select(f, "gamma > 2", rows, 9, &n, &err));
const mes_sel chosen = {MES_SEL_INDEX, 0, 0, rows, n};
const mes_sel one_node = {MES_SEL_INDEX, 0, 0, &node, 1};
double values[9];
CHECK(mes_read(f, "cp", &chosen, &one_node, MES_FLOAT64, values, sizeof values, &err));
```

A selection is everything (`MES_SEL_ALL`, or `NULL`), a range
(`MES_SEL_RANGE`, from `start` up to `stop`), or a strictly increasing list
of positions (`MES_SEL_INDEX`). `mes_shape` gives the shape a read will
have; `mes_read` converts to the type asked for and fills the buffer from
the start. It prints the same values Python reads for those runs and that
node:

```text
cp at node 12 where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

## Worth knowing

- `mes_close` finishes a file. If it refuses (a shared mesh never set),
  the handle stays open to fix and close again; `mes_abandon` gives up,
  and can delete a file the handle created.
- `mes_validate`, `mes_append`, `mes_extract` and `mes_write_copy` work on
  paths, as in every language.
- Only the `mes_` functions leave the library. A build with
  `MESTRA_STATIC_HDF5` carries its own HDF5, so a program that also links
  HDF5 never meets a second copy.

Build it: `cc one_mesh.c -I<prefix>/include -L<prefix>/lib -lmestra -lm`.
The full program is [`examples/c/one_mesh.c`](../../examples/c/one_mesh.c).
