/* The C interface of the Gamut core: the one surface every binding
 * (Python, MATLAB, Julia) and C or C++ caller uses.  Opaque handles,
 * caller-allocated buffers, UTF-8 strings, and an error record on every
 * failure.  No C++ type and no HDF5 identifier crosses it.
 *
 * Every function returning int returns 0 on success and nonzero on
 * failure, when it fills *err if err is not NULL.  The one exception is
 * gamut_units_valid, a test that returns 1 when its units parse.  No function keeps a
 * pointer the caller passed after it returns.
 *
 * Any function may be called from any thread.  Calls that reach a file
 * take turns, one at a time across the process, so threads reading
 * different files do not run in parallel; gamut_set_threads is what reads
 * one large field faster.
 */
#ifndef GAMUT_H
#define GAMUT_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(GAMUT_BUILDING)
#    define GAMUT_API __declspec(dllexport)
#  else
#    define GAMUT_API __declspec(dllimport)
#  endif
#else
#  define GAMUT_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* An error: the rule of spec section 16 when one applies ("E7"), a
 * concept path ("node_fields/p") when one applies, and a message. */
typedef struct {
  char rule[8];
  char path[512];
  char message[2048];
} gamut_error;

/* Element types; the numbers are fixed.  GAMUT_AS_GIVEN in a declaration
 * means the dtype of the first values written (precision kept as given),
 * except for a parameter, which is float64 unless declared GAMUT_INT64. */
enum {
  GAMUT_AS_GIVEN = 0,
  GAMUT_UINT8 = 1,
  GAMUT_INT8 = 2,
  GAMUT_INT32 = 3,
  GAMUT_INT64 = 4,
  GAMUT_FLOAT32 = 5,
  GAMUT_FLOAT64 = 6
};

/* A selection along one axis. */
enum { GAMUT_SEL_ALL = 0, GAMUT_SEL_RANGE = 1, GAMUT_SEL_INDEX = 2 };
typedef struct {
  int kind;
  int64_t start, stop;     /* GAMUT_SEL_RANGE: [start, stop) */
  const int64_t* index;    /* GAMUT_SEL_INDEX: strictly increasing */
  int64_t count;
} gamut_sel;

/* The library's version ("2.0.0") and the format string it writes
 * ("gamut/1").  Static strings; never freed. */
GAMUT_API const char* gamut_version(void);
GAMUT_API const char* gamut_format(void);
/* 1 when `units` parses by the grammar of spec section 13, else 0. */
GAMUT_API int gamut_units_valid(const char* units);

/* Opaque handles. */
typedef struct gamut_file gamut_file;        /* a file open to write or to read */
typedef struct gamut_strings gamut_strings;  /* a list of UTF-8 strings */

/* --- Writing a data file ------------------------------------------------
 * The output path must not exist; creation never replaces an existing file.
 * mesh_kind: NULL or "" (no mesh), "shared", "changing".
 * per: "fixed", "run" or "group:<label>" (NULL or "" without a mesh). */
GAMUT_API int gamut_create(const char* path, const char* writer, const char* mesh_kind,
                       const char* per, gamut_file** out, gamut_error* err);
/* An existing data file, to add rows in place. */
GAMUT_API int gamut_open_append(const char* path, gamut_file** out, gamut_error* err);

/* A new model file (spec section 7).  mesh_kind: NULL or "" or "shared";
 * per: "fixed" or "run". */
GAMUT_API int gamut_create_model(const char* path, const char* writer, const char* mesh_kind,
                             const char* per, gamut_file** out, gamut_error* err);

/* title, license, references, source or portion_marking; trained_on in a
 * model file. */
GAMUT_API int gamut_set_attribute(gamut_file* f, const char* name, const char* value,
                              gamut_error* err);
GAMUT_API int gamut_declare_parameter(gamut_file* f, const char* name, const char* role,
                                  const char* units, int dtype, int has_bounds,
                                  double lower, double upper, const char* run_group,
                                  gamut_error* err);
GAMUT_API int gamut_declare_label(gamut_file* f, const char* name, const char* role,
                              const char* const* categories, int64_t n_categories,
                              gamut_error* err);
