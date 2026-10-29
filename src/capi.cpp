// The C interface: every gamut_* function, each catching every exception at
// the boundary and turning it into a gamut_error.
#include "gamut/gamut.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "copy.hpp"
#include "evaluate.hpp"
#include "names.hpp"
#include "nearest.hpp"
#include "reader.hpp"
#include "select.hpp"
#include "types.hpp"
#include "units.hpp"
#include "validate.hpp"
#include "writer.hpp"

using gamut_core::DType;
using gamut_core::Error;
using gamut_core::Selection;
using gamut_core::internal::Batch;
using gamut_core::internal::Column;
using gamut_core::internal::Geometry;
using gamut_core::internal::Reader;
using gamut_core::internal::Schema;
using gamut_core::internal::Writer;

struct gamut_file {
  std::unique_ptr<Writer> writer;
  std::unique_ptr<Reader> reader;
  Geometry geometry;
  bool geometry_open = false;
  Batch batch;
  bool batch_open = false;
};

struct gamut_strings {
  std::vector<std::string> items;
};

struct gamut_report {
  gamut_core::internal::Report report;
};

struct gamut_tree {
  gamut_core::internal::Dict root;
};

namespace {

const char kVersion[] = "1.3.0";
const char kFormat[] = "gamut/1";

// HDF5 keeps process-wide state and is built without its thread-safety
// option, so two handles are not independent: every call that reaches a
// file holds this lock, and calls from several threads take turns.  Never
// destroyed, so a handle closed during process exit still finds it.
std::recursive_mutex& hdf5_mutex() {
  static std::recursive_mutex* m = new std::recursive_mutex();
  return *m;
}

using Lock = std::lock_guard<std::recursive_mutex>;

void copy_into(char* dst, std::size_t size, const std::string& src) {
  if (size == 0) return;
  const std::size_t n = src.size() < size - 1 ? src.size() : size - 1;
  std::memcpy(dst, src.data(), n);
  dst[n] = '\0';
}

int fail(gamut_error* err) {
  if (err == nullptr) return 1;
  std::memset(err, 0, sizeof *err);
  try {
    throw;
  } catch (const Error& e) {
    copy_into(err->rule, sizeof err->rule, e.rule());
    copy_into(err->path, sizeof err->path, e.path());
    copy_into(err->message, sizeof err->message, e.what());
  } catch (const std::bad_alloc&) {
    copy_into(err->message, sizeof err->message, "out of memory");
  } catch (const std::exception& e) {
    copy_into(err->message, sizeof err->message, e.what());
  } catch (...) {
    copy_into(err->message, sizeof err->message, "unknown failure");
  }
  return 1;
}

void clear(gamut_error* err) {
  if (err != nullptr) std::memset(err, 0, sizeof *err);
}

std::string str(const char* s) { return s == nullptr ? std::string() : std::string(s); }

void need(bool ok, const std::string& message) {
  if (!ok) throw Error("", message);
}

DType dtype(int code) {
  DType t;
  need(gamut_core::dtype_from_int(code, &t) && t != DType::String,
       "dtype " + std::to_string(code) + " is not one of the GAMUT_* codes");
  return t;
}

// GAMUT_AS_GIVEN (0) in a declaration: the dtype of the first values.
bool as_given(int code) { return code == 0; }

Writer& writer_of(gamut_file* f) {
  need(f != nullptr, "the handle is NULL");
  need(f->writer != nullptr, "this handle was opened for reading; writing needs gamut_create "
                             "or gamut_open_append");
  return *f->writer;
}

const Reader& reader_of(const gamut_file* f) {
  need(f != nullptr, "the handle is NULL");
  need(f->reader != nullptr, "this handle was opened for writing; close it and open it with "
                             "gamut_open to read");
  return *f->reader;
}

std::vector<std::string> list(const char* const* items, int64_t n) {
  std::vector<std::string> out;
  need(n >= 0, "a negative count");
  need(n == 0 || items != nullptr, "a list pointer is NULL");
  for (int64_t i = 0; i < n; ++i) {
    need(items[i] != nullptr, "list entry " + std::to_string(i) + " is NULL");
    out.push_back(items[i]);
  }
  return out;
}

Selection selection(const gamut_sel* s) {
  if (s == nullptr) return Selection::all();
  switch (s->kind) {
    case GAMUT_SEL_ALL: return Selection::all();
    case GAMUT_SEL_RANGE: return Selection::range(s->start, s->stop);
    case GAMUT_SEL_INDEX: {
      need(s->count >= 0 && (s->count == 0 || s->index != nullptr), "an index selection "
                                                                    "needs its indices");
      return Selection::list(std::vector<int64_t>(s->index, s->index + s->count));
    }
    default: break;
  }
  throw Error("", "selection kind " + std::to_string(s->kind) + " is unknown");
}

Column column(int code, const void* values, int64_t count) {
  const DType t = dtype(code);
  need(count >= 0, "a negative count");
  need(count == 0 || values != nullptr, "the values pointer is NULL");
  need(static_cast<uint64_t>(count) <= SIZE_MAX / gamut_core::dtype_size(t), "the count is too large");
  Column c;
  c.dtype = t;
  c.count = count;
  const auto* p = static_cast<const unsigned char*>(values);
  c.bytes.assign(p, p + static_cast<std::size_t>(count) * gamut_core::dtype_size(t));
  return c;
}

// A bare name, or one of the reserved read names, to the reader's path.
std::string path_of(const Schema& s, const std::string& name) {
  if (name == "row" || name == "coordinates" || name.compare(0, 6, "cells/") == 0) return name;
  for (const auto& r : s.results) {
    if (r.name == name) return gamut_core::internal::result_path(r);
  }
  for (const auto& m : s.mesh.labels) {
    if (m.name == name) return gamut_core::internal::mesh_label_path(m);
  }
  return name;
}

gamut_strings* strings(std::vector<std::string> items) {
  auto* s = new gamut_strings;
  s->items = std::move(items);
  return s;
}

gamut_core::internal::Dict& tree_of(gamut_tree* t) {
  need(t != nullptr, "the tree is NULL");
  return t->root;
}

const gamut_core::internal::Dict& tree_of(const gamut_tree* t) {
  need(t != nullptr, "the tree is NULL");
  return t->root;
}

const gamut_core::internal::Value& value_at(const gamut_tree* t, const char* key) {
  const auto* v = gamut_core::internal::find_path(tree_of(t), str(key));
  need(v != nullptr, "the tree has no \"" + str(key) + "\"");
  return *v;
}


}  // namespace

