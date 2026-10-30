# C++ and C

The library every language uses is a C++ core behind a C interface,
[`gamut/gamut.h`](https://github.com/bijective-systems-org/gamut/blob/main/include/gamut/gamut.h). C++ programs use
[`gamut/gamut.hpp`](https://github.com/bijective-systems-org/gamut/blob/main/include/gamut/gamut.hpp), a header over that
interface with the names of the Python package, exceptions for errors and
standard containers for data; C programs, and other languages that call C,
use `gamut.h` directly. Both are installed with the library
([installing](../install.md#c-and-c)); with CMake, `find_package(gamut)`
and `gamut::gamut` are all a project needs.

Every example in the [examples](../guide/README.md) has a C++ tab, quoted
from a program in `examples/cpp`, and
[`nearest.cpp`](https://github.com/bijective-systems-org/gamut/blob/main/examples/cpp/nearest.cpp)
evaluates a model fitted in Python. Without CMake, one builds as
`c++ -std=c++17 run_table.cpp -I<prefix>/include -L<prefix>/lib -lgamut
-o run_table`, `<prefix>` being where the library is installed.

## C++

### The same calls

| Python | C++ |
|---|---|
| `gamut.create(path, writer=w, mesh="shared", per="fixed", ...)` | `gamut::create(path, w, "shared", "fixed")`, then `declare_...` calls |
| `study.add_run(values, fields=...)` | `study.add_run({{"gamma", 0.5}}, {{"cp", cp}})` |
| `gamut.open(path, mode="a")` | `gamut::open(path, "a")` |
| `study.get_field("p", rows=r, nodes=n)` | `study.get_field("p", r, n)` |
| `study.get_parameter("alpha")`, `study.get_constant("area")` | `study.get_parameter<double>("alpha")`, `study.get_constant<double>("area")`: the type the value is stored as, `int64_t` for one declared int64 |
| `study.outside("alpha", rows=r)` | `study.outside("alpha", r)` |
| `study.select("mach > 0.7")`, `study.get_label(...)`, `study.describe(...)` | the same names |
| `gamut.append`, `extract`, `write_copy`, `validate` | `gamut::append`, `extract`, `write_copy`, `validate` |

Model files, notes and private records are written and read through
`gamut.h`; `study.handle()` gives the open file to pass to it.

### Conventions

`create` takes the path, the writer, the mesh (`""` for a table of runs,
`"shared"` or `"changing"`) and how often the geometry changes (`"fixed"`,
`"run"` or `"group:<label>"`). Declarations come next, then the mesh, then
runs. `points` are nodes × axes in C order and `cells` a `gamut::Cells` in
VTK's convention, node numbers from 0. Each run gives its parameters and
scalars as numbers (a parameter is a double unless declared with
`declare_parameter<int64_t>`) and its labels by name, then its fields;
`add_run` writes it all or nothing and returns its id, and takes a
`gamut::Geometry` when the run brings its own points. `add_runs` writes
many runs at once from a column per name.

`select` returns positions counted from 0, which every `get_` call takes
as rows: `gamut::all`, positions such as `{12}`, or
`gamut::Selection::range(start, stop)`. A field comes back as a
`gamut::Array<double>`: the values in C order and their shape, with
`block(run, k)` for one value. `gamut::open(path, "r", 4)` decompresses
large reads in four threads.

A call that is refused throws `gamut::Error`, whose `rule()` names the rule
of the specification (`"E7"`) when one applies and `path()` what it
concerns. A study closes when it goes out of scope. Call `close()` to
finish a file you write: it throws if the file cannot be finished (a
shared mesh never set), whereas leaving the scope then discards the file
silently. `abandon()` gives up on a file on purpose.

### A model file

The built-in nearest model of [models](../guide/07-models.md#the-built-in-model),
fitted in Python, is evaluated here by the core, from the model's stored
numbers:

```cpp
const gamut::Study model = gamut::open("lift_nearest.gamut");
gamut_error err;
gamut_tree* tree = nullptr;
if (gamut_model_numbers(model.handle(), "fit", &tree, &err) != 0) throw gamut::Error(err);
const std::unique_ptr<gamut_tree, void (*)(gamut_tree*)> numbers(tree, gamut_tree_free);

const char* inputs[] = {"alpha"};
const double alpha[] = {2.2, 7.9};
const double* columns[] = {alpha};
const int64_t lengths[] = {2};
double lift[2];
if (gamut_nearest_call(numbers.get(), inputs, columns, lengths, 1, 2, "cl", lift, 2, &err) != 0)
  throw gamut::Error(err);
```

```text
the nearest run's lift at 2.2 and 7.9 degrees: 0.22 0.88
```

`gamut_model_numbers` gives any model's numbers, whatever its type, as a
tree read with the `gamut_tree_*` calls, for a program that computes the
model itself. `gamut_nearest_call` evaluates the built-in model on a
column of values for each named input, a value per row. It returns values
only: it neither checks the inputs against the parameters' bounds nor
writes a data file, as `evaluate` does in Python, MATLAB and Julia.

## C

[`examples/c/one_mesh.c`](https://github.com/bijective-systems-org/gamut/blob/main/examples/c/one_mesh.c) writes the same
runs in C, with no wall label, and prints the last line.

### The conventions

- Every call returns 0, or returns nonzero and fills a `gamut_error` with the
  rule of the specification it concerns (when one applies), the path of
  what it concerns, and a message. No call keeps a pointer it was given.
- Handles are opaque: `gamut_file` for an open file, `gamut_strings` for a
  list of names.
- Arrays are the caller's, in C order. Positions count from 0. Each array
  comes with its length, and each array the core fills with its capacity,
  so the core can check them: `gamut_geometry_points` takes the count of
  coordinates as well as the nodes and axes they make.

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
CHECK(gamut_geometry_points(f, GAMUT_FLOAT64, points, 2 * N_NODES, N_NODES, 2, &err));
CHECK(gamut_geometry_cells(f, types, N_CELLS, offsets, N_CELLS + 1, connectivity, 4 * N_CELLS,
                           &err));
CHECK(gamut_set_mesh(f, &err));
```

```c
static void add_run(gamut_file* f, double gamma) {
  static double cp[N_NODES];
  solve(gamma, cp);
  CHECK(gamut_batch_begin(f, 1, &err));
  CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 0, 1, &err));
  CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, 0, N_NODES, &err));
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
The full program is [`examples/c/one_mesh.c`](https://github.com/bijective-systems-org/gamut/blob/main/examples/c/one_mesh.c).