/* where: "scalar", "node" or "cell".  Empty strings and has_q = 0 mean
 * absent; round_bits < 0 means no rounding.  model and output name what
 * computes the result in a model file (empty in a data file). */
GAMUT_API int gamut_declare_result(gamut_file* f, const char* name, const char* where,
                               const char* units, int dtype, const char* of,
                               const char* statistic, int has_q, double q,
                               const char* method, const char* with_respect_to,
                               const char* axis, const char* vector, int round_bits,
                               const char* model, const char* output, gamut_error* err);
GAMUT_API int gamut_declare_mesh_label(gamut_file* f, const char* name, const char* where,
                                   const char* const* categories, int64_t n_categories,
                                   gamut_error* err);
/* model and output: coordinates computed by a model (a model file whose
 * mesh is per run); empty otherwise. */
GAMUT_API int gamut_declare_coordinates(gamut_file* f, const char* units, int dtype, int axes,
                                    const char* model, const char* output, gamut_error* err);
/* dtype GAMUT_INT64 uses integer_value; GAMUT_FLOAT32 or GAMUT_FLOAT64 float_value. */
GAMUT_API int gamut_set_constant(gamut_file* f, const char* name, const char* units, int dtype,
                             double float_value, int64_t integer_value, gamut_error* err);
GAMUT_API int gamut_set_generalisation_group(gamut_file* f, const char* label, gamut_error* err);
/* gzip_level 0 turns compression off; 1 to 9 with or without shuffle. */
GAMUT_API int gamut_set_compression(gamut_file* f, int gzip_level, int shuffle, gamut_error* err);

/* A geometry is staged, then used by gamut_set_mesh or assigned to batch
 * rows or group members.  Each gamut_geometry_begin starts a new one. */
GAMUT_API int gamut_geometry_begin(gamut_file* f, gamut_error* err);
/* points holds count values, n_nodes x axes in C order; points may be NULL,
 * with count 0, to give only n_nodes and axes (a shared mesh whose
 * coordinates come with the runs). */
GAMUT_API int gamut_geometry_points(gamut_file* f, int dtype, const void* points, int64_t count,
                                int64_t n_nodes, int axes, gamut_error* err);
/* n_cells types, n_offsets offsets (n_cells + 1, or none for no cells) and
 * n_connectivity node numbers, in VTK's convention. */
GAMUT_API int gamut_geometry_cells(gamut_file* f, const uint8_t* types, int64_t n_cells,
                               const int64_t* offsets, int64_t n_offsets,
                               const int64_t* connectivity, int64_t n_connectivity,
                               gamut_error* err);
GAMUT_API int gamut_geometry_label(gamut_file* f, const char* name, const int64_t* values,
                               int64_t n, gamut_error* err);
/* A shared mesh from the staged geometry (cells, fixed labels, and the
 * coordinates when per = fixed). */
GAMUT_API int gamut_set_mesh(gamut_file* f, gamut_error* err);

/* Rows are staged in a batch and committed all or nothing. */
GAMUT_API int gamut_batch_begin(gamut_file* f, int64_t n_rows, gamut_error* err);
/* Parameters, label codes, scalars, and fields (rows x sites, or for a
 * changing mesh every row's values end to end). first_axis is the length of
 * the first axis of the caller's array when it has more than one axis, and 0
 * for a flat array; an array whose first axis is not the batch's rows (a
 * field given sites x rows) is refused. */
GAMUT_API int gamut_batch_values(gamut_file* f, const char* name, int dtype, const void* values,
                             int64_t first_axis, int64_t count, gamut_error* err);
GAMUT_API int gamut_batch_names(gamut_file* f, const char* label, const char* const* names,
                            int64_t count, gamut_error* err);
/* The staged geometry belongs to the next row of the batch (per = run) or
 * to a group member appearing for the first time (per = group). */
GAMUT_API int gamut_batch_geometry_for_row(gamut_file* f, gamut_error* err);
GAMUT_API int gamut_batch_geometry_for_member(gamut_file* f, const char* member, gamut_error* err);
GAMUT_API int gamut_batch_commit(gamut_file* f, int64_t* first_id, gamut_error* err);
GAMUT_API int gamut_flush(gamut_file* f, gamut_error* err);

