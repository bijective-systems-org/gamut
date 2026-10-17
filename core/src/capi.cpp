// The C interface: every mes_* function, each catching every exception at
// the boundary and turning it into a mes_error.
#include "mestra/mestra.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "evaluate.hpp"
#include "names.hpp"
#include "nearest.hpp"
#include "reader.hpp"
#include "select.hpp"
#include "types.hpp"
#include "units.hpp"
#include "validate.hpp"
#include "writer.hpp"

using mestra::DType;
using mestra::Error;
using mestra::Selection;
using mestra::internal::Batch;
using mestra::internal::Column;
using mestra::internal::Geometry;
using mestra::internal::Reader;
using mestra::internal::Schema;
using mestra::internal::Writer;

struct mes_file {
  std::unique_ptr<Writer> writer;
  std::unique_ptr<Reader> reader;
  Geometry geometry;
  bool geometry_open = false;
  Batch batch;
  bool batch_open = false;
};

struct mes_strings {
  std::vector<std::string> items;
};

struct mes_report {
  mestra::internal::Report report;
};

struct mes_tree {
  mestra::internal::Dict root;
};

namespace {

const char kVersion[] = "1.0.0.dev0";
const char kFormat[] = "mestra/1";

void copy_into(char* dst, std::size_t size, const std::string& src) {
  if (size == 0) return;
  const std::size_t n = src.size() < size - 1 ? src.size() : size - 1;
  std::memcpy(dst, src.data(), n);
  dst[n] = '\0';
}

int fail(mes_error* err) {
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

void clear(mes_error* err) {
  if (err != nullptr) std::memset(err, 0, sizeof *err);
}

std::string str(const char* s) { return s == nullptr ? std::string() : std::string(s); }

void need(bool ok, const std::string& message) {
  if (!ok) throw Error("", message);
}

DType dtype(int code) {
  DType t;
  need(mestra::dtype_from_int(code, &t) && t != DType::String,
       "dtype " + std::to_string(code) + " is not one of the MES_* codes");
  return t;
}

// MES_AS_GIVEN (0) in a declaration: the dtype of the first values.
bool as_given(int code) { return code == 0; }

Writer& writer_of(mes_file* f) {
  need(f != nullptr, "the handle is NULL");
  need(f->writer != nullptr, "this handle was opened for reading; writing needs mes_create "
                             "or mes_open_append");
  return *f->writer;
}

const Reader& reader_of(const mes_file* f) {
  need(f != nullptr, "the handle is NULL");
  need(f->reader != nullptr, "this handle was opened for writing; close it and open it with "
                             "mes_open to read");
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

Selection selection(const mes_sel* s) {
  if (s == nullptr) return Selection::all();
  switch (s->kind) {
    case MES_SEL_ALL: return Selection::all();
    case MES_SEL_RANGE: return Selection::range(s->start, s->stop);
    case MES_SEL_INDEX: {
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
  need(static_cast<uint64_t>(count) <= SIZE_MAX / mestra::dtype_size(t), "the count is too large");
  Column c;
  c.dtype = t;
  c.count = count;
  const auto* p = static_cast<const unsigned char*>(values);
  c.bytes.assign(p, p + static_cast<std::size_t>(count) * mestra::dtype_size(t));
  return c;
}

// A bare name, or one of the reserved read names, to the reader's path.
std::string path_of(const Schema& s, const std::string& name) {
  if (name == "row" || name == "coordinates" || name.compare(0, 6, "cells/") == 0) return name;
  for (const auto& r : s.results) {
    if (r.name == name) return mestra::internal::result_path(r);
  }
  for (const auto& m : s.mesh.labels) {
    if (m.name == name) return mestra::internal::mesh_label_path(m);
  }
  return name;
}

mes_strings* strings(std::vector<std::string> items) {
  auto* s = new mes_strings;
  s->items = std::move(items);
  return s;
}

mestra::internal::Dict& tree_of(mes_tree* t) {
  need(t != nullptr, "the tree is NULL");
  return t->root;
}

const mestra::internal::Dict& tree_of(const mes_tree* t) {
  need(t != nullptr, "the tree is NULL");
  return t->root;
}

const mestra::internal::Value& value_at(const mes_tree* t, const char* key) {
  const auto* v = mestra::internal::find_path(tree_of(t), str(key));
  need(v != nullptr, "the tree has no \"" + str(key) + "\"");
  return *v;
}


}  // namespace

extern "C" {

const char* mes_version(void) { return kVersion; }
const char* mes_format(void) { return kFormat; }

int mes_units_parse(const char* units) {
  try {
    return units != nullptr && mestra::units_parse(units) ? 1 : 0;
  } catch (...) {
    return 0;
  }
}

int mes_create(const char* path, const char* writer, const char* mesh_kind, const char* per,
               mes_file** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<mes_file>();
    f->writer = Writer::create(str(path), str(writer), str(mesh_kind),
                               str(per).empty() ? std::string("fixed") : str(per));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_create_model(const char* path, const char* writer, const char* mesh_kind, const char* per,
                     mes_file** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<mes_file>();
    f->writer = Writer::create_model(str(path), str(writer), str(mesh_kind),
                                     str(per).empty() ? std::string("fixed") : str(per));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_open_append(const char* path, mes_file** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<mes_file>();
    f->writer = Writer::open_append(str(path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_attribute(mes_file* f, const char* name, const char* value, mes_error* err) {
  try {
    clear(err);
    writer_of(f).set_attribute(str(name), str(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_declare_parameter(mes_file* f, const char* name, const char* role, const char* units,
                          int dtype_code, int has_bounds, double lower, double upper,
                          const char* run_group, mes_error* err) {
  try {
    clear(err);
    mestra::internal::Parameter p;
    p.name = str(name);
    p.role = str(role).empty() ? std::string("design") : str(role);
    p.units = str(units);
    p.auto_dtype = as_given(dtype_code);
    if (!p.auto_dtype) p.dtype = dtype(dtype_code);
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

int mes_declare_label(mes_file* f, const char* name, const char* role,
                      const char* const* categories, int64_t n, mes_error* err) {
  try {
    clear(err);
    writer_of(f).declare_label(str(name), str(role), list(categories, n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_declare_result(mes_file* f, const char* name, const char* where, const char* units,
                       int dtype_code, const char* of, const char* statistic, int has_q,
                       double q, const char* method, const char* with_respect_to,
                       const char* axis, const char* vector, int round_bits, const char* model,
                       const char* output, mes_error* err) {
  try {
    clear(err);
    mestra::internal::Result r;
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

int mes_declare_mesh_label(mes_file* f, const char* name, const char* where,
                           const char* const* categories, int64_t n, mes_error* err) {
  try {
    clear(err);
    mestra::internal::MeshLabel m;
    m.name = str(name);
    m.where = str(where);
    writer_of(f).declare_mesh_label(m, list(categories, n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_declare_coordinates(mes_file* f, const char* units, int dtype_code, int axes,
                            const char* model, const char* output, mes_error* err) {
  try {
    clear(err);
    writer_of(f).declare_coordinates(str(units),
                                     as_given(dtype_code) ? DType::String : dtype(dtype_code),
                                     axes, str(model), str(output));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_constant(mes_file* f, const char* name, const char* units, int dtype_code,
                     double float_value, int64_t integer_value, mes_error* err) {
  try {
    clear(err);
    mestra::internal::Constant c;
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

int mes_set_generalisation_group(mes_file* f, const char* label, mes_error* err) {
  try {
    clear(err);
    writer_of(f).set_generalisation_group(str(label));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_compression(mes_file* f, int gzip_level, int shuffle, mes_error* err) {
  try {
    clear(err);
    need(gzip_level >= 0 && gzip_level <= 9, "gzip_level is 0 (off) to 9");
    mestra::FilterPipeline p;
    if (gzip_level > 0) {
      if (shuffle) p.push_back(mestra::FilterStep::shuffle());
      p.push_back(mestra::FilterStep::gzip(gzip_level));
    }
    writer_of(f).set_compression(p);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_geometry_begin(mes_file* f, mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    f->geometry = Geometry();
    f->geometry_open = true;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_geometry_points(mes_file* f, int dtype_code, const void* points, int64_t n_nodes,
                        int axes, mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call mes_geometry_begin first");
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

int mes_geometry_cells(mes_file* f, const uint8_t* types, int64_t n_cells,
                       const int64_t* offsets, const int64_t* connectivity,
                       int64_t n_connectivity, mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call mes_geometry_begin first");
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

int mes_geometry_label(mes_file* f, const char* name, const int64_t* values, int64_t n,
                       mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->geometry_open, "call mes_geometry_begin first");
    need(n >= 0 && (n == 0 || values != nullptr), "label values are missing");
    f->geometry.labels[str(name)] = std::vector<int64_t>(values, values + n);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_mesh(mes_file* f, mes_error* err) {
  try {
    clear(err);
    Writer& w = writer_of(f);
    need(f->geometry_open, "stage the mesh with mes_geometry_begin first");
    w.set_mesh(f->geometry);
    f->geometry_open = false;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_batch_begin(mes_file* f, int64_t n_rows, mes_error* err) {
  try {
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

int mes_batch_values(mes_file* f, const char* name, int dtype_code, const void* values,
                     int64_t count, mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->batch_open, "call mes_batch_begin first");
    need(f->batch.values.count(str(name)) == 0, str(name) + " was given twice in this batch");
    f->batch.values[str(name)] = column(dtype_code, values, count);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_batch_names(mes_file* f, const char* label, const char* const* names, int64_t count,
                    mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->batch_open, "call mes_batch_begin first");
    need(f->batch.names.count(str(label)) == 0, str(label) + " was given twice in this batch");
    f->batch.names[str(label)] = list(names, count);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_batch_geometry_for_row(mes_file* f, mes_error* err) {
  try {
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

int mes_batch_geometry_for_member(mes_file* f, const char* member, mes_error* err) {
  try {
    clear(err);
    writer_of(f);
    need(f->batch_open && f->geometry_open, "begin a batch and stage a geometry first");
    need(f->batch.member_geometry.count(str(member)) == 0,
         "\"" + str(member) + "\" was given a geometry twice in this batch");
    f->batch.member_geometry[str(member)] = f->geometry;
    f->geometry_open = false;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_batch_commit(mes_file* f, int64_t* first_id, mes_error* err) {
  try {
    clear(err);
    Writer& w = writer_of(f);
    need(f->batch_open, "call mes_batch_begin first");
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

int mes_set_note_text(mes_file* f, const char* key, const char* value, mes_error* err) {
  try {
    clear(err);
    writer_of(f).set_note(str(key), mestra::AttrValue::text(str(value)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_note_int(mes_file* f, const char* key, int64_t value, mes_error* err) {
  try {
    clear(err);
    writer_of(f).set_note(str(key), mestra::AttrValue::integer(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_note_float(mes_file* f, const char* key, double value, mes_error* err) {
  try {
    clear(err);
    writer_of(f).set_note(str(key), mestra::AttrValue::real(value));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_private(mes_file* f, const char* name, const void* bytes, int64_t n, mes_error* err) {
  try {
    clear(err);
    need(n >= 0 && (n == 0 || bytes != nullptr), "the bytes are NULL");
    const auto* p = static_cast<const unsigned char*>(bytes);
    writer_of(f).set_private(str(name), std::vector<unsigned char>(p, p + n));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_flush(mes_file* f, mes_error* err) {
  try {
    clear(err);
    writer_of(f).flush();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_close(mes_file* f, mes_error* err) {
  clear(err);
  if (f == nullptr) return 0;
  std::unique_ptr<mes_file> owned(f);
  try {
    if (owned->writer) owned->writer->close();
    owned->reader.reset();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

void mes_abandon(mes_file* f, int remove_file) {
  if (f == nullptr) return;
  std::unique_ptr<mes_file> owned(f);
  try {
    if (owned->writer) owned->writer->abandon(remove_file != 0);
  } catch (...) {
    // Abandoning reports nothing; the handle is freed either way.
  }
}

int mes_open(const char* path, mes_file** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<mes_file>();
    f->reader = Reader::open(str(path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_set_threads(mes_file* f, int threads, mes_error* err) {
  try {
    clear(err);
    need(f != nullptr && f->reader != nullptr, "threads apply to a file open to read");
    need(threads >= 1 && threads <= 256, "threads is 1 to 256");
    f->reader->set_threads(threads);
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_info(const mes_file* f, const char* key, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    const Schema& s = reader_of(f).schema();
    const std::string k = str(key);
    std::vector<std::string> v;
    if (k == "format") v = {"mestra/1"};
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

int mes_names(const mes_file* f, const char* group, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).names(str(group)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_describe(const mes_file* f, const char* name, mes_strings** keys, mes_strings** values,
                 mes_error* err) {
  try {
    clear(err);
    need(keys != nullptr && values != nullptr, "keys or values is NULL");
    const Reader& r = reader_of(f);
    std::vector<std::pair<std::string, std::string>> pairs;
    if (str(name).empty()) {
      // The file itself (interface section 4).
      const Schema& s = r.schema();
      const std::pair<const char*, std::string> all[] = {
          {"format", "mestra/1"}, {"kind", s.kind}, {"type", s.type()},
          {"row_count", std::to_string(s.rows)}, {"writer", s.writer},
          {"created", s.created}, {"file_id", s.file_id}, {"title", s.title},
          {"license", s.license}, {"references", s.references}, {"source", s.source},
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

int mes_shape(const mes_file* f, const char* name, const mes_sel* rows, const mes_sel* sites,
              int64_t* shape, int* rank, mes_error* err) {
  try {
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

int mes_read(const mes_file* f, const char* name, const mes_sel* rows, const mes_sel* sites,
             int dtype_code, void* out, int64_t out_bytes, mes_error* err) {
  try {
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

int mes_label_names(const mes_file* f, const char* label, const mes_sel* rows, mes_strings** out,
                    mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).label_names(str(label), selection(rows)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_select(const mes_file* f, const char* where, int64_t* out, int64_t capacity, int64_t* n,
               mes_error* err) {
  try {
    clear(err);
    need(n != nullptr, "n is NULL");
    const auto rows = mestra::internal::select_rows(reader_of(f), str(where));
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

int mes_notes(const mes_file* f, mes_strings** keys, mes_strings** kinds, mes_strings** values,
              mes_error* err) {
  try {
    clear(err);
    need(keys != nullptr && kinds != nullptr && values != nullptr, "an output is NULL");
    std::vector<std::string> k, t, v;
    for (const auto& kv : reader_of(f).notes()) {
      k.push_back(kv.first);
      switch (kv.second.kind()) {
        case mestra::AttrValue::Kind::Str: t.push_back("text"); v.push_back(kv.second.as_text()); break;
        case mestra::AttrValue::Kind::Int: t.push_back("int"); v.push_back(std::to_string(kv.second.as_int())); break;
        case mestra::AttrValue::Kind::Bool: t.push_back("bool"); v.push_back(kv.second.as_bool() ? "1" : "0"); break;
        case mestra::AttrValue::Kind::Float: {
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

int mes_private_names(const mes_file* f, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).private_names());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_get_private(const mes_file* f, const char* name, void* out, int64_t capacity, int64_t* n,
                    mes_error* err) {
  try {
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

int mes_table(const mes_file* f, const char* table, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = strings(reader_of(f).table(str(table)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_new(mes_tree** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    *out = new mes_tree;
    return 0;
  } catch (...) {
    return fail(err);
  }
}

void mes_tree_free(mes_tree* t) { delete t; }

#define MES_TREE_SET(expr)                                              \
  try {                                                                 \
    clear(err);                                                         \
    mestra::internal::set_path(tree_of(t), str(key), expr);             \
    return 0;                                                           \
  } catch (...) {                                                       \
    return fail(err);                                                   \
  }

int mes_tree_set_null(mes_tree* t, const char* key, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::null())
}
int mes_tree_set_bool(mes_tree* t, const char* key, int value, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::boolean(value != 0))
}
int mes_tree_set_int(mes_tree* t, const char* key, int64_t value, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::integer(value))
}
int mes_tree_set_float(mes_tree* t, const char* key, double value, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::real(value))
}
int mes_tree_set_string(mes_tree* t, const char* key, const char* value, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::text(str(value)))
}
int mes_tree_set_dict(mes_tree* t, const char* key, mes_error* err) {
  MES_TREE_SET(mestra::internal::Value::dict(mestra::internal::Dict()))
}

int mes_tree_set_array(mes_tree* t, const char* key, int dtype_code, const void* data, int rank,
                       const int64_t* shape, mes_error* err) {
  try {
    clear(err);
    const DType d = dtype(dtype_code);
    need(rank >= 1 && rank <= 8 && shape != nullptr, "an array has 1 to 8 axes");
    std::vector<int64_t> s(shape, shape + rank);
    int64_t n = 1;
    for (const auto e : s) {
      need(e >= 0, "a negative extent");
      n *= e;
    }
    need(n == 0 || data != nullptr, "the array's data is NULL");
    const auto* p = static_cast<const unsigned char*>(data);
    std::vector<unsigned char> bytes(p, p + static_cast<std::size_t>(n) * mestra::dtype_size(d));
    mestra::internal::set_path(tree_of(t), str(key),
                               mestra::internal::Value::numbers(d, s, std::move(bytes)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_set_strings(mes_tree* t, const char* key, const char* const* items, int64_t n,
                         mes_error* err) {
  try {
    clear(err);
    mestra::internal::set_path(tree_of(t), str(key),
                               mestra::internal::Value::strings({n}, list(items, n)));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_keys(const mes_tree* t, const char* key, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    const mestra::internal::Dict* d = &tree_of(t);
    if (!str(key).empty()) {
      const auto& v = value_at(t, key);
      need(v.kind() == mestra::internal::Value::Kind::Dict, "\"" + str(key) + "\" is not a dictionary");
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

int mes_tree_kind(const mes_tree* t, const char* key, int* kind, mes_error* err) {
  try {
    clear(err);
    need(kind != nullptr, "kind is NULL");
    if (str(key).empty()) {
      tree_of(t);
      *kind = MES_TREE_DICT;
      return 0;
    }
    const auto* v = mestra::internal::find_path(tree_of(t), str(key));
    *kind = v == nullptr ? MES_TREE_ABSENT : static_cast<int>(v->kind());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_scalar(const mes_tree* t, const char* key, int64_t* integer, double* real,
                    mes_error* err) {
  try {
    clear(err);
    const auto& v = value_at(t, key);
    using K = mestra::internal::Value::Kind;
    need(v.kind() == K::Bool || v.kind() == K::Int || v.kind() == K::Float,
         "\"" + str(key) + "\" is not a number or a boolean");
    if (integer != nullptr) *integer = v.as_int();
    if (real != nullptr) *real = v.kind() == K::Float ? v.as_float() : static_cast<double>(v.as_int());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_strings(const mes_tree* t, const char* key, mes_strings** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    const auto& v = value_at(t, key);
    using K = mestra::internal::Value::Kind;
    need(v.kind() == K::Str || v.kind() == K::Strings, "\"" + str(key) + "\" is not text");
    *out = strings(v.kind() == K::Str ? std::vector<std::string>{v.as_text()} : v.items());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_array_info(const mes_tree* t, const char* key, int* dtype_out, int* rank,
                        int64_t* shape, mes_error* err) {
  try {
    clear(err);
    need(dtype_out != nullptr && rank != nullptr && shape != nullptr, "an output is NULL");
    const auto& v = value_at(t, key);
    need(v.kind() == mestra::internal::Value::Kind::Numbers, "\"" + str(key) + "\" is not an array");
    need(v.shape().size() <= 8, "more than 8 axes");
    *dtype_out = static_cast<int>(v.dtype());
    *rank = static_cast<int>(v.shape().size());
    for (std::size_t i = 0; i < v.shape().size(); ++i) shape[i] = v.shape()[i];
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_tree_array(const mes_tree* t, const char* key, void* out, int64_t out_bytes,
                   mes_error* err) {
  try {
    clear(err);
    const auto& v = value_at(t, key);
    need(v.kind() == mestra::internal::Value::Kind::Numbers, "\"" + str(key) + "\" is not an array");
    need(out_bytes == static_cast<int64_t>(v.bytes().size()), "the buffer holds " +
                                                                  std::to_string(out_bytes) +
                                                                  " bytes and the array " +
                                                                  std::to_string(v.bytes().size()));
    if (out_bytes > 0) std::memcpy(out, v.bytes().data(), v.bytes().size());
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_add_model(mes_file* f, const char* id, const char* type, const char* const* inputs,
                  int64_t n_inputs, const mes_tree* numbers, const char* repr, mes_error* err) {
  try {
    clear(err);
    writer_of(f).add_model(str(id), str(type), list(inputs, n_inputs), tree_of(numbers), str(repr));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_model_numbers(const mes_file* f, const char* id, mes_tree** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto t = std::make_unique<mes_tree>();
    t->root = reader_of(f).model_numbers(str(id));
    *out = t.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_nearest_check(const mes_tree* numbers, mes_error* err) {
  try {
    clear(err);
    mestra::internal::nearest_from(tree_of(numbers));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_nearest_output_size(const mes_tree* numbers, const char* output, int64_t* per_row,
                            mes_error* err) {
  try {
    clear(err);
    need(per_row != nullptr, "per_row is NULL");
    const auto m = mestra::internal::nearest_from(tree_of(numbers));
    *per_row = mestra::internal::nearest_output_size(m, str(output));
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_nearest_call(const mes_tree* numbers, const char* const* input_names,
                     const double* const* columns, int n_inputs, int64_t n_rows,
                     const char* output, double* out, int64_t out_count, mes_error* err) {
  try {
    clear(err);
    need(n_inputs >= 0 && n_rows >= 0, "a negative count");
    need(n_inputs == 0 || (input_names != nullptr && columns != nullptr), "inputs are NULL");
    const auto m = mestra::internal::nearest_from(tree_of(numbers));
    std::map<std::string, const double*> table;
    for (int j = 0; j < n_inputs; ++j) table[str(input_names[j])] = columns[j];
    const auto idx = mestra::internal::nearest_indices(m, table, n_rows);
    const auto values = mestra::internal::nearest_values(m, str(output), idx);
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

int mes_evaluate_begin(const mes_file* model, const char* out_path, mes_file** out,
                       mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    auto f = std::make_unique<mes_file>();
    f->writer = mestra::internal::begin_evaluation(reader_of(model), str(out_path));
    *out = f.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int mes_validate(const char* path, mes_report** out, mes_error* err) {
  try {
    clear(err);
    need(out != nullptr, "out is NULL");
    need(path != nullptr, "path is NULL");
    auto r = std::make_unique<mes_report>();
    r->report = mestra::internal::validate_file(path);
    *out = r.release();
    return 0;
  } catch (...) {
    return fail(err);
  }
}

int64_t mes_report_count(const mes_report* r) {
  return r == nullptr ? 0 : static_cast<int64_t>(r->report.findings.size());
}

int mes_report_get(const mes_report* r, int64_t i, const char** rule, const char** severity,
                   const char** path, const char** message) {
  if (r == nullptr || i < 0 || i >= static_cast<int64_t>(r->report.findings.size())) return 1;
  const auto& f = r->report.findings[static_cast<std::size_t>(i)];
  if (rule != nullptr) *rule = f.rule.c_str();
  if (severity != nullptr) *severity = f.severity.c_str();
  if (path != nullptr) *path = f.path.c_str();
  if (message != nullptr) *message = f.message.c_str();
  return 0;
}

void mes_report_free(mes_report* r) { delete r; }

int64_t mes_strings_count(const mes_strings* s) {
  return s == nullptr ? 0 : static_cast<int64_t>(s->items.size());
}

const char* mes_strings_get(const mes_strings* s, int64_t i) {
  if (s == nullptr || i < 0 || i >= static_cast<int64_t>(s->items.size())) return nullptr;
  return s->items[static_cast<std::size_t>(i)].c_str();
}

void mes_strings_free(mes_strings* s) { delete s; }

}  // extern "C"
