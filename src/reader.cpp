#include "reader.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <set>

#include "codec.hpp"
#include "names.hpp"

namespace gamut_core {
namespace internal {

namespace {

void need(bool ok, const std::string& rule, const std::string& message,
          const std::string& path = {}) {
  if (!ok) throw Error(rule, message, path);
}

const std::set<std::string> kParameterRoles = {"design", "condition", "time"};
const std::set<std::string> kLabelRoles = {"group", "categorical", "status",
                                           "split"};

struct Attrs {
  std::vector<RawAttr> list;
  const RawAttr* find(const std::string& name) const {
    for (const auto& a : list) {
      if (a.name == name) return &a;
    }
    return nullptr;
  }
  std::string text(const std::string& name) const {
    const RawAttr* a = find(name);
    return a != nullptr && a->value.kind() == AttrValue::Kind::Str
               ? a->value.as_text()
               : std::string();
  }
  std::optional<double> real(const std::string& name) const {
    const RawAttr* a = find(name);
    if (a == nullptr) return std::nullopt;
    if (a->value.kind() == AttrValue::Kind::Float) return a->value.as_float();
    if (a->value.kind() == AttrValue::Kind::Int) {
      return static_cast<double>(a->value.as_int());
    }
    return std::nullopt;
  }
  std::optional<std::int64_t> integer(const std::string& name) const {
    const RawAttr* a = find(name);
    if (a == nullptr || a->value.kind() != AttrValue::Kind::Int) {
      return std::nullopt;
    }
    return a->value.as_int();
  }
};

Relation relation_of(const Attrs& a) {
  Relation r;
  r.of = a.text("of");
  r.statistic = a.text("statistic");
  r.q = a.real("q");
  r.method = a.text("method");
  r.with_respect_to = a.text("with_respect_to");
  if (!r.with_respect_to.empty()) r.axis = a.text("axis");
  return r;
}

// A result from its object's attributes and, for a dataset, its type.
Result result_from(const Attrs& a, const DsetInfo& info, const std::string& name,
                   const std::string& where) {
  Result r;
  r.name = name;
  r.where = where;
  r.units = a.text("units");
  r.relation = relation_of(a);
  r.vector = a.text("vector");
  if (!r.vector.empty() || r.relation.with_respect_to.empty()) {
    r.axis = r.vector.empty() ? std::string() : a.text("axis");
  }
  r.model = a.text("model");
  r.output = a.text("output");
  const auto bits = a.integer("_QuantizeBitRoundNumberOfSignificantBits");
  if (bits) r.round_bits = static_cast<int>(*bits);
  DType t;
  if (info.is_dataset && dtype_of(info.type, &t)) r.dtype = t;
  return r;
}


}  // namespace

Schema load_schema(const File& f, const std::string& path) {
  Schema s;
  const Attrs root{f.attributes("/")};
  const std::string format = root.text("format");
  need(format == "gamut/1", "E1",
       format.empty() ? "\"" + path + "\" has no format attribute; it is not a "
                                      "file of this format"
                      : "\"" + path + "\" is " + format +
                            ", and this library reads gamut/1");
  s.kind = root.text("kind");
  s.writer = root.text("writer");
  s.created = root.text("created");
  s.file_id = root.text("file_id");
  s.title = root.text("title");
  s.license = root.text("license");
  s.references = root.text("references");
  s.source = root.text("source");
  s.portion_marking = root.text("portion_marking");
  s.generalisation_group = root.text("generalisation_group");
  s.trained_on = root.text("trained_on");
  s.evaluated_from = root.text("evaluated_from");
  const DsetInfo row = f.dataset_shape("/row");
  s.rows = row.is_dataset && row.shape.size() == 1
               ? static_cast<std::int64_t>(row.shape[0])
               : 0;
  // Links are never followed (spec section 9.6); one where the structure
  // lives is refused rather than read as absent.
  auto hard = [](const Member& m, const std::string& group) {
    const std::string p = (group == "/" ? "" : group) + "/" + m.name;
    need(m.kind == LinkKind::Hard, "E22",
         p + " is a soft or external link; links are never followed", p);
  };
  for (const std::string& g : {std::string("/"), std::string("/categories"),
                               std::string("/mesh"), std::string("/models")}) {
    for (const Member& m : f.members(g)) hard(m, g);
  }
  // Tables are read at open, so their size is capped as structure: one budget
  // for all of them, as for one table, so many tables cannot add up (E26).
  std::size_t entries_left = kMaxTableEntries, bytes_left = kMaxTableBytes;
  for (const Member& m : f.members("/categories")) {
    if (!m.is_dataset) continue;
    const std::string p = "/categories/" + m.name;
    s.tables[m.name] = f.read_strings(p, entries_left, bytes_left);
    entries_left -= s.tables[m.name].size();
    bytes_left -= s.tables[m.name].size() * f.dataset_info(p, false).type.size;
    for (const std::string& entry : s.tables[m.name]) {
      need(entry.find('\0') == std::string::npos && valid_utf8(entry), "E4",
           p + ": a category name is not valid UTF-8 or holds a NUL", p);
    }
  }
  for (const Member& m : f.members("/")) {
    if (m.kind != LinkKind::Hard) continue;
    const std::string h5 = "/" + m.name;
    if (m.name == "row") continue;
    // One open of each object gives its attributes and, for a dataset, its
    // type and shape.
    auto [raw, info] = f.inspect(h5);
    const Attrs a{std::move(raw)};
    const std::string role = a.text("role");
    if (role.empty()) continue;
    if (m.is_group) {
      if (role == "scalar") s.results.push_back(result_from(a, info, m.name, "scalar"));
      continue;
    }
    DType t = DType::Float64;
    const bool typed = dtype_of(info.type, &t);
    // An unknown role is ignored (spec section 17); the validator reports it.
    if (kParameterRoles.count(role) == 1) {
      Parameter p;
      p.name = m.name;
      p.role = role;
      p.units = a.text("units");
      if (typed) p.dtype = t;
      p.lower = a.real("lower");
      p.upper = a.real("upper");
      p.run_group = a.text("run_group");
      s.parameters.push_back(p);
    } else if (kLabelRoles.count(role) == 1) {
      Label l;
      l.name = m.name;
      l.role = role;
      l.category = a.text("category");
      if (typed) l.dtype = t;
      s.labels.push_back(l);
    } else if (role == "scalar") {
      s.results.push_back(result_from(a, info, m.name, "scalar"));
    } else if (role == "constant") {
      Constant c;
      c.name = m.name;
      c.units = a.text("units");
      if (typed) c.dtype = t;
      if (info.shape.empty()) {
        if (c.dtype == DType::Int64) {
          f.read(h5, DType::Int64, {}, &c.i, 8);
        } else if (typed && t != DType::String) {
          f.read(h5, DType::Float64, {}, &c.f, 8);
        }
      }
      s.constants.push_back(c);
    }
  }
  auto by_name = [](auto& v) {
    std::sort(v.begin(), v.end(), [](const auto& a, const auto& b) {
      return bytes_less(a.name, b.name);
    });
  };
  by_name(s.parameters);
  by_name(s.labels);
  by_name(s.constants);
  if (f.is_group("/mesh")) {
    const Attrs ma{f.attributes("/mesh")};
    Mesh& mesh = s.mesh;
    mesh.kind = ma.text("kind");
    mesh.per = ma.text("per");
    mesh.support_id = ma.text("support_id");
    auto length = [&](const std::string& p) -> std::int64_t {
      const DsetInfo i = f.dataset_shape(p);
      return i.is_dataset && i.shape.size() == 1 ? static_cast<std::int64_t>(i.shape[0]) : 0;
    };
    auto [coord_attrs, coords] = f.inspect("/mesh/coordinates");
    const Attrs ca{std::move(coord_attrs)};
    if (coords.is_dataset) {
      DType t;
      if (dtype_of(coords.type, &t)) mesh.coordinate_dtype = t;
      if (!coords.shape.empty()) mesh.axes = static_cast<int>(coords.shape.back());
    } else if (const auto ax = ca.integer("axes")) {
      mesh.axes = static_cast<int>(*ax);
    }
    // Coordinates a model computes (section 10.3) name it on the
    // zero-length dataset that stands for them.
    mesh.coordinate_model = ca.text("model");
    mesh.coordinate_output = ca.text("output");
    mesh.coordinate_units = ca.text("units");
    if (mesh.kind == "shared") {
      mesh.n_nodes = length("/mesh/node");
      mesh.n_cells = length("/mesh/cell");
      if (mesh.per == "run") {
        mesh.n_instances = s.rows;
      } else if (!mesh.per_group().empty()) {
        mesh.n_instances = length("/mesh/instance");
      }
    } else {
      mesh.n_instances = std::max<std::int64_t>(0, length("/mesh/instance_nodes") - 1);
      const DsetInfo types = f.dataset_shape("/mesh/cell_types");
      mesh.n_nodes = coords.is_dataset && !coords.shape.empty()
                         ? static_cast<std::int64_t>(coords.shape[0])
                         : 0;
      mesh.n_cells = types.is_dataset && !types.shape.empty()
                         ? static_cast<std::int64_t>(types.shape[0])
                         : 0;
      mesh.has_cells = types.is_dataset ? 1 : 0;
    }
    const DsetInfo conn = f.dataset_shape("/mesh/cell_connectivity");
    mesh.n_conn = conn.is_dataset && !conn.shape.empty()
                      ? static_cast<std::int64_t>(conn.shape[0])
                      : 0;
    for (const char* where : {"node", "cell"}) {
      const std::string lg = std::string("/mesh/") + where + "_labels";
      for (const Member& m : f.members(lg)) {
        hard(m, lg);
        if (!m.is_dataset) continue;
        MeshLabel ml;
        ml.name = m.name;
        ml.where = where;
        auto [raw, info] = f.inspect(lg + "/" + m.name);
        ml.category = Attrs{std::move(raw)}.text("category");
        DType t;
        if (dtype_of(info.type, &t)) ml.dtype = t;
        mesh.labels.push_back(ml);
      }
      const std::string fg = std::string("/mesh/") + where + "_fields";
      for (const Member& m : f.members(fg)) {
        hard(m, fg);
        if (!m.is_dataset && !m.is_group) continue;
        auto [raw, info] = f.inspect(fg + "/" + m.name);
        s.results.push_back(result_from(Attrs{std::move(raw)}, info, m.name, where));
      }
    }
  }
  std::stable_sort(s.results.begin(), s.results.end(),
                   [](const Result& a, const Result& b) {
                     return bytes_less(result_path(a), result_path(b));
                   });
  for (const Member& m : f.members("/models")) {
    if (m.kind != LinkKind::Hard || !m.is_group) continue;
    const Attrs a{f.attributes("/models/" + m.name)};
    Model model;
    model.id = m.name;
    model.type = a.text("type");
    model.inputs = split_spaces(a.text("inputs"));
    model.repr = a.text("repr");
    s.models.push_back(model);
  }
  return s;
}

std::unique_ptr<Reader> Reader::open(const std::string& path) {
  std::unique_ptr<Reader> r(new Reader());
  r->file_.reset(new File(File::open_read(path)));
  r->schema_ = load_schema(*r->file_, path);
  need(r->schema_.kind == "data" || r->schema_.kind == "model", "E1",
       "kind must be data or model");
  return r;
}

std::vector<std::string> Reader::names(const std::string& group) const {
  std::vector<std::string> out;
  const Schema& s = schema_;
  if (group == "parameters") {
    for (const auto& p : s.parameters) out.push_back(p.name);
  } else if (group == "labels") {
    for (const auto& l : s.labels) out.push_back(l.name);
  } else if (group == "scalars") {
    for (const auto& r : s.results) {
      if (r.where == "scalar") out.push_back(r.name);
    }
  } else if (group == "constants") {
    for (const auto& c : s.constants) out.push_back(c.name);
  } else if (group == "node_fields" || group == "cell_fields") {
    const std::string where = group == "node_fields" ? "node" : "cell";
    for (const auto& r : s.results) {
      if (r.where == where) out.push_back(r.name);
    }
  } else if (group == "node_labels" || group == "cell_labels") {
    const std::string where = group == "node_labels" ? "node" : "cell";
    for (const auto& m : s.mesh.labels) {
      if (m.where == where) out.push_back(m.name);
    }
  } else if (group == "tables") {
    for (const auto& kv : s.tables) out.push_back(kv.first);
  } else if (group == "models") {
    for (const auto& m : s.models) out.push_back(m.id);
  } else {
    throw Error("", "no group \"" + group + "\"; the groups are parameters, labels, scalars, "
                    "constants, node_fields, cell_fields, node_labels, cell_labels, tables "
                    "and models");
  }
  std::sort(out.begin(), out.end(), bytes_less);
  return out;
}

std::vector<std::pair<std::string, std::string>> Reader::describe(
    const std::string& path) const {
  const Schema& s = schema_;
  std::vector<std::pair<std::string, std::string>> out;
  auto add = [&](const std::string& k, const std::string& v) {
    if (!v.empty()) out.emplace_back(k, v);
  };
  auto real = [](const std::optional<double>& v) {
    return v ? format_f64(*v) : std::string();
  };
  if (const Parameter* p = s.parameter(path)) {
    add("kind", "parameter");
    add("role", p->role);
    add("units", p->units);
    add("dtype", dtype_name(p->dtype));
    add("lower", real(p->lower));
    add("upper", real(p->upper));
    add("run_group", p->run_group);
  } else if (const Label* l = s.label(path)) {
    add("kind", "label");
    add("role", l->role);
    add("category", l->category);
    add("dtype", dtype_name(l->dtype));
  } else if (const Constant* c = s.constant(path)) {
    add("kind", "constant");
    add("units", c->units);
    add("dtype", dtype_name(c->dtype));
    add("value", c->dtype == DType::Int64 ? format_i64(c->i) : format_f64(c->f));
  } else if (const Result* r = s.result(path)) {
    add("kind", r->where == "scalar" ? "scalar" : "field");
    add("location", r->where == "scalar" ? "run" : r->where);
    add("units", r->units);
    add("dtype", r->served() ? "" : dtype_name(r->dtype));
    add("of", r->relation.of);
    add("statistic", r->relation.statistic);
    add("q", real(r->relation.q));
    add("method", r->relation.method);
    add("with_respect_to", r->relation.with_respect_to);
    add("axis", !r->relation.axis.empty() ? r->relation.axis : r->axis);
    add("vector", r->vector);
    add("model", r->model);
    add("output", r->output);
    if (r->round_bits >= 0) add("round_bits", format_i64(r->round_bits));
  } else if (const MeshLabel* m = s.mesh_label(path)) {
    add("kind", "mesh_label");
    add("location", m->where);
    add("category", m->category);
    add("per", s.mesh.per);
  } else if (path.compare(0, 7, "models/") == 0) {
    const Model* found = nullptr;
    for (const auto& model : s.models) {
      if ("models/" + model.id == path) found = &model;
    }
    need(found != nullptr, "", "nothing is called \"" + path + "\"", path);
    std::string inputs;
    for (const auto& in : found->inputs) inputs += (inputs.empty() ? "" : " ") + in;
    add("kind", "model");
    add("type", found->type);
    add("inputs", inputs);
    add("repr", found->repr);
  } else if (path == "coordinates" && !s.mesh.kind.empty()) {
    add("kind", "coordinates");
    add("units", s.mesh.coordinate_units);
    add("dtype", dtype_name(s.mesh.coordinate_dtype));
    add("axes", format_i64(s.mesh.axes));
    add("per", s.mesh.per);
    add("model", s.mesh.coordinate_model);
    add("output", s.mesh.coordinate_output);
  } else if (path == "coordinates") {
    throw Error("", path + ": the file has no mesh", path);
  } else {
    throw Error("", "nothing is called \"" + path + "\"", path);
  }
  return out;
}


std::pair<std::int64_t, std::int64_t> Reader::span(const std::string& cumulative, std::int64_t k,
                                                   const std::string& path) const {
  const DsetInfo info = file_->dataset_info(cumulative, false);
  const std::int64_t len =
      info.is_dataset && info.shape.size() == 1 ? static_cast<std::int64_t>(info.shape[0]) : 0;
  need(k >= 0 && k < len - 1, "E21",
       path + ": instance " + std::to_string(k) + " does not exist", path);
  std::int64_t v[2] = {0, 0};
  file_->read(cumulative, DType::Int64, {Selection::range(k, k + 2)}, v, sizeof v);
  need(v[0] >= 0 && v[1] >= v[0], "E21",
       cumulative + " decreases at instance " + std::to_string(k), path);
  return {v[0], v[1]};
}

std::vector<std::int64_t> Reader::row_instances(const Selection& runs) const {
  const std::int64_t n = runs.count(schema_.rows, "rows");
  std::vector<std::int64_t> out(checked_count("/mesh/row_instance", 8, {n}));
  if (n > 0) file_->read("/mesh/row_instance", DType::Int64, {runs}, out.data(), out.size() * 8);
  return out;
}

std::int64_t Reader::instance_of_run(std::int64_t run) const {
  if (schema_.mesh.per == "run") return run;
  std::int64_t inst = 0;
  file_->read("/mesh/row_instance", DType::Int64, {Selection::range(run, run + 1)}, &inst, 8);
  return inst;
}

namespace {

// The one run a changing-mesh read takes.
std::int64_t single_run(const Selection& runs, std::int64_t rows,
                        const std::string& path) {
  const std::int64_t n = runs.count(rows, path);
  need(n == 1 && runs.kind != Selection::All, "",
       path + ": a changing mesh is read one run at a time; select exactly one "
              "run (a selection across runs needs a shared mesh)",
       path);
  if (runs.kind == Selection::Range) return runs.start;
  if (runs.kind == Selection::Index) return runs.index[0];
  return 0;
}

// `sites` relative to an instance, shifted to the end-to-end dataset.
Selection shifted(const Selection& sites, std::int64_t length,
                  std::int64_t offset, const std::string& path) {
  sites.count(length, path);
  // offset comes from the file; with this, no sum below can overflow.
  need(offset >= 0 && offset <= std::numeric_limits<std::int64_t>::max() - length, "E21",
       path + ": the run's start in the file is out of range", path);
  switch (sites.kind) {
    case Selection::All: return Selection::range(offset, offset + length);
    case Selection::Range:
      return Selection::range(offset + sites.start, offset + sites.stop);
    case Selection::Index: {
      std::vector<std::int64_t> idx = sites.index;
      for (auto& i : idx) i += offset;
      return Selection::list(idx);
    }
  }
  return Selection::all();
}

}  // namespace

std::vector<std::int64_t> Reader::shape(const std::string& path,
                                        const Selection& runs,
                                        const Selection& sites) const {
  const std::vector<std::int64_t> out = unchecked_shape(path, runs, sites);
  // Checked here, before any caller sizes a buffer for the read, at 8 bytes
  // a value, the widest a read returns (docs/security.md).
  const std::size_t limit = kMaxDatasetBytes / 8;
  std::size_t n = 1;
  for (const std::int64_t d : out) {
    need(d >= 0, "E21", path + ": a negative count", path);
    const std::size_t x = static_cast<std::size_t>(d);
    need(x == 0 || n <= limit / x, "E26",
         path + ": a read of more than " + std::to_string(limit) +
             " values (8 GiB) is refused; read a part at a time",
         path);
    n *= x;
  }
  return out;
}

std::vector<std::int64_t> Reader::unchecked_shape(const std::string& path,
                                                  const Selection& runs,
                                                  const Selection& sites) const {
  const Schema& s = schema_;
  const Mesh& m = s.mesh;
  if (path == "row" || s.parameter(path) || s.label(path) ||
      (s.result(path) && s.result(path)->where == "scalar")) {
    need(sites.kind == Selection::All, "", path + ": a run-table column has no "
                                                  "sites to select",
         path);
    const Result* r = s.result(path);
    need(!(r && r->served()), "", path + " is computed by a model; evaluate "
                                         "the model file to get values",
         path);
    return {runs.count(s.rows, path)};
  }
  if (s.constant(path)) return {};
  const Result* r = s.result(path);
  const MeshLabel* ml = s.mesh_label(path);
  if (r != nullptr || ml != nullptr || path == "coordinates") {
    need(!m.kind.empty(), "", path + ": the file has no mesh", path);
    need(!(r && r->served()), "", path + " is computed by a model; evaluate "
                                         "the model file to get values",
         path);
    const std::string where = r ? r->where : (ml ? ml->where : "node");
    if (m.kind == "shared") {
      const std::int64_t len = where == "node" ? m.n_nodes : m.n_cells;
      const std::int64_t ns = sites.count(len, path);
      const bool fixed_geometry = ml != nullptr || (path == "coordinates" && m.per == "fixed");
      std::vector<std::int64_t> out;
      if (!(fixed_geometry && runs.kind == Selection::All)) {
        out.push_back(runs.count(s.rows, path));
      }
      out.push_back(ns);
      if (path == "coordinates") out.push_back(m.axes);
      return out;
    }
    const std::int64_t run = single_run(runs, s.rows, path);
    const std::int64_t k = instance_of_run(run);
    const auto sp = span(where == "node" ? "/mesh/instance_nodes" : "/mesh/instance_cells", k,
                         path);
    std::vector<std::int64_t> out = {sites.count(sp.second - sp.first, path)};
    if (path == "coordinates") out.push_back(m.axes);
    return out;
  }
  if (path == "cells/types" || path == "cells/offsets" ||
      path == "cells/connectivity") {
    need(!m.kind.empty() && m.n_cells >= 0, "", path + ": the file has no mesh");
    need(sites.kind == Selection::All, "", path + ": cells are read whole", path);
    if (m.kind == "shared") {
      if (path == "cells/types") return {m.n_cells};
      if (path == "cells/offsets") return {m.n_cells == 0 ? 0 : m.n_cells + 1};
      return {m.n_conn};
    }
    const std::int64_t run = single_run(runs, s.rows, path);
    const std::int64_t k = instance_of_run(run);
    if (m.has_cells == 0) return {0};
    const auto c = span("/mesh/instance_cells", k, path);
    if (path == "cells/types") return {c.second - c.first};
    need(c.second - c.first < std::numeric_limits<std::int64_t>::max(), "E21",
         path + ": the instance has too many cells", path);
    if (path == "cells/offsets") return {c.second - c.first + 1};
    std::int64_t lo = 0, hi = 0;
    file_->read("/mesh/cell_offsets", DType::Int64, {Selection::range(c.first, c.first + 1)}, &lo, 8);
    file_->read("/mesh/cell_offsets", DType::Int64, {Selection::range(c.second, c.second + 1)}, &hi, 8);
    need(lo >= 0 && hi >= lo, "E21", path + ": /mesh/cell_offsets decreases", path);
    return {hi - lo};
  }
  throw Error("", "nothing is called \"" + path + "\"", path);
}

void Reader::read(const std::string& path, const Selection& runs,
                  const Selection& sites, DType mem, void* out,
                  std::size_t out_bytes) const {
  const Schema& s = schema_;
  const Mesh& m = s.mesh;
  const std::vector<std::int64_t> shp = shape(path, runs, sites);
  std::int64_t count = 1;
  for (const auto x : shp) count *= x;
  // The buffer is a capacity: the read fills what it needs from the start.
  const std::size_t needed = static_cast<std::size_t>(count) * dtype_size(mem);
  need(out_bytes >= needed, "",
       path + ": the buffer holds " + std::to_string(out_bytes) + " bytes and the read needs " +
           std::to_string(needed),
       path);
  out_bytes = needed;
  if (count == 0) return;
  const File& f = *file_;
  if (path == "row") {
    f.read("/row", mem, {runs}, out, out_bytes);
    return;
  }
  if (s.parameter(path) || s.label(path) ||
      (s.result(path) && s.result(path)->where == "scalar") || s.constant(path)) {
    if (s.constant(path)) {
      f.read("/" + path, mem, {}, out, out_bytes);
    } else {
      f.read("/" + path, mem, {runs}, out, out_bytes);
    }
    return;
  }
  const Result* r = s.result(path);
  const MeshLabel* ml = s.mesh_label(path);
  if (path.compare(0, 6, "cells/") == 0) {
    const std::string which = path.substr(6);
    if (m.kind == "shared") {
      f.read("/mesh/cell_" + which, mem, {}, out, out_bytes);
      return;
    }
    const std::int64_t run = single_run(runs, s.rows, path);
    const std::int64_t k = instance_of_run(run);
    const auto c = span("/mesh/instance_cells", k, path);
    const std::int64_t c0 = c.first, c1 = c.second;
    if (which == "types") {
      f.read("/mesh/cell_types", mem, {Selection::range(c0, c1)}, out, out_bytes);
      return;
    }
    const DsetInfo oi = f.dataset_info("/mesh/cell_offsets", false);
    need(oi.shape.size() == 1 && static_cast<hsize_t>(c1) < oi.shape[0], "E21",
         path + ": instance_cells runs past cell_offsets", path);
    std::vector<std::int64_t> offs(checked_count(path, 8, {c1 - c0 + 1}));
    f.read("/mesh/cell_offsets", DType::Int64, {Selection::range(c0, c1 + 1)},
           offs.data(), offs.size() * 8);
    need(offs.front() >= 0, "E21", path + ": /mesh/cell_offsets is negative", path);
    for (std::size_t i = 1; i < offs.size(); ++i) {
      need(offs[i] >= offs[i - 1], "E21", path + ": /mesh/cell_offsets decreases", path);
    }
    if (which == "offsets") {
      const std::int64_t base = offs[0];
      for (auto& o : offs) o -= base;
      need(mem == DType::Int64, "", path + " is read as int64", path);
      std::memcpy(out, offs.data(), out_bytes);
      return;
    }
    f.read("/mesh/cell_connectivity", mem,
           {Selection::range(offs.front(), offs.back())}, out, out_bytes);
    return;
  }
  const std::string where = r ? r->where : (ml ? ml->where : "node");
  const std::string h5 =
      path == "coordinates" ? "/mesh/coordinates"
      : r ? (where == "node" ? "/mesh/node_fields/" : "/mesh/cell_fields/") + r->name
          : (where == "node" ? "/mesh/node_labels/" : "/mesh/cell_labels/") + ml->name;
  if (m.kind == "changing") {
    const std::int64_t run = single_run(runs, s.rows, path);
    if (r != nullptr) {
      const std::string start = where == "node" ? "/mesh/row_node_start"
                                                : "/mesh/row_cell_start";
      std::int64_t first = 0;
      f.read(start, DType::Int64, {Selection::range(run, run + 1)}, &first, 8);
      const std::int64_t k = instance_of_run(run);
      const auto sp = span(where == "node" ? "/mesh/instance_nodes" : "/mesh/instance_cells", k,
                           path);
      f.read(h5, mem, {shifted(sites, sp.second - sp.first, first, path)}, out, out_bytes);
      return;
    }
    const std::int64_t k = instance_of_run(run);
    const auto sp = span(where == "node" ? "/mesh/instance_nodes" : "/mesh/instance_cells", k,
                         path);
    f.read(h5, mem, {shifted(sites, sp.second - sp.first, sp.first, path)}, out, out_bytes);
    return;
  }
  // Shared mesh.
  if (r != nullptr) {
    f.read(h5, mem, {runs, sites}, out, out_bytes, threads_);
    return;
  }
  // Mesh labels are fixed; coordinates follow `per`.
  if (ml != nullptr || m.per == "fixed") {
    if (runs.kind == Selection::All) {
      f.read(h5, mem, {sites}, out, out_bytes);
      return;
    }
    // One copy of the fixed geometry per selected run.
    const std::int64_t nruns = runs.count(s.rows, path);
    const std::size_t one = out_bytes / static_cast<std::size_t>(nruns);
    f.read(h5, mem, {sites}, out, one);
    for (std::int64_t i = 1; i < nruns; ++i) {
      std::memcpy(static_cast<char*>(out) + static_cast<std::size_t>(i) * one, out, one);
    }
    return;
  }
  if (m.per == "run") {
    f.read(h5, mem, {runs, sites}, out, out_bytes);
    return;
  }
  // Per group: read each geometry the selected runs use once, then place.
  const std::vector<std::int64_t> codes = row_instances(runs);
  std::vector<std::int64_t> uniq = codes;
  std::sort(uniq.begin(), uniq.end());
  uniq.erase(std::unique(uniq.begin(), uniq.end()), uniq.end());
  const std::size_t one = out_bytes / codes.size();
  std::vector<unsigned char> block(one * uniq.size());
  f.read(h5, mem, {Selection::list(uniq), sites}, block.data(), block.size());
  for (std::size_t i = 0; i < codes.size(); ++i) {
    const std::size_t at = static_cast<std::size_t>(
        std::lower_bound(uniq.begin(), uniq.end(), codes[i]) - uniq.begin());
    std::memcpy(static_cast<char*>(out) + i * one, block.data() + at * one, one);
  }
}

std::vector<std::pair<std::string, AttrValue>> Reader::notes() const {
  std::vector<std::pair<std::string, AttrValue>> out;
  if (!file_->is_group("/notes")) return out;
  for (const RawAttr& a : file_->attributes("/notes")) {
    if (a.too_large) continue;
    out.emplace_back(a.name, a.value);
  }
  return out;
}

std::vector<std::string> Reader::private_names() const {
  std::vector<std::string> out;
  for (const Member& m : file_->members("/private")) {
    if (m.kind == LinkKind::Hard && m.is_dataset) out.push_back(m.name);
  }
  return out;
}

std::vector<unsigned char> Reader::private_record(const std::string& name) const {
  const std::string path = "/private/" + name;
  const DsetInfo info = file_->dataset_info(path, false);
  need(info.is_dataset && info.shape.size() == 1, "", "no private record \"" + name + "\"");
  DType t;
  need(dtype_of(info.type, &t) && t == DType::UInt8, "",
       "the private record \"" + name + "\" is not bytes written by this library");
  std::vector<unsigned char> out(checked_count(path, 1, {static_cast<std::int64_t>(info.shape[0])}));
  if (!out.empty()) file_->read(path, DType::UInt8, {}, out.data(), out.size());
  return out;
}

Dict Reader::model_numbers(const std::string& id) const {
  bool found = false;
  for (const auto& m : schema_.models) found = found || m.id == id;
  need(found, "", "no model called \"" + id + "\"");
  return read_dict_group(*file_, "/models/" + id, true);
}

std::vector<std::string> Reader::table(const std::string& name) const {
  const auto it = schema_.tables.find(name);
  need(it != schema_.tables.end(), "", "no table \"" + name + "\"");
  return it->second;
}

std::vector<std::string> Reader::label_names(const std::string& name,
                                             const Selection& runs) const {
  const Label* l = schema_.label(name);
  need(l != nullptr, "", "no label \"" + name + "\"", name);
  // The file's fault, as the validator reports it: no category (E2), or one naming no table (E9).
  need(!l->category.empty(), "E2", name + ": the label has no category", name);
  need(schema_.tables.count(l->category) == 1, "E9",
       name + ": its category names no table (\"" + l->category + "\")", name);
  const std::vector<std::string>& entries = table(l->category);
  const std::int64_t n = runs.count(schema_.rows, name);
  need(n <= kMaxNamesRead, "E26",
       name + ": names for " + std::to_string(n) + " rows are more than the " +
           std::to_string(kMaxNamesRead) + " read at once; read the codes, or fewer rows",
       name);
  std::vector<std::int64_t> codes(checked_count(name, 8, {n}));
  if (n > 0) file_->read("/" + name, DType::Int64, {runs}, codes.data(), codes.size() * 8);
  std::vector<std::string> out;
  out.reserve(codes.size());
  for (const std::int64_t c : codes) {
    need(c >= 0 && c < static_cast<std::int64_t>(entries.size()), "E9",
         name + ": code " + std::to_string(c) + " is outside its table", name);
    out.push_back(entries[static_cast<std::size_t>(c)]);
  }
  return out;
}

namespace {

// a + b exactly, as s + e (Knuth's two-sum).
void two_sum(double a, double b, double* s, double* e) {
  *s = a + b;
  const double v = *s - a;
  *e = (a - (*s - v)) + (b - v);
}

// -1, 0 or 1 as the int64 v is below, at or above the finite b, exactly.
int compare(std::int64_t v, double b) {
  if (b >= 9223372036854775808.0) return -1;
  if (b < -9223372036854775808.0) return 1;
  const double whole = std::trunc(b);
  const auto i = static_cast<std::int64_t>(whole);   // exact: |whole| <= 2^63, -2^63 included
  if (v != i) return v < i ? -1 : 1;
  const double fraction = b - whole;                  // exact
  return fraction > 0 ? -1 : fraction < 0 ? 1 : 0;
}

// v - b for an int64 v and a finite b, rounded once to the nearest double
// (a double holds every int64 only to 2^53). v is split into its bits above
// the lowest ten and those ten, each exact as a double, and the sum is
// carried as exact pairs: v - b = r + w + u exactly at the end.
double minus(std::int64_t v, double b) {
  const std::int64_t low = v & 1023;
  double s1, e1, s2, e2, s, e, t, u, r, w;
  two_sum(static_cast<double>(v - low), -b, &s1, &e1);
  two_sum(e1, static_cast<double>(low), &s2, &e2);
  two_sum(s1, s2, &s, &e);
  two_sum(e, e2, &t, &u);
  two_sum(s, t, &r, &w);
  // r is nearest to r + w; when that was a tie, u says which way it goes.
  if (w != 0 && u != 0 && (w > 0) == (u > 0)) {
    const double next = std::nextafter(r, w > 0 ? HUGE_VAL : -HUGE_VAL);
    if (std::fabs(w) == std::fabs(next - r) / 2) r = next;
  }
  return r;
}

}  // namespace

void Reader::outside(const std::string& name, const Selection& runs, double* out,
                     std::size_t out_bytes) const {
  const Parameter* p = schema_.parameter(name);
  need(p != nullptr, "", "no parameter \"" + name + "\"", name);
  need(p->lower || p->upper, "",
       name + " declares no bounds; outside needs a parameter with lower and upper", name);
  // The validator reports these (E16); measuring against them would mislead.
  need(p->lower && p->upper && std::isfinite(*p->lower) && std::isfinite(*p->upper) &&
           *p->lower <= *p->upper,
       "E16", name + ": its bounds are not two finite numbers with lower <= upper", name);
  const std::int64_t n = shape(name, runs, Selection::all()).at(0);
  if (p->dtype == DType::Int64) {
    // Integers are measured as integers: as doubles they lose bits past 2^53.
    const std::size_t want = static_cast<std::size_t>(n) * sizeof(double);
    need(out_bytes >= want, "",
         name + ": the buffer holds " + std::to_string(out_bytes) +
             " bytes and the selection needs " + std::to_string(want), name);
    std::vector<std::int64_t> values(static_cast<std::size_t>(n));
    read(name, runs, Selection::all(), DType::Int64, values.data(), values.size() * 8);
    // Inside or outside is decided exactly; then how far.
    for (std::size_t i = 0; i < values.size(); ++i) {
      const std::int64_t v = values[i];
      out[i] = compare(v, *p->lower) < 0   ? minus(v, *p->lower)
               : compare(v, *p->upper) > 0 ? minus(v, *p->upper)
                                           : 0.0;
    }
    return;
  }
  read(name, runs, Selection::all(), DType::Float64, out, out_bytes);
  for (std::int64_t i = 0; i < n; ++i) {
    double& v = out[i];
    if (v < *p->lower) {
      v -= *p->lower;
    } else if (v > *p->upper) {
      v -= *p->upper;
    } else if (!std::isnan(v)) {
      v = 0.0;
    }
  }
}

}  // namespace internal
}  // namespace gamut_core
