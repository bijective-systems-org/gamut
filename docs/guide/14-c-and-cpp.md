# 14. C++ and C

The library every language uses is a C++ core behind a C interface,
[`gamut/gamut.h`](../../include/gamut/gamut.h). C++ programs use
[`gamut/gamut.hpp`](../../include/gamut/gamut.hpp), a header over that
interface with the names of the Python package, exceptions for errors and
standard containers for data; C programs, and other languages that call C,
use `gamut.h` directly. Both are installed with the library
([installing](../install.md#c-and-c)); with CMake, `find_package(gamut)`
and `gamut::gamut` are all a project needs.

The example writes eight runs of flow past a cylinder on one mesh, reopens
the file to add a ninth, then reads one node in every run: the program of
the [README](../../README.md#example).

## C++

### Writing

```cpp
auto study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed");
study.declare_coordinates("m", 2);
study.declare_parameter("gamma", "design", "m2 s-1");
study.declare_field("cp", "node", "1");
study.set_mesh(points, cells);
for (double gamma = 0.0; gamma < 3.75; gamma += 0.5)
  study.add_run({{"gamma", gamma}}, {{"cp", solve(gamma)}});
study.close();
```

`create` takes the path, the writer, the mesh (`""` for a table of runs,
`"shared"` or `"changing"`) and how often the geometry changes (`"fixed"`,
`"run"` or `"group:<label>"`). Declarations come next, then the mesh, then
runs. `points` are nodes × axes in C order and `cells` a `gamut::Cells` in
VTK's convention, node numbers from 0. Each run gives its parameters and
scalars as numbers and its labels by name, then its fields; `add_run`
writes it all or nothing and returns its id. `solve` stands for the
solver and returns `cp` at every node.

A call that is refused throws `gamut::Error`, whose `rule()` names the rule
of the specification (`"E7"`) when one applies and `path()` what it
concerns. A study closes when it goes out of scope; `close()` does it
sooner and throws if the file cannot be finished (a shared mesh never
set), whereas leaving the scope then discards the file.

### Adding runs

```cpp
auto study = gamut::open("cylinder.gamut", "a");
study.add_run({{"gamma", 4.0}}, {{"cp", solve(4.0)}});
study.close();
```

### Reading

```cpp
auto study = gamut::open("cylinder.gamut");
auto cp = study.get_field("cp", gamut::all, {12});    // runs x nodes
```

```text
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

`get_field` takes the rows and the nodes (or cells) to read: `gamut::all`,
positions such as `{12}`, or `gamut::Selection::range(start, stop)`. It
returns a `gamut::Array<double>`: the values in C order and their shape,
here 9 × 1, with `cp(i, j)` for one value. `gamut::open(path, "r", 4)`
decompresses large reads in four threads.

### The same calls

| Python | C++ |
|---|---|
| `gamut.create(path, writer=w, mesh="shared", per="fixed", ...)` | `gamut::create(path, w, "shared", "fixed")`, then `declare_...` calls |
| `study.add_run(values, fields=...)` | `study.add_run({{"gamma", 0.5}}, {{"cp", cp}})` |
| `gamut.open(path, mode="a")` | `gamut::open(path, "a")` |
| `study.get_field("p", rows=r, nodes=n)` | `study.get_field("p", r, n)` |
| `study.select("mach > 0.7")`, `study.get_label(...)`, `study.describe(...)` | the same names |
| `gamut.append`, `extract`, `write_copy`, `validate` | `gamut::append`, `extract`, `write_copy`, `validate` |

Model files, notes and private records are written and read through
`gamut.h`; `study.handle()` gives the open file to pass to it.

## C

The same program in C is
[`examples/c/one_mesh.c`](../../examples/c/one_mesh.c).

### The conventions

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

### Writing

Declarations come first, then the mesh, then runs. A batch of one or more
runs is staged and committed all or nothing:

```c
CHECK(gamut_create("cylinder.gamut", "example sweep", "shared", "fixed", &f, &err));
CHECK(gamut_declare_coordinates(f, "m", GAMUT_FLOAT64, 2, "", "", &err));
CHECK(gamut_declare_parameter(f, "gamma", "design", "m2 s-1", GAMUT_FLOAT64, 0, 0, 0, "", &err));
CHECK(gamut_declare_result(f, "cp", "node", "1", GAMUT_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                         "", "", &err));
CHECK(gamut_geometry_begin(f, &err));
CHECK(gamut_geometry_points(f, GAMUT_FLOAT64, points, N_NODES, 2, &err));
CHECK(gamut_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
CHECK(gamut_set_mesh(f, &err));
```

```c
static void add_run(gamut_file* f, double gamma) {
  static double cp[N_NODES];
  solve(gamma, cp);
  CHECK(gamut_batch_begin(f, 1, &err));
  CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 1, &err));
  CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, N_NODES, &err));
  CHECK(gamut_batch_commit(f, NULL, &err));
}
```

`gamut_open_append` opens an existing file, and runs are added to it the
same way.

`gamut_declare_result` takes every attribute a result can have; an empty
string leaves a text attribute out, `has_q = 0` the quantile and
`round_bits = -1` the rounding. The header comments each argument.

### Reading

```c
CHECK(gamut_open("cylinder.gamut", &f, &err));
int64_t node = 12;
const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
double cp[9];                                          /* runs x nodes */
CHECK(gamut_read(f, "cp", NULL, &one_node, GAMUT_FLOAT64, cp, sizeof cp, &err));
CHECK(gamut_close(f, &err));
```

A selection is everything (`GAMUT_SEL_ALL`, or `NULL`), a range
(`GAMUT_SEL_RANGE`, from `start` up to `stop`), or a strictly increasing list
of positions (`GAMUT_SEL_INDEX`). `gamut_shape` gives the shape a read will
have; `gamut_read` converts to the type asked for and fills the buffer from
the start. It prints the same values Python reads for that node in every
run:

```text
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

### Notes

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
