/* The C interface of the mestra core: the one surface every binding
 * (Python, MATLAB, Julia) and C or C++ caller uses.  Opaque handles,
 * caller-allocated buffers, UTF-8 strings, and an error record on every
 * failure.  No C++ type and no HDF5 identifier crosses it.
 *
 * Every function returning int returns 0 on success and nonzero on
 * failure, when it fills *err if err is not NULL.  No function keeps a
 * pointer the caller passed after it returns.
 */
#ifndef MESTRA_H
#define MESTRA_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(MESTRA_BUILDING)
#    define MES_API __declspec(dllexport)
#  else
#    define MES_API __declspec(dllimport)
#  endif
#else
#  define MES_API __attribute__((visibility("default")))
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
} mes_error;

/* Element types; the numbers are fixed.  MES_AS_GIVEN in a declaration
 * means the dtype of the first values written (precision kept as given). */
enum {
  MES_AS_GIVEN = 0,
  MES_UINT8 = 1,
  MES_INT8 = 2,
  MES_INT32 = 3,
  MES_INT64 = 4,
  MES_FLOAT32 = 5,
  MES_FLOAT64 = 6
};

/* A selection along one axis. */
enum { MES_SEL_ALL = 0, MES_SEL_RANGE = 1, MES_SEL_INDEX = 2 };
typedef struct {
  int kind;
  int64_t start, stop;     /* MES_SEL_RANGE: [start, stop) */
  const int64_t* index;    /* MES_SEL_INDEX: strictly increasing */
  int64_t count;
} mes_sel;

/* The library's version ("1.0.0.dev0") and the format string it writes
 * ("mestra/1").  Static strings; never freed. */
MES_API const char* mes_version(void);
MES_API const char* mes_format(void);

/* Opaque handles. */
typedef struct mes_file mes_file;        /* a file open to write or to read */
typedef struct mes_strings mes_strings;  /* a list of UTF-8 strings */

/* --- Writing a data file ------------------------------------------------
 * mesh_kind: NULL or "" (no mesh), "shared", "changing".
 * per: "fixed", "run" or "group:<label>" (NULL or "" without a mesh). */
MES_API int mes_create(const char* path, const char* writer, const char* mesh_kind,
                       const char* per, mes_file** out, mes_error* err);
/* An existing data file, to add rows in place. */
MES_API int mes_open_append(const char* path, mes_file** out, mes_error* err);

/* title, license, references or source. */
MES_API int mes_set_attribute(mes_file* f, const char* name, const char* value,
                              mes_error* err);
MES_API int mes_declare_parameter(mes_file* f, const char* name, const char* role,
                                  const char* units, int dtype, int has_bounds,
                                  double lower, double upper, const char* run_group,
                                  mes_error* err);
MES_API int mes_declare_label(mes_file* f, const char* name, const char* role,
                              const char* const* categories, int64_t n_categories,
                              mes_error* err);
/* where: "scalar", "node" or "cell".  Empty strings and has_q = 0 mean
 * absent; round_bits < 0 means no rounding. */
MES_API int mes_declare_result(mes_file* f, const char* name, const char* where,
                               const char* units, int dtype, const char* of,
                               const char* statistic, int has_q, double q,
                               const char* method, const char* with_respect_to,
                               const char* axis, const char* vector, int round_bits,
                               mes_error* err);
MES_API int mes_declare_mesh_label(mes_file* f, const char* name, const char* where,
                                   const char* const* categories, int64_t n_categories,
                                   mes_error* err);
MES_API int mes_declare_coordinates(mes_file* f, const char* units, int dtype, int axes,
                                    mes_error* err);
/* dtype MES_INT64 uses integer_value; MES_FLOAT32 or MES_FLOAT64 float_value. */
MES_API int mes_set_constant(mes_file* f, const char* name, const char* units, int dtype,
                             double float_value, int64_t integer_value, mes_error* err);
MES_API int mes_set_generalisation_group(mes_file* f, const char* label, mes_error* err);
/* gzip_level 0 turns compression off; 1 to 9 with or without shuffle. */
MES_API int mes_set_compression(mes_file* f, int gzip_level, int shuffle, mes_error* err);

/* A geometry is staged, then used by mes_set_mesh or assigned to batch
 * rows or group members.  Each mes_geometry_begin starts a new one. */