extern "C" {

const char* gamut_version(void) { return kVersion; }
const char* gamut_format(void) { return kFormat; }

int gamut_units_parse(const char* units) {
  try {
    return units != nullptr && gamut_core::units_parse(units) ? 1 : 0;
  } catch (...) {
    return 0;
  }
}

int gamut_create(const char* path, const char* writer, const char* mesh_kind, const char* per,
               gamut_file** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<gamut_file>();
    f->writer = Writer::create(str(path), str(writer), str(mesh_kind), str(per));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_create_model(const char* path, const char* writer, const char* mesh_kind, const char* per,
                     gamut_file** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<gamut_file>();
    f->writer = Writer::create_model(str(path), str(writer), str(mesh_kind),
                                     str(per).empty() ? std::string("fixed") : str(per));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_open_append(const char* path, gamut_file** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<gamut_file>();
    f->writer = Writer::open_append(str(path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_attribute(gamut_file* f, const char* name, const char* value, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).set_attribute(str(name), str(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_declare_parameter(gamut_file* f, const char* name, const char* role, const char* units,
                          int dtype_code, int has_bounds, double lower, double upper,
                          const char* run_group, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::Parameter p;
    p.name = str(name);
    p.role = str(role).empty() ? std::string("design") : str(role);
    p.units = str(units);
    // A parameter's dtype never comes from its values: integers passed to an
    // undeclared one are float64, so a sweep begun at 0, 2, 4 can take 2.5.
    p.dtype = as_given(dtype_code) ? DType::Float64 : dtype(dtype_code);
    if (has_bounds) {
      p.lower = lower;
      p.upper = upper;
    }
    p.run_group = str(run_group);
    writer_of(f).declare_parameter(p);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_declare_label(gamut_file* f, const char* name, const char* role,
                      const char* const* categories, int64_t n, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).declare_label(str(name), str(role), list(categories, n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_declare_result(gamut_file* f, const char* name, const char* where, const char* units,
                       int dtype_code, const char* of, const char* statistic, int has_q,
                       double q, const char* method, const char* with_respect_to,
                       const char* axis, const char* vector, int round_bits, const char* model,
                       const char* output, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::Result r;
    r.name = str(name);
    r.where = str(where);
    r.units = str(units);
    r.auto_dtype = as_given(dtype_code);
    if (!r.auto_dtype) r.dtype = dtype(dtype_code);
    r.relation.of = str(of);
    r.relation.statistic = str(statistic);
    if (has_q) r.relation.q = q;
    r.relation.method = str(method);
    r.relation.with_respect_to = str(with_respect_to);
    if (r.relation.with_respect_to == "coordinates") {
      r.relation.axis = str(axis);
    } else {
      r.axis = str(axis);
    }
    r.vector = str(vector);
    r.round_bits = round_bits;
    r.model = str(model);
    r.output = str(output);
    writer_of(f).declare_result(r);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_declare_mesh_label(gamut_file* f, const char* name, const char* where,
                           const char* const* categories, int64_t n, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::MeshLabel m;
    m.name = str(name);
    m.where = str(where);
    writer_of(f).declare_mesh_label(m, list(categories, n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_declare_coordinates(gamut_file* f, const char* units, int dtype_code, int axes,
                            const char* model, const char* output, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).declare_coordinates(str(units),
                                     as_given(dtype_code) ? DType::String : dtype(dtype_code),
                                     axes, str(model), str(output));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_constant(gamut_file* f, const char* name, const char* units, int dtype_code,
                     double float_value, int64_t integer_value, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::Constant c;
    c.name = str(name);
    c.units = str(units);
    c.dtype = dtype(dtype_code);
    c.f = float_value;
    c.i = integer_value;
    writer_of(f).set_constant(c);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_generalisation_group(gamut_file* f, const char* label, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).set_generalisation_group(str(label));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_compression(gamut_file* f, int gzip_level, int shuffle, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(gzip_level >= 0 && gzip_level <= 9, "gzip_level is 0 (off) to 9");
    gamut_core::FilterPipeline p;
    if (gzip_level > 0) {
      if (shuffle) p.push_back(gamut_core::FilterStep::shuffle());
      p.push_back(gamut_core::FilterStep::gzip(gzip_level));
    }
    writer_of(f).set_compression(p);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_geometry_begin(gamut_file* f, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    f->geometry = Geometry();
    f->geometry_open = true;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_geometry_points(gamut_file* f, int dtype_code, const void* points, int64_t n_nodes,
                        int axes, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call gamut_geometry_begin first");
    need(n_nodes >= 0 && axes >= 1 && axes <= 3, "points are n_nodes x 1 to 3 axes");
    // NULL points give the node count alone: the cells of a shared mesh
    // whose coordinates come with the runs.
    f->geometry.points = points == nullptr ? Column() : column(dtype_code, points, n_nodes * axes);
    f->geometry.n_nodes = n_nodes;
    f->geometry.axes = axes;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_geometry_cells(gamut_file* f, const uint8_t* types, int64_t n_cells,
                       const int64_t* offsets, const int64_t* connectivity,
                       int64_t n_connectivity, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call gamut_geometry_begin first");
    need(n_cells >= 0 && n_connectivity >= 0, "a negative count");
    need(n_cells == 0 || (types != nullptr && offsets != nullptr), "cells need types and offsets");
    need(n_connectivity == 0 || connectivity != nullptr, "connectivity is NULL");
    f->geometry.types.assign(types, types + n_cells);
    f->geometry.offsets.assign(offsets, offsets + (n_cells > 0 ? n_cells + 1 : 0));
    f->geometry.connectivity.assign(connectivity, connectivity + n_connectivity);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_geometry_label(gamut_file* f, const char* name, const int64_t* values, int64_t n,
                       gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call gamut_geometry_begin first");
    need(n >= 0 && (n == 0 || values != nullptr), "label values are missing");
    f->geometry.labels[str(name)] = std::vector<int64_t>(values, values + n);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_mesh(gamut_file* f, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    Writer& w = writer_of(f);
    need(f->geometry_open, "stage the mesh with gamut_geometry_begin first");
    w.set_mesh(f->geometry);
    f->geometry_open = false;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_begin(gamut_file* f, int64_t n_rows, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(n_rows >= 0, "a batch has zero or more rows");
    f->batch = Batch();
    f->batch.runs = n_rows;
    f->batch_open = true;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_values(gamut_file* f, const char* name, int dtype_code, const void* values,
                     int64_t first_axis, int64_t count, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->batch_open, "call gamut_batch_begin first");
    need(f->batch.values.count(str(name)) == 0, str(name) + " was given twice in this batch");
    need(first_axis == 0 || first_axis == f->batch.runs,
         str(name) + ": the array's first axis has " + std::to_string(first_axis) +
             " entries but the batch has " + std::to_string(f->batch.runs) +
             " runs; give runs first (a field is runs x sites), transposed if need be");
    f->batch.values[str(name)] = column(dtype_code, values, count);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_names(gamut_file* f, const char* label, const char* const* names, int64_t count,
                    gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->batch_open, "call gamut_batch_begin first");
    need(f->batch.names.count(str(label)) == 0, str(label) + " was given twice in this batch");
    f->batch.names[str(label)] = list(names, count);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_geometry_for_row(gamut_file* f, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->batch_open && f->geometry_open, "begin a batch and stage a geometry first");
    f->batch.run_geometry.push_back(f->geometry);
    f->geometry_open = false;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_geometry_for_member(gamut_file* f, const char* member, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f);
    need(f->batch_open && f->geometry_open, "begin a batch and stage a geometry first");
    // A member given its geometry again in one batch must give the same one.
    const auto given = f->batch.member_geometry.find(str(member));
    if (given == f->batch.member_geometry.end()) {
      f->batch.member_geometry[str(member)] = f->geometry;
    } else {   // the first stays; the commit checks it
      need(writer_of(f).geometry_print(given->second) == writer_of(f).geometry_print(f->geometry),
           "\"" + str(member) + "\" is given two different geometries in one batch");
    }
    f->geometry_open = false;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_batch_commit(gamut_file* f, int64_t* first_id, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    Writer& w = writer_of(f);
    need(f->batch_open, "call gamut_batch_begin first");
    const int64_t id = w.add_runs(f->batch);
    f->batch = Batch();
    f->batch_open = false;
    if (first_id != nullptr) *first_id = id;
    return 0;
  } catch (...) {
    // A refused batch is discarded; nothing of it was written.
    if (f != nullptr) {
      f->batch = Batch();
      f->batch_open = false;
    }
    return fail(err);
  }
}

int gamut_set_note_text(gamut_file* f, const char* key, const char* value, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).set_note(str(key), gamut_core::AttrValue::text(str(value)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_note_int(gamut_file* f, const char* key, int64_t value, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).set_note(str(key), gamut_core::AttrValue::integer(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_note_float(gamut_file* f, const char* key, double value, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).set_note(str(key), gamut_core::AttrValue::real(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_private(gamut_file* f, const char* name, const void* bytes, int64_t n, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(n >= 0 && (n == 0 || bytes != nullptr), "the bytes are NULL");
    const auto* p = static_cast<const unsigned char*>(bytes);
    writer_of(f).set_private(str(name), std::vector<unsigned char>(p, p + n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_flush(gamut_file* f, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).flush();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_close(gamut_file* f, gamut_error* err) {
  clear(err);
  if (f == nullptr) return 0;
  try {
    const Lock lock(hdf5_mutex());
    if (f->writer) f->writer->close();
    delete f;   // a reader's file closes here
  } catch (...) {
    // The handle stays open: fix what the error names and close again, or
    // give up with gamut_abandon.
    return fail(err);
  }
  return 0;
}

int gamut_append(const char* dst_path, const char* src_path, int64_t* rows_added,
               gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    const int64_t n = gamut_core::internal::append_file(str(dst_path), str(src_path));
    if (rows_added != nullptr) *rows_added = n;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_extract(const char* src_path, const char* dst_path, const gamut_sel* rows,
                gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::extract_file(str(src_path), str(dst_path), selection(rows));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_write_copy(const char* src_path, const char* dst_path, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    gamut_core::internal::write_copy_file(str(src_path), str(dst_path));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

void gamut_abandon(gamut_file* f, int remove_file) {
  if (f == nullptr) return;
  try {
    const Lock lock(hdf5_mutex());
    std::unique_ptr<gamut_file> owned(f);
    if (owned->writer) owned->writer->abandon(remove_file != 0);
  } catch (...) {
    // Abandoning reports nothing; the handle is freed with the lock held,
    // or, if the lock itself failed, not at all.
  }
}

int gamut_open(const char* path, gamut_file** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<gamut_file>();
    f->reader = Reader::open(str(path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_set_threads(gamut_file* f, int threads, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(f != nullptr && f->reader != nullptr, "threads apply to a file open to read");
    need(threads >= 1 && threads <= 256, "threads is 1 to 256");
    f->reader->set_threads(threads);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_info(const gamut_file* f, const char* key, gamut_strings** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    const Schema& s = reader_of(f).schema();
    const std::string k = str(key);
    std::vector<std::string> v;
    if (k == "format") v = {"gamut/1"};
    else if (k == "kind") v = {s.kind};
    else if (k == "type") v = {s.type()};
    else if (k == "addons") v = s.addons();
    else if (k == "row_count") v = {std::to_string(s.rows)};
    else if (k == "writer") v = {s.writer};
    else if (k == "created") v = {s.created};
    else if (k == "file_id") v = {s.file_id};
    else if (k == "title") v = {s.title};
    else if (k == "license") v = {s.license};
    else if (k == "references") v = {s.references};
    else if (k == "source") v = {s.source};
    else if (k == "portion_marking") v = {s.portion_marking};
    else if (k == "generalisation_group") v = {s.generalisation_group};
    else if (k == "trained_on") v = {s.trained_on};
    else if (k == "evaluated_from") v = {s.evaluated_from};
    else if (k == "support_id") v = {s.mesh.support_id};
    else if (k == "per") v = {s.mesh.kind.empty() ? std::string() : s.mesh.per};
    else if (k == "mesh_kind") v = {s.mesh.kind};
    else throw Error("", "no information called \"" + k + "\"");
    *out = strings(std::move(v));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_names(const gamut_file* f, const char* group, gamut_strings** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).names(str(group)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_describe(const gamut_file* f, const char* name, gamut_strings** keys, gamut_strings** values,
                 gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(keys != nullptr && values != nullptr, "keys or values is NULL");
    const Reader& r = reader_of(f);
    std::vector<std::pair<std::string, std::string>> pairs;
    if (str(name).empty()) {
      // The file itself.
      const Schema& s = r.schema();
      const std::pair<const char*, std::string> all[] = {
          {"format", "gamut/1"}, {"kind", s.kind}, {"type", s.type()},
          {"row_count", std::to_string(s.rows)}, {"writer", s.writer},
          {"created", s.created}, {"file_id", s.file_id}, {"title", s.title},
          {"license", s.license}, {"references", s.references}, {"source", s.source},
          {"portion_marking", s.portion_marking},
          {"generalisation_group", s.generalisation_group}, {"trained_on", s.trained_on},
          {"evaluated_from", s.evaluated_from}, {"mesh", s.mesh.kind},
          {"per", s.mesh.kind.empty() ? std::string() : s.mesh.per},
          {"support_id", s.mesh.support_id}};
      for (const auto& p : all) {
        if (!p.second.empty()) pairs.emplace_back(p.first, p.second);
      }
    } else {
      pairs = r.describe(path_of(r.schema(), str(name)));
    }
    std::vector<std::string> k, v;
    for (const auto& p : pairs) {
      k.push_back(p.first);
      v.push_back(p.second);
    }
    *keys = strings(std::move(k));
    *values = strings(std::move(v));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_shape(const gamut_file* f, const char* name, const gamut_sel* rows, const gamut_sel* sites,
              int64_t* shape, int* rank, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(shape != nullptr && rank != nullptr, "shape or rank is NULL");
    const Reader& r = reader_of(f);
    const auto s = r.shape(path_of(r.schema(), str(name)), selection(rows), selection(sites));
    need(s.size() <= 4, "internal: more than four axes");
    *rank = static_cast<int>(s.size());
    for (std::size_t i = 0; i < s.size(); ++i) shape[i] = s[i];
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_read(const gamut_file* f, const char* name, const gamut_sel* rows, const gamut_sel* sites,
             int dtype_code, void* out, int64_t out_bytes, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out_bytes >= 0 && (out_bytes == 0 || out != nullptr), "the output buffer is NULL");
    const Reader& r = reader_of(f);
    r.read(path_of(r.schema(), str(name)), selection(rows), selection(sites), dtype(dtype_code),
           out, static_cast<std::size_t>(out_bytes));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_label_names(const gamut_file* f, const char* label, const gamut_sel* rows, gamut_strings** out,
                    gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).label_names(str(label), selection(rows)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_outside(const gamut_file* f, const char* name, const gamut_sel* rows, double* out,
                int64_t out_bytes, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out_bytes >= 0 && (out_bytes == 0 || out != nullptr), "the output buffer is NULL");
    reader_of(f).outside(str(name), selection(rows), out, static_cast<std::size_t>(out_bytes));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_select(const gamut_file* f, const char* where, int64_t* out, int64_t capacity, int64_t* n,
               gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(n != nullptr, "n is NULL");
    const auto rows = gamut_core::internal::select_rows(reader_of(f), str(where));
    need(static_cast<int64_t>(rows.size()) <= capacity && (rows.empty() || out != nullptr),
         "the output buffer holds " + std::to_string(capacity) + " positions and " +
             std::to_string(rows.size()) + " rows are selected");
    if (!rows.empty()) std::memcpy(out, rows.data(), rows.size() * sizeof(int64_t));
    *n = static_cast<int64_t>(rows.size());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_notes(const gamut_file* f, gamut_strings** keys, gamut_strings** kinds, gamut_strings** values,
              gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(keys != nullptr && kinds != nullptr && values != nullptr, "an output is NULL");
    std::vector<std::string> k, t, v;
    for (const auto& kv : reader_of(f).notes()) {
      k.push_back(kv.first);
      switch (kv.second.kind()) {
        case gamut_core::AttrValue::Kind::Str: t.push_back("text"); v.push_back(kv.second.as_text()); break;
        case gamut_core::AttrValue::Kind::Int: t.push_back("int"); v.push_back(std::to_string(kv.second.as_int())); break;
        case gamut_core::AttrValue::Kind::Bool: t.push_back("bool"); v.push_back(kv.second.as_bool() ? "1" : "0"); break;
        case gamut_core::AttrValue::Kind::Float: {
          char buf[40];
          std::snprintf(buf, sizeof buf, "%.17g", kv.second.as_float());
          t.push_back("float");
          v.push_back(buf);
          break;
        }
      }
    }
    *keys = strings(std::move(k));
    *kinds = strings(std::move(t));
    *values = strings(std::move(v));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_private_names(const gamut_file* f, gamut_strings** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).private_names());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_get_private(const gamut_file* f, const char* name, void* out, int64_t capacity, int64_t* n,
                    gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(n != nullptr, "n is NULL");
    const auto bytes = reader_of(f).private_record(str(name));
    *n = static_cast<int64_t>(bytes.size());
    if (capacity > 0) {
      need(out != nullptr, "out is NULL");
      std::memcpy(out, bytes.data(), std::min<std::size_t>(bytes.size(), static_cast<std::size_t>(capacity)));
    }
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_table(const gamut_file* f, const char* table, gamut_strings** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).table(str(table)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_new(gamut_tree** out, gamut_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = new gamut_tree;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

void gamut_tree_free(gamut_tree* t) { delete t; }

#define GAMUT_TREE_SET(expr)                                              \
  try {                                                                 \
    clear(err);                                                         \
    gamut_core::internal::set_path(tree_of(t), str(key), expr);             \
    return 0;                                                           \
  } catch (...) {                                                       \
    return fail(err);                                                   \
  }

int gamut_tree_set_null(gamut_tree* t, const char* key, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::null())
}
int gamut_tree_set_bool(gamut_tree* t, const char* key, int value, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::boolean(value != 0))
}
int gamut_tree_set_int(gamut_tree* t, const char* key, int64_t value, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::integer(value))
}
int gamut_tree_set_float(gamut_tree* t, const char* key, double value, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::real(value))
}
int gamut_tree_set_string(gamut_tree* t, const char* key, const char* value, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::text(str(value)))
}
int gamut_tree_set_dict(gamut_tree* t, const char* key, gamut_error* err) {
  GAMUT_TREE_SET(gamut_core::internal::Value::dict(gamut_core::internal::Dict()))
}

int gamut_tree_set_array(gamut_tree* t, const char* key, int dtype_code, const void* data, int rank,
                       const int64_t* shape, gamut_error* err) {
  try {
    clear(err);
    const DType d = dtype(dtype_code);
    need(rank >= 1 && rank <= 8 && shape != nullptr, "an array has 1 to 8 axes");
    std::vector<int64_t> s(shape, shape + rank);
    int64_t n = 1;
    for (const auto e : s) {
      need(e >= 0, "a negative extent");
      need(e == 0 || n <= std::numeric_limits<int64_t>::max() / e, "an array too large");
      n *= e;
    }
    need(n <= std::numeric_limits<int64_t>::max() / static_cast<int64_t>(gamut_core::dtype_size(d)),
         "an array too large");
    need(n == 0 || data != nullptr, "the array's data is NULL");
    const auto* p = static_cast<const unsigned char*>(data);
    std::vector<unsigned char> bytes(p, p + static_cast<std::size_t>(n) * gamut_core::dtype_size(d));
    gamut_core::internal::set_path(tree_of(t), str(key),
                               gamut_core::internal::Value::numbers(d, s, std::move(bytes)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_set_strings(gamut_tree* t, const char* key, const char* const* items, int64_t n,
                         gamut_error* err) {
  try {
    clear(err);
    gamut_core::internal::set_path(tree_of(t), str(key),
                               gamut_core::internal::Value::strings({n}, list(items, n)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_keys(const gamut_tree* t, const char* key, gamut_strings** out, gamut_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    const gamut_core::internal::Dict* d = &tree_of(t);
    if (!str(key).empty()) {
      const auto& v = value_at(t, key);
      need(v.kind() == gamut_core::internal::Value::Kind::Dict, "\"" + str(key) + "\" is not a dictionary");
      d = &v.as_dict();
    }
    std::vector<std::string> keys;
    for (const auto& kv : *d) keys.push_back(kv.first);
    *out = strings(std::move(keys));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_kind(const gamut_tree* t, const char* key, int* kind, gamut_error* err) {
  try {
    clear(err);
    need(kind != nullptr, "kind is NULL");
    if (str(key).empty()) {
      tree_of(t);
      *kind = GAMUT_TREE_DICT;
      return 0;
    }
    const auto* v = gamut_core::internal::find_path(tree_of(t), str(key));
    *kind = v == nullptr ? GAMUT_TREE_ABSENT : static_cast<int>(v->kind());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_scalar(const gamut_tree* t, const char* key, int64_t* integer, double* real,
                    gamut_error* err) {
  try {
    clear(err);
    const auto& v = value_at(t, key);
    using K = gamut_core::internal::Value::Kind;
    need(v.kind() == K::Bool || v.kind() == K::Int || v.kind() == K::Float,
         "\"" + str(key) + "\" is not a number or a boolean");
    if (integer != nullptr) *integer = v.as_int();
    if (real != nullptr) *real = v.kind() == K::Float ? v.as_float() : static_cast<double>(v.as_int());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_strings(const gamut_tree* t, const char* key, gamut_strings** out, gamut_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    const auto& v = value_at(t, key);
    using K = gamut_core::internal::Value::Kind;
    need(v.kind() == K::Str || v.kind() == K::Strings, "\"" + str(key) + "\" is not text");
    *out = strings(v.kind() == K::Str ? std::vector<std::string>{v.as_text()} : v.items());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_array_info(const gamut_tree* t, const char* key, int* dtype_out, int* rank,
                        int64_t* shape, gamut_error* err) {
  try {
    clear(err);
    need(dtype_out != nullptr && rank != nullptr && shape != nullptr, "an output is NULL");
    const auto& v = value_at(t, key);
    need(v.kind() == gamut_core::internal::Value::Kind::Numbers, "\"" + str(key) + "\" is not an array");
    need(v.shape().size() <= 8, "more than 8 axes");
    *dtype_out = static_cast<int>(v.dtype());
    *rank = static_cast<int>(v.shape().size());
    for (std::size_t i = 0; i < v.shape().size(); ++i) shape[i] = v.shape()[i];
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_tree_array(const gamut_tree* t, const char* key, void* out, int64_t out_bytes,
                   gamut_error* err) {
  try {
    clear(err);
    const auto& v = value_at(t, key);
    need(v.kind() == gamut_core::internal::Value::Kind::Numbers, "\"" + str(key) + "\" is not an array");
    need(out_bytes >= static_cast<int64_t>(v.bytes().size()),
         "the buffer holds " + std::to_string(out_bytes) + " bytes and the array " +
             std::to_string(v.bytes().size()));
    if (out_bytes > 0) std::memcpy(out, v.bytes().data(), v.bytes().size());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_add_model(gamut_file* f, const char* id, const char* type, const char* const* inputs,
                  int64_t n_inputs, const gamut_tree* numbers, const char* repr, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    writer_of(f).add_model(str(id), str(type), list(inputs, n_inputs), tree_of(numbers), str(repr));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_model_numbers(const gamut_file* f, const char* id, gamut_tree** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto t = std::make_unique<gamut_tree>();
    t->root = reader_of(f).model_numbers(str(id));
    *out = t.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_nearest_check(const gamut_tree* numbers, gamut_error* err) {
  try {
    clear(err);
    gamut_core::internal::nearest_from(tree_of(numbers));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_nearest_output_size(const gamut_tree* numbers, const char* output, int64_t* per_row,
                            gamut_error* err) {
  try {
    clear(err);
    need(per_row != nullptr, "per_row is NULL");
    const auto m = gamut_core::internal::nearest_from(tree_of(numbers));
    *per_row = gamut_core::internal::nearest_output_size(m, str(output));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_nearest_call(const gamut_tree* numbers, const char* const* input_names,
                     const double* const* columns, int n_inputs, int64_t n_rows,
                     const char* output, double* out, int64_t out_count, gamut_error* err) {
  try {
    clear(err);
    need(n_inputs >= 0 && n_rows >= 0, "a negative count");
    need(n_inputs == 0 || (input_names != nullptr && columns != nullptr), "inputs are NULL");
    const auto m = gamut_core::internal::nearest_from(tree_of(numbers));
    std::map<std::string, const double*> table;
    for (int j = 0; j < n_inputs; ++j) table[str(input_names[j])] = columns[j];
    const auto idx = gamut_core::internal::nearest_indices(m, table, n_rows);
    const auto values = gamut_core::internal::nearest_values(m, str(output), idx);
    need(out_count == static_cast<int64_t>(values.size()),
         "the output buffer holds " + std::to_string(out_count) + " values and the output needs " +
             std::to_string(values.size()));
    need(values.empty() || out != nullptr, "out is NULL");
    if (!values.empty()) std::memcpy(out, values.data(), values.size() * sizeof(double));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_evaluate_begin(const gamut_file* model, const char* out_path, gamut_file** out,
                       gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<gamut_file>();
    f->writer = gamut_core::internal::begin_evaluation(reader_of(model), str(out_path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int gamut_validate(const char* path, gamut_report** out, gamut_error* err) {
  try {
    const Lock lock(hdf5_mutex());
    clear(err);
    need(out != nullptr, "out is NULL");
    need(path != nullptr, "path is NULL");
    auto r = std::make_unique<gamut_report>();
    r->report = gamut_core::internal::validate_file(path);
    *out = r.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int64_t gamut_report_count(const gamut_report* r) {
  return r == nullptr ? 0 : static_cast<int64_t>(r->report.findings.size());
}

int gamut_report_get(const gamut_report* r, int64_t i, const char** rule, const char** severity,
                   const char** path, const char** message) {
  if (r == nullptr || i < 0 || i >= static_cast<int64_t>(r->report.findings.size())) return 1;
  const auto& f = r->report.findings[static_cast<std::size_t>(i)];
  if (rule != nullptr) *rule = f.rule.c_str();
  if (severity != nullptr) *severity = f.severity.c_str();
  if (path != nullptr) *path = f.path.c_str();
  if (message != nullptr) *message = f.message.c_str();
  return 0;
}

void gamut_report_free(gamut_report* r) { delete r; }

int64_t gamut_strings_count(const gamut_strings* s) {
  return s == nullptr ? 0 : static_cast<int64_t>(s->items.size());
}

const char* gamut_strings_get(const gamut_strings* s, int64_t i) {
  if (s == nullptr || i < 0 || i >= static_cast<int64_t>(s->items.size())) return nullptr;
  return s->items[static_cast<std::size_t>(i)].c_str();
}

void gamut_strings_free(gamut_strings* s) { delete s; }

}  // extern "C"
