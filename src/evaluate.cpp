#include "evaluate.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "names.hpp"
#include "nearest.hpp"

namespace gamut_core {
namespace internal {

// A setup that fails part way removes the file it created.
std::unique_ptr<Writer> begin_evaluation(const Reader& model, const std::string& out_path) {
  const Schema& s = model.schema();
  if (s.kind != "model") throw Error("E16", "only a model file is evaluated");
  auto w = Writer::create(out_path, "gamut evaluate", s.mesh.kind,
                          s.mesh.kind.empty() ? "fixed" : s.mesh.per);
  try {
    for (const auto& kv : {std::make_pair("title", s.title), std::make_pair("license", s.license),
                           std::make_pair("references", s.references),
                           std::make_pair("source", s.source),
                           std::make_pair("portion_marking", s.portion_marking)}) {
      if (!kv.second.empty()) w->set_attribute(kv.first, kv.second);
    }
    if (!s.file_id.empty()) w->set_attribute("evaluated_from", s.file_id);
    for (const auto& l : s.labels) {
      const auto it = s.tables.find(l.category);
      w->declare_label(l.name, l.role,
                       it == s.tables.end() ? std::vector<std::string>() : it->second);
    }
    for (const auto& p : s.parameters) w->declare_parameter(p);
    if (!s.mesh.kind.empty()) {
      w->declare_coordinates(s.mesh.coordinate_units, s.mesh.coordinate_dtype, s.mesh.axes);
      for (const auto& ml : s.mesh.labels) {
        const auto it = s.tables.find(ml.category);
        w->declare_mesh_label(ml, it == s.tables.end() ? std::vector<std::string>() : it->second);
      }
    }
    for (const auto& r : s.results) {
      Result copy = r;
      copy.model.clear();
      copy.output.clear();
      w->declare_result(copy);
    }
    for (const auto& c : s.constants) w->set_constant(c);
    if (s.mesh.kind == "shared") {
      Geometry g;
      g.n_nodes = s.mesh.n_nodes;
      g.axes = s.mesh.axes;
      const auto all = Selection::all();
      if (s.mesh.per == "fixed") {
        std::vector<double> pts(checked_count("coordinates", 8, {s.mesh.n_nodes, s.mesh.axes}));
        model.read("coordinates", all, all, DType::Float64, pts.data(), pts.size() * 8);
        g.points = Column::of(DType::Float64, pts.data(), static_cast<std::int64_t>(pts.size()));
      }
      if (s.mesh.n_cells > 0) {
        std::vector<std::int64_t> types(checked_count("cells/types", 8, {s.mesh.n_cells}));
        model.read("cells/types", all, all, DType::Int64, types.data(), types.size() * 8);
        g.types.assign(types.begin(), types.end());
        g.offsets.resize(checked_count("cells/offsets", 8, {s.mesh.n_cells + 1}));
        model.read("cells/offsets", all, all, DType::Int64, g.offsets.data(), g.offsets.size() * 8);
        g.connectivity.resize(checked_count("cells/connectivity", 8, {s.mesh.n_conn}));
        model.read("cells/connectivity", all, all, DType::Int64, g.connectivity.data(),
                   g.connectivity.size() * 8);
      }
      for (const auto& ml : s.mesh.labels) {
        const std::size_t n = checked_count(mesh_label_path(ml), 8,
                                            {ml.where == "node" ? s.mesh.n_nodes : s.mesh.n_cells});
        std::vector<std::int64_t> v(n);
        model.read(mesh_label_path(ml), all, all, DType::Int64, v.data(), n * 8);
        g.labels[ml.name] = v;
      }
      w->set_mesh(g);
    }
  } catch (...) {
    w->abandon(true);
    throw;
  }
  return w;
}

namespace {

std::string number(double v) {
  char b[32];
  std::snprintf(b, sizeof b, "%g", v);
  return b;
}

// q as text that reads back as the same double.
std::string exact(double v) {
  char b[40];
  std::snprintf(b, sizeof b, "%.17g", v);
  return b;
}

std::vector<double> doubles(const Column& c, const std::string& what) {
  const std::vector<unsigned char> b = converted(c, DType::Float64, what);
  std::vector<double> out(static_cast<std::size_t>(c.count));
  if (!out.empty()) std::memcpy(out.data(), b.data(), b.size());
  return out;
}

}  // namespace

Evaluation::Evaluation(const Reader& model, std::int64_t rows, const std::string& out_path)
    : model_(model), rows_(rows) {
  if (model.schema().kind != "model") throw Error("E16", "only a model file is evaluated");
  if (rows < 0) throw Error("E5", "the number of rows is negative");
  writer_ = begin_evaluation(model, out_path);
}

Evaluation::~Evaluation() {
  if (writer_ == nullptr) return;
  try {
    writer_->abandon(true);
  } catch (...) {
    // Removing an unfinished file is best effort; nothing is left to report to.
  }
}

void Evaluation::values(const std::string& name, const Column& given) {
  const Schema& s = model_.schema();
  const Parameter* p = s.parameter(name);
  if (p == nullptr) {
    if (s.label(name) != nullptr) throw Error("E2", name + " is a label: give its names", name);
    throw Error("E2", name + " is not an input of this model", name);
  }
  if (given.count != rows_) {
    throw Error("E5", name + " has " + std::to_string(given.count) + " values for " +
                          std::to_string(rows_) + " rows; every input needs the same number",
                name);
  }
  Column c;
  c.dtype = p->dtype;
  c.count = rows_;
  c.bytes = converted(given, p->dtype, name);
  parameters_[name] = std::move(c);
  ready_ = false;
}

void Evaluation::names(const std::string& name, const std::vector<std::string>& given) {
  const Schema& s = model_.schema();
  const Label* l = s.label(name);
  if (l == nullptr) {
    if (s.parameter(name) != nullptr) throw Error("E2", name + " is a parameter: give its values", name);
    throw Error("E2", name + " is not an input of this model", name);
  }
  if (static_cast<std::int64_t>(given.size()) != rows_) {
    throw Error("E5", name + " has " + std::to_string(given.size()) + " names for " +
                          std::to_string(rows_) + " rows; every input needs the same number",
                name);
  }
  const auto table = s.tables.find(l->category);
  std::vector<std::int64_t> codes;
  for (const auto& g : given) {
    const auto& entries = table != s.tables.end() ? table->second : std::vector<std::string>();
    const auto at = std::find(entries.begin(), entries.end(), g);
    if (at == entries.end()) throw Error("E9", name + ": \"" + g + "\" is not in the model's table", name);
    codes.push_back(at - entries.begin());
  }
  label_names_[name] = given;
  label_codes_[name] = std::move(codes);
  ready_ = false;
}

void Evaluation::coordinates(const Column& given) {
  const Mesh& m = model_.schema().mesh;
  if (m.kind.empty()) throw Error("E2", "this model file has no mesh, so it takes no coordinates", "coordinates");
  const std::int64_t want = rows_ * m.n_nodes * m.axes;
  if (given.count != want) {
    throw Error("E5", "coordinates have " + std::to_string(given.count) + " values, not rows x nodes x axes (" +
                          std::to_string(rows_) + " x " + std::to_string(m.n_nodes) + " x " +
                          std::to_string(m.axes) + ")",
                "coordinates");
  }
  coordinates_ = doubles(given, "coordinates");
  coordinates_given_ = true;
  ready_ = false;
}

bool Evaluation::coordinates_available() const {
  return coordinates_given_ || !coordinates_.empty();
}

Evaluation::Asked& Evaluation::asked(const std::string& model_id, const Request& r) {
  for (auto& a : asked_) {
    if (a.model == model_id && a.request == r) return a;
  }
  throw Error("", "the model " + model_id + " was not asked for the " + r.kind + " of " + r.output);
}

const Evaluation::Asked* Evaluation::asked_for(const Result& r) const {
  for (const auto& a : asked_) {
    if (a.model != r.model || a.request.output != r.output) continue;
    const Relation& rel = r.relation;
    const bool match = rel.statistic == "std" ? a.request.kind == "std"
                       : rel.statistic == "quantile" && rel.q
                           ? a.request.kind == "quantile" && a.request.key == exact(*rel.q)
                       : !rel.with_respect_to.empty()
                           ? a.request.kind == "derivative" && a.request.key == rel.with_respect_to
                           : a.request.kind == "values";
    if (match) return &a;
  }
  return nullptr;
}

void Evaluation::ready() {
  const Schema& s = model_.schema();
  for (const auto& p : s.parameters) {
    if (parameters_.count(p.name) == 0) throw Error("E2", "the input " + p.name + " is missing", p.name);
  }
  for (const auto& l : s.labels) {
    if (label_codes_.count(l.name) == 0) throw Error("E2", "the input " + l.name + " is missing", l.name);
  }
  // Inputs outside the range a model was fitted on are evaluated, and reported.
  warnings_.clear();
  for (const auto& p : s.parameters) {
    if (!p.lower || !p.upper) continue;
    const std::vector<double> v = doubles(parameters_.at(p.name), p.name);
    const auto out = std::count_if(v.begin(), v.end(), [&](double x) { return x < *p.lower || x > *p.upper; });
    if (out > 0) {
      warnings_.push_back("W4: " + p.name + " is outside the model's domain [" + number(*p.lower) + ", " +
                          number(*p.upper) + "] in " + std::to_string(out) + " of " +
                          std::to_string(rows_) + " rows");
    }
  }
  // A shared mesh's stored coordinates, for every row, when none are given.
  if (!coordinates_given_ && s.mesh.kind == "shared" && s.mesh.per == "fixed") {
    const auto all = Selection::all();
    std::vector<double> pts(checked_count("coordinates", 8, {s.mesh.n_nodes, s.mesh.axes}));
    model_.read("coordinates", all, all, DType::Float64, pts.data(), pts.size() * 8);
    coordinates_.clear();
    for (std::int64_t i = 0; i < rows_; ++i) coordinates_.insert(coordinates_.end(), pts.begin(), pts.end());
  }
  // What each model is asked for: its results' values, spreads, quantiles
  // and derivatives, and computed coordinates.
  asked_.clear();
  requests_.clear();
  order_.clear();
  auto ask = [&](const std::string& model, const Request& r, std::int64_t per_row) {
    for (const auto& a : asked_) {
      if (a.model == model && a.request == r) return;
    }
    if (requests_.count(model) == 0) order_.push_back(model);
    requests_[model].push_back(r);
    Asked a;
    a.model = model;
    a.request = r;
    a.per_row = per_row;
    asked_.push_back(std::move(a));
  };
  for (const char* where : {"scalar", "node", "cell"}) {
    for (const auto& r : s.results) {
      if (r.where != where || r.model.empty()) continue;
      Request q;
      q.output = r.output;
      const Relation& rel = r.relation;
      if (rel.statistic == "std") {
        q.kind = "std";
      } else if (rel.statistic == "quantile" && rel.q) {
        q.kind = "quantile";
        q.key = exact(*rel.q);
      } else if (!rel.with_respect_to.empty()) {
        q.kind = "derivative";
        q.key = rel.with_respect_to;
      } else {
        q.kind = "values";
      }
      ask(r.model, q, r.where == "scalar" ? 1 : r.where == "node" ? s.mesh.n_nodes : s.mesh.n_cells);
    }
  }
  if (!s.mesh.coordinate_model.empty()) {
    ask(s.mesh.coordinate_model, Request{s.mesh.coordinate_output, "values", ""}, s.mesh.n_nodes * s.mesh.axes);
  }
  // Each model can read what it reads; the built-in ones run here.
  for (const auto& id : order_) {
    const Model* m = nullptr;
    for (const auto& candidate : s.models) {
      if (candidate.id == id) m = &candidate;
    }
    if (m == nullptr) throw Error("E17", "a result names the model " + id + ", which does not exist", id);
    for (const auto& in : m->inputs) {
      if (in == "coordinates" && !coordinates_available()) {
        throw Error("E2", "the model " + id + " reads coordinates, which were not given", id);
      }
    }
    if (m->type != "nearest") continue;
    const Nearest nm = nearest_from(model_.model_numbers(id));
    std::map<std::string, std::vector<double>> columns;
    std::map<std::string, const double*> pointers;
    for (const auto& c : nm.columns) {
      const auto it = parameters_.find(c);
      if (it == parameters_.end()) throw Error("E17", "the nearest model " + id + " reads " + c + ", which is not a parameter", id);
      columns[c] = doubles(it->second, c);
      pointers[c] = columns[c].data();
    }
    const std::vector<std::int64_t> index = nearest_indices(nm, pointers, rows_);
    for (auto& a : asked_) {
      if (a.model != id) continue;
      if (a.request.kind != "values") {
        throw Error("", "the nearest model " + id + " gives values only, not the " + a.request.kind + " of " +
                            a.request.output, id);
      }
      std::vector<double> v = nearest_values(nm, a.request.output, index);
      if (static_cast<std::int64_t>(v.size()) != rows_ * a.per_row) {
        throw Error("E17", "the nearest model " + id + " gives " + a.request.output + " with " +
                               std::to_string(nearest_output_size(nm, a.request.output)) +
                               " values per row, not " + std::to_string(a.per_row), id);
      }
      a.answer = std::move(v);
      a.answered = true;
    }
  }
  ready_ = true;
}

std::vector<std::string> Evaluation::models() const {
  std::vector<std::string> out;
  for (const auto& id : order_) {
    for (const auto& m : model_.schema().models) {
      if (m.id == id && m.type != "nearest") out.push_back(id);
    }
  }
  return out;
}

const std::vector<Request>& Evaluation::requests(const std::string& model_id) const {
  if (!ready_) throw Error("", "the evaluation is not ready: give the inputs and call ready");
  const auto it = requests_.find(model_id);
  if (it == requests_.end()) throw Error("", "the model " + model_id + " is asked for nothing", model_id);
  return it->second;
}

DType Evaluation::input_dtype(const std::string& name) const {
  if (const auto it = parameters_.find(name); it != parameters_.end()) return it->second.dtype;
  if (label_codes_.count(name)) return DType::Int64;
  if (name == "coordinates" && coordinates_available()) return DType::Float64;
  throw Error("E2", name + " is not an input given to this evaluation", name);
}

std::vector<std::int64_t> Evaluation::input_shape(const std::string& name) const {
  if (name == "coordinates" && coordinates_available()) {
    const Mesh& m = model_.schema().mesh;
    return {rows_, m.n_nodes, m.axes};
  }
  input_dtype(name);
  return {rows_};
}

const std::vector<unsigned char>& Evaluation::input(const std::string& name) const {
  if (const auto it = parameters_.find(name); it != parameters_.end()) return it->second.bytes;
  auto& bytes = inputs_[name];
  if (const auto it = label_codes_.find(name); it != label_codes_.end()) {
    bytes.resize(it->second.size() * 8);
    if (!bytes.empty()) std::memcpy(bytes.data(), it->second.data(), bytes.size());
    return bytes;
  }
  if (name == "coordinates" && coordinates_available()) {
    bytes.resize(coordinates_.size() * 8);
    if (!bytes.empty()) std::memcpy(bytes.data(), coordinates_.data(), bytes.size());
    return bytes;
  }
  throw Error("E2", name + " is not an input given to this evaluation", name);
}

void Evaluation::answer(const std::string& model_id, const Request& r, const double* values,
                        std::int64_t count) {
  if (!ready_) throw Error("", "the evaluation is not ready: give the inputs and call ready");
  Asked& a = asked(model_id, r);
  if (count != rows_ * a.per_row) {
    throw Error("E5", "the model " + model_id + " gave " + std::to_string(count) + " values for the " +
                          r.kind + " of " + r.output + ", not " + std::to_string(rows_ * a.per_row) +
                          " (rows x " + std::to_string(a.per_row) + ")",
                model_id);
  }
  a.answer.assign(values, values + count);
  a.answered = true;
}

void Evaluation::finish() {
  if (!ready_) throw Error("", "the evaluation is not ready: give the inputs and call ready");
  if (writer_ == nullptr) throw Error("", "the evaluation is finished");
  const Schema& s = model_.schema();
  for (const auto& a : asked_) {
    if (!a.answered) throw Error("", "the model " + a.model + " gave no " + a.request.kind + " for " + a.request.output, a.model);
  }
  Batch b;
  b.runs = rows_;
  for (const auto& p : s.parameters) b.values[p.name] = parameters_.at(p.name);
  for (const auto& l : s.labels) b.names[l.name] = label_names_.at(l.name);
  for (const auto& r : s.results) {
    const Asked* a = asked_for(r);
    if (a == nullptr) throw Error("E17", r.name + " is computed by no model the file holds", r.name);
    b.values[r.name] = Column::of(DType::Float64, a->answer.data(), static_cast<std::int64_t>(a->answer.size()));
  }
  if (s.mesh.kind == "shared" && s.mesh.per == "run") {
    const std::vector<double>* source = nullptr;
    if (!s.mesh.coordinate_model.empty()) {
      source = &asked(s.mesh.coordinate_model, Request{s.mesh.coordinate_output, "values", ""}).answer;
    } else if (coordinates_given_) {
      source = &coordinates_;
    } else {
      throw Error("E2", "this model file's geometry changes per run; give coordinates", "coordinates");
    }
    const std::int64_t each = s.mesh.n_nodes * s.mesh.axes;
    for (std::int64_t i = 0; i < rows_; ++i) {
      Geometry g;
      g.n_nodes = s.mesh.n_nodes;
      g.axes = s.mesh.axes;
      g.points = Column::of(DType::Float64, source->data() + i * each, each);
      b.run_geometry.push_back(std::move(g));
    }
  }
  std::unique_ptr<Writer> w = std::move(writer_);
  try {
    w->add_runs(b);
    w->close();
  } catch (...) {
    w->abandon(true);
    throw;
  }
}

}  // namespace internal
}  // namespace gamut_core
