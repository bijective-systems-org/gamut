#include "schema.hpp"

#include <algorithm>

namespace mestra {
namespace internal {

std::string result_path(const Result& r) {
  if (r.where == "node") return "node_fields/" + r.name;
  if (r.where == "cell") return "cell_fields/" + r.name;
  return r.name;
}

std::string mesh_label_path(const MeshLabel& m) {
  return (m.where == "node" ? "node_labels/" : "cell_labels/") + m.name;
}

const Parameter* Schema::parameter(const std::string& name) const {
  for (const auto& p : parameters) {
    if (p.name == name) return &p;
  }
  return nullptr;
}

const Label* Schema::label(const std::string& name) const {
  for (const auto& l : labels) {
    if (l.name == name) return &l;
  }
  return nullptr;
}

const Result* Schema::result(const std::string& path) const {
  for (const auto& r : results) {
    if (result_path(r) == path) return &r;
  }
  return nullptr;
}

const Constant* Schema::constant(const std::string& name) const {
  for (const auto& c : constants) {
    if (c.name == name) return &c;
  }
  return nullptr;
}

const MeshLabel* Schema::mesh_label(const std::string& path) const {
  for (const auto& m : mesh.labels) {
    if (mesh_label_path(m) == path) return &m;
  }
  return nullptr;
}

bool Schema::name_taken(const std::string& name) const {
  if (parameter(name) || label(name) || constant(name)) return true;
  for (const auto& r : results) {
    if (r.name == name) return true;
  }
  for (const auto& m : mesh.labels) {
    if (m.name == name) return true;
  }
  return false;
}

std::string Schema::type() const {
  if (mesh.kind == "shared") return "shared";
  if (mesh.kind == "changing") return "changing";
  return "table";
}

std::vector<std::string> Schema::addons() const {
  std::vector<std::string> out;
  bool time = false, gradients = false, uncertainty = false;
  for (const auto& p : parameters) time = time || p.role == "time";
  for (const auto& r : results) {
    gradients = gradients || !r.relation.with_respect_to.empty();
    uncertainty = uncertainty || r.relation.statistic == "std" ||
                  r.relation.statistic == "quantile";
  }
  if (time) out.push_back("time");
  if (gradients) out.push_back("gradients");
  if (uncertainty) out.push_back("uncertainty");
  return out;
}

}  // namespace internal
}  // namespace mestra