/* Free-form public notes (spec section 8): text, integers, floats. */
GAMUT_API int gamut_set_note_text(gamut_file* f, const char* key, const char* value, gamut_error* err);
GAMUT_API int gamut_set_note_int(gamut_file* f, const char* key, int64_t value, gamut_error* err);
GAMUT_API int gamut_set_note_float(gamut_file* f, const char* key, double value, gamut_error* err);
/* A producer's own record: bytes no reader interprets. */
GAMUT_API int gamut_set_private(gamut_file* f, const char* name, const void* bytes, int64_t n,
                            gamut_error* err);

/* Closes a file opened by any call and frees the handle; writes what a
 * writer holds.  f may be NULL.  When a writer's close is refused (a model
 * file without a model, a shared mesh never set) the handle stays open:
 * fix what the error names and close again, or gamut_abandon. */
GAMUT_API int gamut_close(gamut_file* f, gamut_error* err);
/* Gives up on a file and frees the handle without finishing it: nothing
 * more is written.  remove_file (non-zero) deletes a file this handle
 * created; a file opened for appending is never deleted.  f may be NULL.
 * For a writer whose earlier call failed and whose file is not wanted. */
GAMUT_API void gamut_abandon(gamut_file* f, int remove_file);

/* --- Reading ------------------------------------------------------------- */
GAMUT_API int gamut_open(const char* path, gamut_file** out, gamut_error* err);
/* Worker threads for reading fields: raw chunks come through HDF5 one at a
 * time and are decompressed in parallel outside it.  1 (the default) reads
 * serially. */
GAMUT_API int gamut_set_threads(gamut_file* f, int threads, gamut_error* err);
/* key: "format", "kind", "type", "addons", "row_count", or a file-level
 * attribute ("writer", "created", "file_id", "title", "license",
 * "references", "source", "portion_marking", "generalisation_group",
 * "trained_on", "evaluated_from", "support_id", "per", "mesh_kind").  One string, or
 * several for "addons". */
GAMUT_API int gamut_info(const gamut_file* f, const char* key, gamut_strings** out, gamut_error* err);
/* group: "parameters", "labels", "scalars", "constants", "node_fields",
 * "cell_fields", "node_labels", "cell_labels", "tables", "models". */
GAMUT_API int gamut_names(const gamut_file* f, const char* group, gamut_strings** out,
                      gamut_error* err);
/* A concept's attributes as two parallel lists. */
GAMUT_API int gamut_describe(const gamut_file* f, const char* name, gamut_strings** keys,
                         gamut_strings** values, gamut_error* err);
/* What describes a result (spec section 6), as three parallel lists, in the
 * order of the file's scalars, node fields and cell fields: kinds ("std",
 * "quantile", "derivative", "vector"), keys (a quantile's q, as describe
 * gives it; what a derivative is with respect to, "coordinates:<axis>" for
 * node position; empty for "std" and "vector") and the results' names.  The
 * parts of a vector are its results without an "of", the result itself
 * among them.  Another concept has nothing describing it; a name that is
 * nothing in the file is refused, as by gamut_describe. */
GAMUT_API int gamut_related(const gamut_file* f, const char* name, gamut_strings** kinds,
                        gamut_strings** keys, gamut_strings** names, gamut_error* err);
/* name: a parameter, label, scalar, constant, field or mesh label, or
 * "row", "coordinates", "cells/types", "cells/offsets",
 * "cells/connectivity".  rows and sites may be NULL (everything).  shape has
 * room for `capacity` extents; *rank is always set, and a capacity below it
 * is refused (4 is always enough).  gamut_read converts to dtype and fills out
 * from the start, in C order; out_bytes is its capacity, at least the product
 * of the shape times the dtype's size. */
GAMUT_API int gamut_shape(const gamut_file* f, const char* name, const gamut_sel* rows,
                      const gamut_sel* sites, int* rank, int64_t* shape, int capacity,
                      gamut_error* err);
GAMUT_API int gamut_read(const gamut_file* f, const char* name, const gamut_sel* rows,
                     const gamut_sel* sites, int dtype, void* out, int64_t out_bytes,
                     gamut_error* err);