MES_API int mes_geometry_begin(mes_file* f, mes_error* err);
/* points may be NULL to give only n_nodes and axes (a shared mesh whose
 * coordinates come with the runs). */
MES_API int mes_geometry_points(mes_file* f, int dtype, const void* points, int64_t n_nodes,
                                int axes, mes_error* err);
MES_API int mes_geometry_cells(mes_file* f, const uint8_t* types, int64_t n_cells,
                               const int64_t* offsets, const int64_t* connectivity,
                               int64_t n_connectivity, mes_error* err);
MES_API int mes_geometry_label(mes_file* f, const char* name, const int64_t* values,
                               int64_t n, mes_error* err);
/* A shared mesh from the staged geometry (cells, fixed labels, and the
 * coordinates when per = fixed). */
MES_API int mes_set_mesh(mes_file* f, mes_error* err);

/* Rows are staged in a batch and committed all or nothing. */
MES_API int mes_batch_begin(mes_file* f, int64_t n_rows, mes_error* err);
/* Parameters, label codes, scalars, and fields (rows x sites, or for a
 * changing mesh every row's values end to end). */
MES_API int mes_batch_values(mes_file* f, const char* name, int dtype, const void* values,
                             int64_t count, mes_error* err);
MES_API int mes_batch_names(mes_file* f, const char* label, const char* const* names,
                            int64_t count, mes_error* err);
/* The staged geometry belongs to the next row of the batch (per = run) or
 * to a group member appearing for the first time (per = group). */
MES_API int mes_batch_geometry_for_row(mes_file* f, mes_error* err);
MES_API int mes_batch_geometry_for_member(mes_file* f, const char* member, mes_error* err);
MES_API int mes_batch_commit(mes_file* f, int64_t* first_id, mes_error* err);
MES_API int mes_flush(mes_file* f, mes_error* err);

/* Closes a file opened by any call and frees the handle; writes what a
 * writer holds.  f may be NULL. */
MES_API int mes_close(mes_file* f, mes_error* err);

/* --- Reading ------------------------------------------------------------- */
MES_API int mes_open(const char* path, mes_file** out, mes_error* err);
/* Worker threads for reading fields: raw chunks come through HDF5 one at a
 * time and are decompressed in parallel outside it.  1 (the default) reads
 * serially. */
MES_API int mes_set_threads(mes_file* f, int threads, mes_error* err);
/* key: "format", "kind", "type", "addons", "row_count", or a file-level
 * attribute ("writer", "created", "file_id", "title", "license",
 * "references", "source", "generalisation_group", "trained_on",
 * "evaluated_from", "support_id", "per", "mesh_kind").  One string, or
 * several for "addons". */
MES_API int mes_info(const mes_file* f, const char* key, mes_strings** out, mes_error* err);
/* group: "parameters", "labels", "scalars", "constants", "node_fields",
 * "cell_fields", "node_labels", "cell_labels", "tables", "models". */
MES_API int mes_names(const mes_file* f, const char* group, mes_strings** out,
                      mes_error* err);
/* A concept's attributes as two parallel lists. */
MES_API int mes_describe(const mes_file* f, const char* name, mes_strings** keys,
                         mes_strings** values, mes_error* err);
/* name: a parameter, label, scalar, constant, field or mesh label, or
 * "row", "coordinates", "cells/types", "cells/offsets",
 * "cells/connectivity".  rows and sites may be NULL (everything).  shape
 * holds up to 4 extents. */
MES_API int mes_shape(const mes_file* f, const char* name, const mes_sel* rows,
                      const mes_sel* sites, int64_t* shape, int* rank, mes_error* err);
MES_API int mes_read(const mes_file* f, const char* name, const mes_sel* rows,
                     const mes_sel* sites, int dtype, void* out, int64_t out_bytes,
                     mes_error* err);
MES_API int mes_label_names(const mes_file* f, const char* label, const mes_sel* rows,
                            mes_strings** out, mes_error* err);
MES_API int mes_table(const mes_file* f, const char* table, mes_strings** out,
                      mes_error* err);

/* --- Strings --------------------------------------------------------------- */
MES_API int64_t mes_strings_count(const mes_strings* s);
MES_API const char* mes_strings_get(const mes_strings* s, int64_t i);
MES_API void mes_strings_free(mes_strings* s);

#ifdef __cplusplus
}
#endif

#endif /* MESTRA_H */
