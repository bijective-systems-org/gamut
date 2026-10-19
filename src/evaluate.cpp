#include "evaluate.hpp"

namespace gamut_core {
namespace internal {

std::unique_ptr<Writer> begin_evaluation(const Reader& model, const std::string& out_path) {
  const Schema& s = model.schema();
  if (s.kind != "model") throw Error("E16", "only a model file is evaluated");
  auto w = Writer::create(out_path, "gamut evaluate", s.mesh.kind,
                          s.mesh.kind.empty() ? "fixed" : s.mesh.per);
  for (const auto& kv : {std::make_pair("title", s.title), std::make_pair("license", s.license),
                         std::make_pair("references", s.references),
                         std::make_pair("source", s.source)}) {
    if (!kv.second.empty()) w->set_attribute(kv.first, kv.second);
  }
  if (!s.file_id.empty()) w->set_attribute("evaluated_from", s.file_id);
  for (const auto& l : s.labels) {
    const auto it = s.tables.find(l.category);
    w->declare_label(l.name, l.role, it == s.tables.end() ? std::vector<std::string>() : it->second);
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
  return w;
}

}  // namespace internal
}  // namespace gamut_core