GAMUT_API int gamut_label_names(const gamut_file* f, const char* label, const gamut_sel* rows,
                            gamut_strings** out, gamut_error* err);
/* How far each selected row's value of the parameter `name` lies outside
 * the bounds the file declares for it, in the parameter's units: 0 inside
 * or on a bound, value - lower below, value - upper above, NaN where the
 * value is missing.  A parameter without bounds is refused.  out has the
 * shape gamut_shape gives the parameter; out_bytes is its capacity. */
GAMUT_API int gamut_outside(const gamut_file* f, const char* name, const gamut_sel* rows,
                        double* out, int64_t out_bytes, gamut_error* err);
GAMUT_API int gamut_table(const gamut_file* f, const char* table, gamut_strings** out,
                      gamut_error* err);
/* The positions of the rows `where` selects (docs/reference/selecting.md),
 * written to out (room for `capacity`, at least the row count); *n says how many. */
GAMUT_API int gamut_select(const gamut_file* f, const char* where, int64_t* out, int64_t capacity,
                       int64_t* n, gamut_error* err);

/* --- Models ----------------------------------------------------------------
 * A model's numbers cross the interface as a tree: a dictionary built and
 * read by key paths ("a/b" for nested dictionaries). */
typedef struct gamut_tree gamut_tree;
enum { GAMUT_TREE_NULL = 0, GAMUT_TREE_BOOL = 1, GAMUT_TREE_INT = 2, GAMUT_TREE_FLOAT = 3,
       GAMUT_TREE_STRING = 4, GAMUT_TREE_NUMBERS = 5, GAMUT_TREE_STRINGS = 6, GAMUT_TREE_DICT = 7,
       GAMUT_TREE_ABSENT = -1 };
GAMUT_API int gamut_tree_new(gamut_tree** out, gamut_error* err);
GAMUT_API void gamut_tree_free(gamut_tree* t);
GAMUT_API int gamut_tree_set_null(gamut_tree* t, const char* key, gamut_error* err);
GAMUT_API int gamut_tree_set_bool(gamut_tree* t, const char* key, int value, gamut_error* err);
GAMUT_API int gamut_tree_set_int(gamut_tree* t, const char* key, int64_t value, gamut_error* err);
GAMUT_API int gamut_tree_set_float(gamut_tree* t, const char* key, double value, gamut_error* err);
GAMUT_API int gamut_tree_set_string(gamut_tree* t, const char* key, const char* value, gamut_error* err);
/* dtype GAMUT_INT8 (booleans), GAMUT_INT32, GAMUT_INT64 or GAMUT_FLOAT64; data
 * holds count values, the product of the shape, in C order. */
GAMUT_API int gamut_tree_set_array(gamut_tree* t, const char* key, int dtype, const void* data,
                               int64_t count, int rank, const int64_t* shape, gamut_error* err);
GAMUT_API int gamut_tree_set_strings(gamut_tree* t, const char* key, const char* const* items,
                                 int64_t n, gamut_error* err);
GAMUT_API int gamut_tree_set_dict(gamut_tree* t, const char* key, gamut_error* err);
/* The keys of the dictionary at key ("" for the root). */
GAMUT_API int gamut_tree_keys(const gamut_tree* t, const char* key, gamut_strings** out, gamut_error* err);
GAMUT_API int gamut_tree_kind(const gamut_tree* t, const char* key, int* kind, gamut_error* err);
/* Booleans and integers in *integer, floats in *real. */
GAMUT_API int gamut_tree_scalar(const gamut_tree* t, const char* key, int64_t* integer, double* real,
                            gamut_error* err);
/* A string (one item) or a list of strings. */
GAMUT_API int gamut_tree_strings(const gamut_tree* t, const char* key, gamut_strings** out,
                             gamut_error* err);
/* shape has room for `capacity` extents; *rank is always set, and a
 * capacity below it is refused (8 is always enough). */
GAMUT_API int gamut_tree_array_info(const gamut_tree* t, const char* key, int* dtype, int* rank,
                                int64_t* shape, int capacity, gamut_error* err);
/* out_bytes is the capacity of out, at least the array's size. */
GAMUT_API int gamut_tree_array(const gamut_tree* t, const char* key, void* out, int64_t out_bytes,
                           gamut_error* err);

