// The C interface: every mes_* function, each catching every exception at
// the boundary and turning it into a mes_error.
#include "mestra/mestra.h"

#include <cstring>
#include <exception>
#include <memory>
#include <string>
#include <vector>

#include "names.hpp"
#include "reader.hpp"
#include "types.hpp"
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
  for (int64_t i = 0; i < n; ++i) out.push_back(str(items[i]));
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

}  // namespace

extern "C" {

const char* mes_version(void) { return kVersion; }
const char* mes_format(void) { return kFormat; }

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
                       const char* axis, const char* vector, int round_bits, mes_error* err) {
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
                            mes_error* err) {
  try {
    clear(err);
    writer_of(f).declare_coordinates(str(units),
                                     as_given(dtype_code) ? DType::String : dtype(dtype_code),
                                     axes);
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
