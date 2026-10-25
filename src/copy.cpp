#include "copy.hpp"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <map>
#include <memory>
#include <set>

#include "reader.hpp"
#include "validate.hpp"
#include "writer.hpp"

namespace gamut_core {
namespace internal {

namespace {

void need(bool ok, const std::string& rule, const std::string& message,
          const std::string& path = "") {
  if (!ok) throw Error(rule, message, path);
}

// A copy reads every row of its source; a source that breaks a rule could
// be refused halfway, so it is refused before the first row.
void need_valid(const std::string& path) {
  const Report r = validate_file(path);
  for (const auto& f : r.findings) {
    if (f.severity != "error") continue;
    throw Error(f.rule, path + " is not a valid file (" + (f.path.empty() ? "" : f.path + ": ") +
                            f.message + "); it is not copied",
                f.path);
  }
}

void need_distinct(const std::string& src, const std::string& dst) {
  std::error_code e;
  const bool same = std::filesystem::exists(dst, e) && std::filesystem::equivalent(src, dst, e);
  need(!same, "", "the source and the destination are one file");
}

Column read_column(const Reader& r, const std::string& path, const Selection& rows, DType t) {
  const std::vector<std::int64_t> shape = r.shape(path, rows, Selection::all());
  Column c;
  c.dtype = t;
  c.count = 1;
  for (const auto x : shape) c.count *= x;
  c.bytes.resize(checked_count(path, dtype_size(t), {c.count}) * dtype_size(t));
  if (c.count > 0) r.read(path, rows, Selection::all(), t, c.bytes.data(), c.bytes.size());
  return c;
}

std::vector<std::int64_t> as_i64(const Column& c) {
  std::vector<std::int64_t> v(static_cast<std::size_t>(c.count));
  if (!v.empty()) std::memcpy(v.data(), c.bytes.data(), v.size() * 8);
  return v;
}

// Mesh-label codes of a source file as the destination's codes, by name
// (spec section 4.3: a mesh label's codes name entries of its table).
// Labels without a table, and copies into a new file, map codes to
// themselves.
using CodeMaps = std::map<std::string, std::vector<std::int64_t>>;

std::vector<std::int64_t> mapped(const std::string& label, std::vector<std::int64_t> codes,
                                 const CodeMaps& maps) {
  const auto it = maps.find(label);
  if (it == maps.end()) return codes;
  for (auto& c : codes) {
    need(c >= 0 && static_cast<std::size_t>(c) < it->second.size(), "E9",
         label + ": a code is outside its table", label);
    c = it->second[static_cast<std::size_t>(c)];
  }
  return codes;
}

// The geometry row `row` uses: its coordinates, and for a changing mesh its
// cells and mesh labels (as the destination's codes).
Geometry geometry_of(const Reader& r, std::int64_t row, const CodeMaps& maps) {
  const Mesh& m = r.schema().mesh;
  const Selection one = Selection::list({row});
  Geometry g;
  g.points = read_column(r, "coordinates", one, m.coordinate_dtype);
  g.axes = m.axes;
  g.n_nodes = g.axes > 0 ? g.points.count / g.axes : 0;
  if (m.kind == "changing") {
    if (m.has_cells == 1) {
      const Column t = read_column(r, "cells/types", one, DType::UInt8);
      g.types.assign(t.bytes.begin(), t.bytes.end());
      g.offsets = as_i64(read_column(r, "cells/offsets", one, DType::Int64));
      g.connectivity = as_i64(read_column(r, "cells/connectivity", one, DType::Int64));
    }
    for (const auto& ml : m.labels) {
      g.labels[ml.name] =
          mapped(ml.name, as_i64(read_column(r, mesh_label_path(ml), one, DType::Int64)), maps);
    }
  }
  return g;
}

bool same_geometry(const Geometry& a, const Geometry& b) {
  return a.points.dtype == b.points.dtype && a.points.bytes == b.points.bytes &&
         a.types == b.types && a.offsets == b.offsets && a.connectivity == b.connectivity &&
         a.labels == b.labels;
}

// The bytes one row of `s` takes in a batch: every column, and for a shared
// mesh its fields and changing coordinates.
std::size_t shared_row_bytes(const Schema& s) {
  const Mesh& m = s.mesh;
  std::size_t n = 8;                                        // the row id
  for (const auto& p : s.parameters) n += dtype_size(p.dtype);
  n += 32 * s.labels.size();                                // a name each
  for (const auto& r : s.results) {
    if (r.where == "scalar") {
      n += dtype_size(r.dtype);
    } else if (m.kind == "shared") {
      n += dtype_size(r.dtype) * static_cast<std::size_t>(r.where == "node" ? m.n_nodes : m.n_cells);
    }
  }
  if (m.kind == "shared" && m.per != "fixed") {
    n += dtype_size(m.coordinate_dtype) * static_cast<std::size_t>(m.n_nodes * m.axes);
  }
  return n;
}

// A changing-mesh row's bytes: its instance's nodes and cells times what
// each holds.
std::size_t changing_row_bytes(const Reader& r, std::int64_t row, std::size_t base) {
  const Schema& s = r.schema();
  const Mesh& m = s.mesh;
  const Selection one = Selection::list({row});
  const Selection all = Selection::all();
  const std::size_t nodes = static_cast<std::size_t>(r.shape("coordinates", one, all)[0]);
  std::size_t cells = 0, conn = 0;
  if (m.has_cells == 1) {
    cells = static_cast<std::size_t>(r.shape("cells/types", one, all)[0]);
    conn = static_cast<std::size_t>(r.shape("cells/connectivity", one, all)[0]);
  }
  std::size_t per_node = dtype_size(m.coordinate_dtype) * static_cast<std::size_t>(m.axes);
  std::size_t per_cell = 1 + 8;
  for (const auto& res : s.results) {
    if (res.where == "node") per_node += dtype_size(res.dtype);
    if (res.where == "cell") per_cell += dtype_size(res.dtype);
  }
  for (const auto& ml : m.labels) (ml.where == "node" ? per_node : per_cell) += 8;
  return base + nodes * per_node + cells * per_cell + conn * 8;
}

// Rows of `src`, in batches of about 32 MiB of values, through the
// writer; with `check_only`, every batch is checked and nothing is written.
// Peak memory is a few batches (the values, the writer's converted copy,
// HDF5's working set), whatever the file's size.
void copy_rows(const Reader& src, Writer& w, const std::vector<std::int64_t>& rows,
               bool keep_ids, const CodeMaps& maps, bool check_only) {
  const Schema& s = src.schema();
  const Mesh& m = s.mesh;
  const std::string group = m.per_group();
  const std::size_t budget = std::size_t(32) << 20;
  const std::size_t base = shared_row_bytes(s);
  std::size_t a = 0;
  while (a < rows.size()) {
    // Rows up to the budget, at least one.
    std::size_t b = a, bytes = 0;
    while (b < rows.size() && (b == a || bytes < budget)) {
      bytes += m.kind == "changing" ? changing_row_bytes(src, rows[b], base) : base;
      ++b;
    }
    const std::vector<std::int64_t> pos(rows.begin() + static_cast<std::ptrdiff_t>(a),
                                        rows.begin() + static_cast<std::ptrdiff_t>(b));
    a = b;
    const Selection sel = Selection::list(pos);
    Batch batch;
    batch.runs = static_cast<std::int64_t>(pos.size());
    if (keep_ids) batch.ids = as_i64(read_column(src, "row", sel, DType::Int64));
    for (const auto& p : s.parameters) batch.values[p.name] = read_column(src, p.name, sel, p.dtype);
    for (const auto& l : s.labels) batch.names[l.name] = src.label_names(l.name, sel);
    for (const auto& r : s.results) {
      if (r.served()) continue;
      if (r.where == "scalar" || m.kind == "shared") {
        batch.values[r.name] = read_column(src, result_path(r), sel, r.dtype);
        continue;
      }
      // A changing mesh: each row's values end to end.
      Column all;
      all.dtype = r.dtype;
      for (const std::int64_t row : pos) {
        const Column one = read_column(src, result_path(r), Selection::list({row}), r.dtype);
        all.bytes.insert(all.bytes.end(), one.bytes.begin(), one.bytes.end());
        all.count += one.count;
      }
      batch.values[r.name] = std::move(all);
    }
    if (!group.empty()) {
      const std::vector<std::string>& members = batch.names.at(group);
      for (std::size_t i = 0; i < pos.size(); ++i) {
        const std::string& name = members[i];
        if (w.has_member(name) || batch.member_geometry.count(name)) continue;
        batch.member_geometry[name] = geometry_of(src, pos[i], maps);
      }
    } else if (m.per == "run") {
      for (const std::int64_t row : pos) batch.run_geometry.push_back(geometry_of(src, row, maps));
    }
    w.add_runs(batch, check_only);
  }
}

// Every declaration of `src` on a new file, with its tables whole (so codes
// keep their meaning), its notes and private records, its mesh and models.
std::unique_ptr<Writer> declare_like(const Reader& src, const std::string& dst) {
  const Schema& s = src.schema();
  const Mesh& m = s.mesh;
  const bool model = s.kind == "model";
  const std::string per = m.kind.empty() ? "fixed" : m.per;
  std::unique_ptr<Writer> w = model ? Writer::create_model(dst, s.writer, m.kind, per)
                                    : Writer::create(dst, s.writer, m.kind, per);
  try {
    for (const auto& kv : {std::make_pair("title", s.title), std::make_pair("license", s.license),
                           std::make_pair("references", s.references),
                           std::make_pair("source", s.source),
                           std::make_pair("portion_marking", s.portion_marking),
                           std::make_pair(model ? "trained_on" : "evaluated_from",
                                          model ? s.trained_on : s.evaluated_from)}) {
      if (!kv.second.empty()) w->set_attribute(kv.first, kv.second);
    }
    auto table = [&](const std::string& name) {
      const auto it = s.tables.find(name);
      return it == s.tables.end() ? std::vector<std::string>() : it->second;
    };
    for (const auto& l : s.labels) w->declare_label(l.name, l.role, table(l.category));
    for (const auto& p : s.parameters) w->declare_parameter(p);
    if (!m.kind.empty()) {
      w->declare_coordinates(m.coordinate_units, m.coordinate_dtype, m.axes, m.coordinate_model,
                             m.coordinate_output);
      for (const auto& ml : m.labels) w->declare_mesh_label(ml, table(ml.category));
    }
    for (const auto& r : s.results) w->declare_result(r);
    for (const auto& c : s.constants) w->set_constant(c);
    if (!s.generalisation_group.empty()) w->set_generalisation_group(s.generalisation_group);
    for (const auto& kv : src.notes()) w->set_note(kv.first, kv.second);
    for (const auto& name : src.private_names()) w->set_private(name, src.private_record(name));
    if (m.kind == "shared") {
      const Selection all = Selection::all();
      Geometry g;
      g.n_nodes = m.n_nodes;
      g.axes = m.axes;
      if (m.per == "fixed") g.points = read_column(src, "coordinates", all, m.coordinate_dtype);
      if (m.n_cells > 0) {
        const Column t = read_column(src, "cells/types", all, DType::UInt8);
        g.types.assign(t.bytes.begin(), t.bytes.end());
        g.offsets = as_i64(read_column(src, "cells/offsets", all, DType::Int64));
        g.connectivity = as_i64(read_column(src, "cells/connectivity", all, DType::Int64));
      }
      for (const auto& ml : m.labels) {
        g.labels[ml.name] = as_i64(read_column(src, mesh_label_path(ml), all, DType::Int64));
      }
      w->set_mesh(g);
    }
    for (const auto& md : s.models) {
      w->add_model(md.id, md.type, md.inputs, src.model_numbers(md.id), md.repr);
    }
  } catch (...) {
    w->abandon(true);
    throw;
  }
  return w;
}

// Positions 0..n-1 that `sel` picks out of n rows, increasing.
std::vector<std::int64_t> positions(const Selection& sel, std::int64_t n) {
  const std::int64_t count = sel.count(n, "rows");
  std::vector<std::int64_t> out;
  out.reserve(checked_count("rows", 8, {count}));
  for (const auto& run : sel.runs(n, "rows")) {
    for (std::int64_t i = 0; i < run.second; ++i) out.push_back(run.first + i);
  }
  return out;
}

// What append needs to hold between two files.
// Returns how the source's mesh-label codes become the destination's.
CodeMaps check_same(const Reader& dst, const Reader& src) {
  CodeMaps maps;
  const Schema& d = dst.schema();
  const Schema& s = src.schema();
  auto differ = [](const std::string& what, const std::string& path) {
    throw Error("", "the files differ in " + what + "; append joins files with the same "
                    "declarations",
                path);
  };
  std::set<std::string> dn, sn;
  for (const auto& p : d.parameters) dn.insert(p.name);
  for (const auto& l : d.labels) dn.insert(l.name);
  for (const auto& r : d.results) dn.insert(result_path(r));
  for (const auto& c : d.constants) dn.insert(c.name);
  for (const auto& p : s.parameters) sn.insert(p.name);
  for (const auto& l : s.labels) sn.insert(l.name);
  for (const auto& r : s.results) sn.insert(result_path(r));
  for (const auto& c : s.constants) sn.insert(c.name);
  for (const auto& n : sn) {
    if (!dn.count(n)) differ("what they declare (" + n + " is only in the source)", n);
  }
  for (const auto& n : dn) {
    if (!sn.count(n)) differ("what they declare (" + n + " is only in the destination)", n);
  }
  for (const auto& p : s.parameters) {
    const Parameter* q = d.parameter(p.name);
    if (q->role != p.role || q->units != p.units || q->dtype != p.dtype ||
        q->run_group != p.run_group) {
      differ("the parameter " + p.name + " (role, units, dtype or run group)", p.name);
    }
  }
  for (const auto& l : s.labels) {
    if (d.label(l.name)->role != l.role) differ("the role of the label " + l.name, l.name);
  }
  for (const auto& r : s.results) {
    const Result* q = d.result(result_path(r));
    const Relation& a = q->relation;
    const Relation& b = r.relation;
    if (q->where != r.where || q->units != r.units || q->dtype != r.dtype ||
        q->vector != r.vector || q->axis != r.axis || a.of != b.of ||
        a.statistic != b.statistic || a.q != b.q || a.method != b.method ||
        a.with_respect_to != b.with_respect_to || a.axis != b.axis) {
      differ(result_path(r) + " (location, units, dtype, relation or vector)", result_path(r));
    }
  }
  for (const auto& c : s.constants) {
    const Constant* q = d.constant(c.name);
    // Compared bit for bit, so a NaN constant equals itself.
    if (q->units != c.units || q->dtype != c.dtype ||
        std::memcmp(&q->f, &c.f, sizeof c.f) != 0 || q->i != c.i) {
      differ("the constant " + c.name, c.name);
    }
  }
  if (d.generalisation_group != s.generalisation_group) differ("their generalisation group", "");
  const Mesh& dm = d.mesh;
  const Mesh& sm = s.mesh;
  if (dm.kind != sm.kind || dm.per != sm.per) differ("their mesh (kind or per)", "mesh");
  if (sm.kind.empty()) return maps;
  if (dm.coordinate_units != sm.coordinate_units || dm.coordinate_dtype != sm.coordinate_dtype ||
      dm.axes != sm.axes) {
    differ("their coordinates (units, dtype or axes)", "coordinates");
  }
  std::set<std::string> dl, sl;
  for (const auto& ml : dm.labels) dl.insert(mesh_label_path(ml) + (ml.category.empty() ? "" : "+"));
  for (const auto& ml : sm.labels) sl.insert(mesh_label_path(ml) + (ml.category.empty() ? "" : "+"));
  if (dl != sl) differ("their mesh labels (names, locations or tables)", "mesh");
  // A mesh label's codes name entries of its table (spec section 4.3), so
  // codes are mapped by name; a mesh label's table does not grow, so a name
  // the destination lacks is refused.
  for (const auto& ml : sm.labels) {
    if (ml.category.empty()) continue;
    const MeshLabel* dml = d.mesh_label(mesh_label_path(ml));
    const std::vector<std::string> theirs = dst.table(dml->category);
    std::vector<std::int64_t> to;
    for (const auto& name : src.table(ml.category)) {
      const auto at = std::find(theirs.begin(), theirs.end(), name);
      if (at == theirs.end()) {
        differ("the table of the mesh label " + ml.name + " (\"" + name + "\" is only in the "
               "source)", mesh_label_path(ml));
      }
      to.push_back(static_cast<std::int64_t>(at - theirs.begin()));
    }
    maps[ml.name] = to;
  }
  const Selection all = Selection::all();
  if (sm.kind == "shared") {
    if (dm.support_id != sm.support_id) differ("their mesh (support_id)", "mesh");
    for (const auto& ml : sm.labels) {
      const std::string p = mesh_label_path(ml);
      if (as_i64(read_column(dst, p, all, DType::Int64)) !=
          mapped(ml.name, as_i64(read_column(src, p, all, DType::Int64)), maps)) {
        differ("the mesh label " + p, p);
      }
    }
    // Fixed geometry is the mesh's: rows on other coordinates belong
    // elsewhere.
    if (sm.per == "fixed" &&
        read_column(dst, "coordinates", all, sm.coordinate_dtype).bytes !=
            read_column(src, "coordinates", all, sm.coordinate_dtype).bytes) {
      differ("their coordinates", "coordinates");
    }
  } else if (dm.has_cells != sm.has_cells && s.rows > 0) {
    // Fixed by the destination's first instance, or at its close from the
    // cell fields and labels it declared.
    differ(std::string("whether their instances have cells (the destination's ") +
               (dm.has_cells == 1 ? "have" : "have none") + ")",
           "mesh");
  }
  // A member in both files has one geometry.
  const std::string group = sm.per_group();
  if (group.empty() || d.rows == 0) return maps;
  // Each member's first row, by name, read as codes and the table.
  auto first_rows = [&](const Reader& r) {
    const std::vector<std::string> entries = r.table(r.schema().label(group)->category);
    const std::vector<std::int64_t> codes = as_i64(read_column(r, group, all, DType::Int64));
    std::map<std::string, std::int64_t> first;
    for (std::size_t i = 0; i < codes.size(); ++i) {
      first.emplace(entries.at(static_cast<std::size_t>(codes[i])), static_cast<std::int64_t>(i));
    }
    return first;
  };
  const std::map<std::string, std::int64_t> in_dst = first_rows(dst);
  for (const auto& kv : first_rows(src)) {
    const auto it = in_dst.find(kv.first);
    if (it == in_dst.end()) continue;
    if (!same_geometry(geometry_of(dst, it->second, {}), geometry_of(src, kv.second, maps))) {
      throw Error("", "the " + group + " \"" + kv.first + "\" has other geometry in the source; "
                      "one member has one geometry",
                  group);
    }
  }
  return maps;
}

}  // namespace

std::int64_t append_file(const std::string& dst, const std::string& src) {
  need_distinct(src, dst);
  need_valid(src);
  std::int64_t n = 0;
  CodeMaps maps;
  {
    const auto d = Reader::open(dst);
    const auto s = Reader::open(src);
    need(d->schema().kind == "data" && s->schema().kind == "data", "E16",
         "a model file has no rows; append joins data files");
    maps = check_same(*d, *s);
    n = s->schema().rows;
  }
  const auto s = Reader::open(src);
  const std::vector<std::int64_t> rows = positions(Selection::all(), n);
  auto w = Writer::open_append(dst);
  // Every batch is checked before the first is written, so nothing the
  // writer refuses can leave part of the source behind. (An I/O failure
  // partway still keeps the rows written before it.)
  copy_rows(*s, *w, rows, false, maps, true);
  copy_rows(*s, *w, rows, false, maps, false);
  w->close();
  return n;
}

void extract_file(const std::string& src, const std::string& dst, const Selection& rows) {
  need_distinct(src, dst);
  need_valid(src);
  const auto s = Reader::open(src);
  need(s->schema().kind == "data", "E16", "a model file has no rows to extract");
  const std::vector<std::int64_t> pos = positions(rows, s->schema().rows);
  auto w = declare_like(*s, dst);
  try {
    copy_rows(*s, *w, pos, true, {}, false);
    w->close();
  } catch (...) {
    w->abandon(true);
    throw;
  }
}

void write_copy_file(const std::string& src, const std::string& dst) {
  need_distinct(src, dst);
  need_valid(src);
  const auto s = Reader::open(src);
  auto w = declare_like(*s, dst);
  try {
    w->keep_identity(s->schema().file_id, s->schema().created);
    if (s->schema().kind == "data") {
      copy_rows(*s, *w, positions(Selection::all(), s->schema().rows), true, {}, false);
    }
    w->close();
  } catch (...) {
    w->abandon(true);
    throw;
  }
}

}  // namespace internal
}  // namespace gamut_core