/* Adds a model to a model file: its type, the inputs it reads (parameters,
 * labels, "coordinates"), its numbers, and an optional one-line repr. */
GAMUT_API int gamut_add_model(gamut_file* f, const char* id, const char* type,
                          const char* const* inputs, int64_t n_inputs, const gamut_tree* numbers,
                          const char* repr, gamut_error* err);
/* A model's type and inputs come from gamut_names(f, "models") and
 * gamut_describe(f, "models/<id>"); its numbers from here. */
GAMUT_API int gamut_model_numbers(const gamut_file* f, const char* id, gamut_tree** out, gamut_error* err);

/* The built-in nearest-neighbour model (spec section 7.5), so every
 * binding gets the same answers. */
GAMUT_API int gamut_nearest_check(const gamut_tree* numbers, gamut_error* err);
GAMUT_API int gamut_nearest_output_size(const gamut_tree* numbers, const char* output,
                                    int64_t* per_row, gamut_error* err);
/* columns[j] holds column_lengths[j] values, each n_rows; out holds out_count. */
GAMUT_API int gamut_nearest_call(const gamut_tree* numbers, const char* const* input_names,
                             const double* const* columns, const int64_t* column_lengths,
                             int n_inputs, int64_t n_rows, const char* output, double* out,
                             int64_t out_count, gamut_error* err);

/* Evaluation, driven by the binding: a data file declaring what the open
 * model file declares; the caller adds the rows (inputs and the models'
 * outputs) with gamut_batch_* and closes it. */
GAMUT_API int gamut_evaluate_begin(const gamut_file* model, const char* out_path, gamut_file** out,
                               gamut_error* err);

/* --- Checking ------------------------------------------------------------- */
/* Copies between files.  Each validates its source
 * first and checks everything before the first row is written.
 * gamut_append adds src's rows to dst in place (new ids continuing dst's,
 * tables merged by name); both need the same declarations, mesh and
 * member geometry.  gamut_extract writes the selected rows of src as a new
 * file, ids kept, tables whole.  gamut_write_copy rewrites src as dst with
 * the default layout, keeping its identity (file_id, created). */
GAMUT_API int gamut_append(const char* dst_path, const char* src_path, int64_t* rows_added,
                       gamut_error* err);
GAMUT_API int gamut_extract(const char* src_path, const char* dst_path, const gamut_sel* rows,
                        gamut_error* err);
GAMUT_API int gamut_write_copy(const char* src_path, const char* dst_path, gamut_error* err);

typedef struct gamut_report gamut_report;   /* the findings of a validation */
/* Validates a file against spec section 16.  A file that breaks rules is
 * not a failure of this call: its findings are in the report.  The call
 * fails only for a bad argument. */
GAMUT_API int gamut_validate(const char* path, gamut_report** out, gamut_error* err);
GAMUT_API int64_t gamut_report_count(const gamut_report* r);
/* Pointers stay valid until gamut_report_free. */
GAMUT_API int gamut_report_get(const gamut_report* r, int64_t i, const char** rule,
                           const char** severity, const char** path, const char** message);
GAMUT_API void gamut_report_free(gamut_report* r);

/* Notes as three parallel lists: keys, kinds ("text", "int", "float",
 * "bool") and values as text (floats in %.17g). */
GAMUT_API int gamut_notes(const gamut_file* f, gamut_strings** keys, gamut_strings** kinds,
                      gamut_strings** values, gamut_error* err);
GAMUT_API int gamut_private_names(const gamut_file* f, gamut_strings** out, gamut_error* err);
/* Writes up to capacity bytes; *n is the record's size (call with
 * capacity 0 to learn it). */
GAMUT_API int gamut_get_private(const gamut_file* f, const char* name, void* out, int64_t capacity,
                            int64_t* n, gamut_error* err);

/* --- Strings --------------------------------------------------------------- */
GAMUT_API int64_t gamut_strings_count(const gamut_strings* s);
GAMUT_API const char* gamut_strings_get(const gamut_strings* s, int64_t i);
GAMUT_API void gamut_strings_free(gamut_strings* s);

#ifdef __cplusplus
}
#endif

#endif /* GAMUT_H */
