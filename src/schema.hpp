// The in-memory description of a file: what spec section 10 lays out,
// without any values.  Built from declarations by the writer and from
// metadata alone by the reader, so both see one model of the file.
#ifndef GAMUT_CORE_SCHEMA_HPP
#define GAMUT_CORE_SCHEMA_HPP

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "types.hpp"

namespace gamut_core {
namespace internal {

// The relation attributes of spec section 6.
struct Relation {
  std::string of;
  std::string statistic;          // "std" | "quantile" | an unknown word
  std::optional<double> q;
  std::string method;
  std::string with_respect_to;    // a parameter name or "coordinates"
  std::string axis;               // with_respect_to = coordinates
  bool empty() const {
    return of.empty() && statistic.empty() && !q && method.empty() &&
           with_respect_to.empty() && axis.empty();
  }
};

struct Parameter {
  std::string name;
  std::string role;               // design | condition | time | unknown
  std::string units;
  DType dtype = DType::Float64;   // int64 only when declared so
  std::optional<double> lower, upper;
  std::string run_group;
};

struct Label {
  std::string name;
  std::string role;               // group | categorical | status | split
  std::string category;           // the table's name
  DType dtype = DType::Int32;
};

// A scalar (where = "scalar") or a field (where = "node" | "cell").
struct Result {
  std::string name;
  std::string where;
  std::string units;
  DType dtype = DType::Float64;
  bool auto_dtype = false;        // taken from the first values written
  bool given_precision = false;   // resolved from the first values this writer took
  Relation relation;
  std::string vector;             // fields only
  std::string axis;               // fields only, with vector
  std::string model, output;      // served, in a model file
  int round_bits = -1;            // _QuantizeBitRoundNumberOfSignificantBits
  bool served() const { return !model.empty(); }
};

struct Constant {
  std::string name;
  std::string units;
  DType dtype = DType::Float64;
  double f = 0.0;
  std::int64_t i = 0;
};

// An integer per node or cell describing the mesh (spec section 4.3).
struct MeshLabel {
  std::string name;
  std::string where;              // node | cell
  std::string category;           // optional table
  DType dtype = DType::Int32;
};

struct Mesh {
  std::string kind;               // "" (none), "shared", "changing"
  std::string per = "fixed";      // fixed | run | group:<label>
  std::int64_t n_nodes = 0;       // shared: the mesh; changing: all instances
  std::int64_t n_cells = 0;
  std::int64_t n_conn = 0;        // connectivity length
  std::int64_t n_instances = 0;   // per != fixed: geometries on disk
  int axes = 0;                   // 1 to 3; 0 until set
  std::string coordinate_units;
  DType coordinate_dtype = DType::Float64;
  bool coordinate_dtype_auto = false;
  bool coordinate_given = false;  // precision taken from the first points this writer took
  std::string support_id;         // shared
  std::string coordinate_model, coordinate_output;   // served coordinates
  std::vector<MeshLabel> labels;
  bool set_done = false;          // the writer has set the mesh
  int has_cells = -1;             // changing mesh: -1 not yet known, 0 no, 1 yes
  std::string per_group() const {
    return per.compare(0, 6, "group:") == 0 ? per.substr(6) : std::string();
  }
};

struct Model {
  std::string id;
  std::string type;
  std::vector<std::string> inputs;
  std::string repr;
};

struct Schema {
  std::string kind = "data";      // data | model
  std::string writer, created, file_id;
  std::string title, license, references, source, portion_marking;
  std::string generalisation_group, trained_on, evaluated_from;
  std::int64_t rows = 0;
  std::vector<Parameter> parameters;
  std::vector<Label> labels;
  std::vector<Result> results;    // scalars and fields
  std::vector<Constant> constants;
  std::map<std::string, std::vector<std::string>> tables;   // name -> entries
  Mesh mesh;
  std::vector<Model> models;

  const Parameter* parameter(const std::string& name) const;
  const Label* label(const std::string& name) const;
  // A result by concept path: "cl", "node_fields/p", "cell_fields/p".
  const Result* result(const std::string& path) const;
  const Constant* constant(const std::string& name) const;
  const MeshLabel* mesh_label(const std::string& path) const;
  // Names are unique in a file (spec section 4.4).
  bool name_taken(const std::string& name) const;
  // "table" | "shared" | "changing"
  std::string type() const;
  std::vector<std::string> addons() const;
};

// The concept path of a result or mesh label.
std::string result_path(const Result& r);
std::string mesh_label_path(const MeshLabel& m);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_SCHEMA_HPP
