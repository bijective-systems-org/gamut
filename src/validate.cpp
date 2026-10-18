#include "validate.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <type_traits>

#include "chunk.hpp"
#include "codec.hpp"
#include "h5.hpp"
#include "nearest.hpp"
#include "names.hpp"
#include "sha256.hpp"
#include "types.hpp"
#include "units.hpp"

namespace mestra {
namespace internal {

bool Report::ok() const { return errors() == 0; }

std::size_t Report::errors() const {
  std::size_t n = 0;
  for (const auto& f : findings) n += f.severity == "error";
  return n;
}

std::size_t Report::warnings() const {
  std::size_t n = 0;
  for (const auto& f : findings) n += f.severity == "warning";
  return n;
}

namespace {

const std::set<std::string> kMachinery = {
    "CLASS", "NAME", "DIMENSION_LIST", "REFERENCE_LIST", "DIMENSION_LABELS",
    "_Netcdf4Dimid", "_Netcdf4Coordinates", "_nc3_strict", "_NCProperties"};
const std::set<std::string> kParameterRoles = {"design", "condition", "time"};
const std::set<std::string> kLabelRoles = {"group", "categorical", "status", "split"};
const std::set<std::string> kReservedRoot = {"row", "coordinates", "categories", "mesh",
                                             "models", "notes", "private", "VTKHDF"};

enum class Kind { S, F, I, Bits };   // string, float64, int64, int32-or-int64

using AttrSpec = std::map<std::string, Kind>;

const AttrSpec kRootAttrs = {
    {"format", Kind::S}, {"kind", Kind::S}, {"writer", Kind::S}, {"created", Kind::S},
    {"file_id", Kind::S}, {"title", Kind::S}, {"license", Kind::S}, {"references", Kind::S},
    {"source", Kind::S}, {"generalisation_group", Kind::S}, {"trained_on", Kind::S},
    {"evaluated_from", Kind::S}};
const AttrSpec kParameterAttrs = {{"role", Kind::S}, {"units", Kind::S}, {"lower", Kind::F},
                                  {"upper", Kind::F}, {"run_group", Kind::S}};
const AttrSpec kLabelAttrs = {{"role", Kind::S}, {"category", Kind::S}};
const AttrSpec kResultAttrs = {
    {"role", Kind::S}, {"units", Kind::S}, {"of", Kind::S}, {"statistic", Kind::S},
    {"q", Kind::F}, {"method", Kind::S}, {"with_respect_to", Kind::S}, {"axis", Kind::S},
    {"vector", Kind::S}, {"model", Kind::S}, {"output", Kind::S}, {"coordinates", Kind::S},
    {"_QuantizeBitRoundNumberOfSignificantBits", Kind::Bits}};
const AttrSpec kConstantAttrs = {{"role", Kind::S}, {"units", Kind::S}};
const AttrSpec kMeshAttrs = {{"kind", Kind::S}, {"per", Kind::S}, {"support_id", Kind::S}};
const AttrSpec kCoordinateAttrs = {{"units", Kind::S}, {"model", Kind::S}, {"output", Kind::S}};
const AttrSpec kMeshLabelAttrs = {{"category", Kind::S}};
const AttrSpec kModelAttrs = {{"type", Kind::S}, {"inputs", Kind::S}, {"repr", Kind::S}};
const AttrSpec kNone = {};

// "1 row is", "3 rows are": a count with its noun (and verb) agreeing.
std::string counted(std::int64_t n, const char* one, const char* many) {
  return std::to_string(n) + " " + (n == 1 ? one : many);
}

std::string where_word(const std::string& prefix) {
  return prefix.compare(0, 4, "node") == 0 ? "node" : "cell";
}

int nodes_of_type(int code) {
  switch (code) {
    case 1: return 1;
    case 3: return 2;
    case 5: return 3;
    case 7: return -3;
    case 9: return 4;
    case 10: return 4;
    case 12: return 8;
    case 13: return 6;
    case 14: return 5;
    case 21: return 3;
    case 22: return 6;
    case 23: return 8;
    case 24: return 10;
    case 25: return 20;
    case 26: return 15;
    case 27: return 13;
    default: return 0;
  }
}

// One dataset or served object, as the validator sees it.
struct Object {
  std::string h5;          // HDF5 path
  std::string concept;     // concept path for findings
  std::string name;
  DsetInfo info;
  std::vector<RawAttr> attrs;
  std::string text(const std::string& key) const {
    for (const auto& a : attrs) {
      if (a.name == key && a.value.kind() == AttrValue::Kind::Str) return a.value.as_text();
    }
    return std::string();
  }
  bool has(const std::string& key) const {
    for (const auto& a : attrs) {
      if (a.name == key) return true;
    }
    return false;
  }
  std::optional<double> real(const std::string& key) const {
    for (const auto& a : attrs) {
      if (a.name != key) continue;
      if (a.value.kind() == AttrValue::Kind::Float) return a.value.as_float();
      if (a.value.kind() == AttrValue::Kind::Int) return static_cast<double>(a.value.as_int());
    }
    return std::nullopt;
  }
};

class Validator {
 public:
  explicit Validator(const std::string& path) : path_(path) {}
  Report run();

 private:
  void add(const std::string& rule, const std::string& path, const std::string& message) {
    report_.findings.push_back({rule, rule[0] == 'E' ? "error" : "warning", path, message});
  }
  void guarded(const std::string& path, const std::function<void()>& check) {
    try {
      check();
    } catch (const Error& e) {
      add(e.rule().empty() ? "E23" : e.rule(), path, e.what());
    } catch (const std::exception& e) {
      add("E23", path, std::string("cannot be read: ") + e.what());
    }
  }

  Object object(const std::string& h5, const std::string& concept, const std::string& name);
  void check_attrs(const Object& o, const AttrSpec& spec);
  void check_name(const std::string& name, const std::string& concept, bool root);
  bool check_dims(const Object& o, const std::vector<std::string>& dims,
                  const std::vector<std::string>& scale_paths);
  void check_storage(const Object& o, bool leading_class, const std::vector<bool>& growable);
  void check_units(const Object& o, bool required);
  std::vector<std::int64_t> ints(const Object& o);
  std::vector<double> floats(const Object& o);
  // Every element of `o` in blocks along its first axis, with its flat
  // index: memory stays bounded whatever the file declares. Skipped above
  // the checker's element cap, as ints() and floats().
  template <class T, class F>
  void each(const Object& o, F f);
  bool check_cells(const Object& t, const Object& o, const Object& c,
                   const std::vector<std::int64_t>& cn, const std::vector<std::int64_t>& cc,
                   Sha256* digest);

  void root_attrs();
  void walk_links();
  void tables();
  void row();
  void root_objects();
  void mesh();
  void models();
  void scales();
  void relations_and_vectors();
  void warnings();

  std::string path_;
  std::unique_ptr<File> file_;
  Report report_;
  std::string kind_;
  std::int64_t rows_ = 0;
  std::map<std::string, std::vector<std::string>> tables_;
  std::map<std::string, Object> parameters_, labels_, scalars_, constants_;
  std::map<std::string, Object> fields_;      // by name; concept path inside
  std::map<std::string, Object> mesh_labels_;
  std::set<std::string> used_names_;
  std::string mesh_kind_, per_;
  std::int64_t n_nodes_ = 0, n_cells_ = 0, instances_ = 0;
  int axes_ = 0;
  std::set<std::string> model_ids_;
  std::vector<std::string> scale_paths_seen_;
};

Object Validator::object(const std::string& h5, const std::string& concept,
                         const std::string& name) {
  Object o;
  o.h5 = h5;
  o.concept = concept;
  o.name = name;
  o.info = file_->dataset_info(h5);
  o.attrs = file_->attributes(h5);
  return o;
}

void Validator::check_attrs(const Object& o, const AttrSpec& spec) {
  for (const auto& a : o.attrs) {
    if (kMachinery.count(a.name)) continue;
    const auto it = spec.find(a.name);
    if (it == spec.end()) {
      add("W5", o.concept, "the attribute " + a.name + " is not defined by this version; it is "
                           "ignored");
      continue;
    }
    if (a.too_large) {
      add("E3", o.concept, a.name + " declares more elements than a reader will read; it must "
                           "be a scalar");
      continue;
    }
    bool good = false;
    switch (it->second) {
      case Kind::S: good = is_spec_string(a.type) && valid_utf8(a.raw_bytes.empty() ? a.value.as_text() : strip_nul(a.raw_bytes)); break;
      case Kind::F: good = is_spec_float64(a.type); break;
      case Kind::I: good = is_spec_int64(a.type); break;
      case Kind::Bits: good = is_spec_int64(a.type) || is_spec_int32(a.type); break;
    }
    if (!good) {
      const char* want = it->second == Kind::S   ? "a fixed-length UTF-8 string"
                         : it->second == Kind::F ? "a float64"
                                                 : "an integer";
      add("E3", o.concept, a.name + " must be stored as " + want + " with a scalar dataspace "
                           "(spec section 9.2)");
    }
  }
}

void Validator::check_name(const std::string& name, const std::string& concept, bool root) {
  if (!legal_netcdf_name(name)) {
    add("E8", concept, "\"" + name + "\" is not a legal name (spec section 9.3)");
  } else if (reserved_name(name)) {
    add("E8", concept, "\"" + name + "\" takes the reserved prefix mestra_");
  } else if (root && (kReservedRoot.count(name) || name.compare(0, 9, "category_") == 0)) {
    add("E8", concept, "\"" + name + "\" is a reserved name at the root (spec section 9.3)");
  }
  if (!used_names_.insert(name).second) {
    add("E8", concept, "the name \"" + name + "\" is used twice; names are unique in a file "
                       "(spec section 4.4)");
  }
}

void Validator::check_units(const Object& o, bool required) {
  const std::string units = o.text("units");
  if (units.empty()) {
    if (required) add("E7", o.concept, "units are required; give a UDUNITS string such as Pa or 1");
  } else if (!units_parse(units)) {
    add("E7", o.concept, "the units \"" + units + "\" do not parse by the grammar of spec "
                         "section 13");
  }
}

bool Validator::check_dims(const Object& o, const std::vector<std::string>& dims,
                           const std::vector<std::string>& scale_paths) {
  if (o.info.shape.size() != dims.size()) {
    add("E5", o.concept, "has " + std::to_string(o.info.shape.size()) + " axes and spec section "
                         "10 gives it " + std::to_string(dims.size()));
    return false;
  }
  for (std::size_t a = 0; a < dims.size(); ++a) {
    // Lengths the file fixes elsewhere (E5).
    std::int64_t want = -1;
    if (dims[a] == "row") want = rows_;
    if (mesh_kind_ == "shared" && dims[a] == "node") want = n_nodes_;
    if (mesh_kind_ == "shared" && dims[a] == "cell") want = n_cells_;
    if (want >= 0 && static_cast<std::int64_t>(o.info.shape[a]) != want) {
      add("E5", o.concept, "axis " + std::to_string(a) + " (" + dims[a] + ") has " +
                           std::to_string(o.info.shape[a]) + " entries and needs " +
                           std::to_string(want));
    }
    const auto& attached = o.info.scales.size() > a ? o.info.scales[a] : std::vector<std::string>();
    if (attached.size() != 1) {
      add("E19", o.concept, "axis " + std::to_string(a) + " needs exactly one dimension scale, "
                            "named " + dims[a] + ", and has " + std::to_string(attached.size()));
      continue;
    }
    if (attached[0] != dims[a]) {
      add("E19", o.concept, "axis " + std::to_string(a) + " is attached to " + attached[0] +
                            " and should be " + dims[a]);
      continue;
    }
    const DsetInfo s = file_->dataset_info(scale_paths[a], false);
    if (s.is_dataset && s.shape.size() == 1 && s.shape[0] != o.info.shape[a]) {
      add("E19", o.concept, "axis " + std::to_string(a) + " has " + std::to_string(o.info.shape[a]) +
                            " entries and its scale " + dims[a] + " says " +
                            std::to_string(s.shape[0]));
    }
  }
  return true;
}

void Validator::check_storage(const Object& o, bool leading_class,
                              const std::vector<bool>& growable) {
  const DsetInfo& i = o.info;
  bool any_unlimited = false;
  for (std::size_t a = 0; a < i.maxshape.size(); ++a) {
    const bool unlimited = i.maxshape[a] == H5S_UNLIMITED;
    any_unlimited = any_unlimited || unlimited;
    const bool may = a < growable.size() && growable[a];
    if (unlimited && !may) {
      add("E19", o.concept, "axis " + std::to_string(a) + " is unlimited and spec section 10 "
                            "does not let it grow");
    }
  }
  if (any_unlimited && !i.chunked) {
    add("E20", o.concept, "a dataset with a growable axis must be chunked");
  }
  for (const auto& flt : i.filters) {
    const bool ok = flt.first == H5Z_FILTER_SHUFFLE ||
                    (flt.first == H5Z_FILTER_DEFLATE && !flt.second.empty() &&
                     flt.second[0] >= 1 && flt.second[0] <= 9);
    if (!ok) {
      add("E20", o.concept, "uses filter " + std::to_string(flt.first) + "; only gzip (levels 1 "
                            "to 9) and shuffle are allowed (spec section 11.2)");
    }
  }
  if (i.has_fill_value_set || o.has("_FillValue")) {
    add("E20", o.concept, "sets a fill value; every element is written and no fill value is "
                          "declared (spec section 11.1)");
  }
  if (i.chunked && !i.shape.empty()) {
    const std::size_t item = i.type.size == 0 ? 1 : i.type.size;
    const std::vector<hsize_t> trailing(i.shape.begin() + 1, i.shape.end());
    const std::vector<hsize_t> dflt =
        leading_class ? leading_chunk(item, trailing) : end_to_end_chunk(item, trailing);
    // Only the leading axis is compared for size; trailing axes must not
    // exceed the default either.
    if (chunk_larger_than_default(i.chunk, dflt)) {
      add("W6", o.concept, "its chunks are larger than the default of spec section 11.4, which "
                           "makes partial reads slower; rewriting the file restores it");
    }
  }
}

namespace {

// Elements in `shape`, or more than `cap` when the product exceeds it.
std::size_t elements(const std::vector<hsize_t>& shape, std::size_t cap) {
  std::size_t n = 1;
  for (const hsize_t x : shape) {
    if (x != 0 && n > cap / x) return cap + 1;
    n *= static_cast<std::size_t>(x);
  }
  return n;
}

}  // namespace

template <class T, class F>
void Validator::each(const Object& o, F f) {
  const std::size_t n = elements(o.info.shape, kMaxCheckElements);
  if (n > kMaxCheckElements || n == 0 || o.info.shape.empty()) return;
  const std::size_t stride = n / static_cast<std::size_t>(o.info.shape[0]);
  // Small blocks also bound what HDF5 keeps per chunk touched.
  const std::size_t rows = std::max<std::size_t>(1, (std::size_t(1) << 16) / std::max<std::size_t>(stride, 1));
  const DType t = std::is_same<T, double>::value ? DType::Float64 : DType::Int64;
  std::vector<T> block;
  std::size_t index = 0;
  for (std::size_t a = 0; a < o.info.shape[0]; a += rows) {
    const std::size_t b = std::min<std::size_t>(o.info.shape[0], a + rows);
    block.resize((b - a) * stride);
    file_->read(o.h5, t, {Selection::range(static_cast<std::int64_t>(a), static_cast<std::int64_t>(b))},
                block.data(), block.size() * sizeof(T));
    for (const T x : block) {
      if (!f(index++, x)) return;   // the callback stops the walk
    }
  }
}

std::vector<std::int64_t> Validator::ints(const Object& o) {
  const std::size_t n = elements(o.info.shape, kMaxCheckElements);
  if (n > kMaxCheckElements) return {};
  std::vector<std::int64_t> out(n);
  if (n) file_->read(o.h5, DType::Int64, {}, out.data(), n * 8);
  return out;
}

std::vector<double> Validator::floats(const Object& o) {
  const std::size_t n = elements(o.info.shape, kMaxCheckElements);
  if (n > kMaxCheckElements) return {};
  std::vector<double> out(n);
  if (n) file_->read(o.h5, DType::Float64, {}, out.data(), n * 8);
  return out;
}

// The cells, a block at a time, so a mesh of any size is checked in bounded
// memory: each type against spec section 15, offsets from 0 to the
// connectivity's length with each cell's node count, and every node number
// inside its instance (cn, cc: where each instance's nodes and cells start;
// one instance on a shared mesh). `digest`, when given, takes the types, the
// offsets and the connectivity in that order (spec section 14). False when a
// finding stopped the walk.
bool Validator::check_cells(const Object& t, const Object& o, const Object& c,
                            const std::vector<std::int64_t>& cn,
                            const std::vector<std::int64_t>& cc, Sha256* digest) {
  for (const Object* x : {&t, &o, &c}) {
    if (x->info.shape.size() != 1) return false;   // check_dims reports the shape
    if (x->info.shape[0] > kMaxDatasetElements) {
      add("E23", x->concept, "holds " + std::to_string(x->info.shape[0]) + " entries, more than the " +
                                 std::to_string(kMaxDatasetElements) + " a checker reads");
      return false;
    }
  }
  const auto n = static_cast<std::int64_t>(t.info.shape[0]);
  const auto nc = static_cast<std::int64_t>(c.info.shape[0]);
  if (static_cast<std::int64_t>(o.info.shape[0]) != n + 1) {
    add("E10", "cells", "cell_offsets needs one more entry than there are cells");
    return false;
  }
  const std::int64_t block = std::int64_t(1) << 16;
  std::vector<std::int64_t> tv, ov, cv;
  auto read = [&](const Object& x, std::int64_t a, std::int64_t b, std::vector<std::int64_t>& out) {
    out.resize(static_cast<std::size_t>(b - a));
    if (b > a) file_->read(x.h5, DType::Int64, {Selection::range(a, b)}, out.data(), out.size() * 8);
  };
  for (std::int64_t a = 0; a < n; a += block) {
    const std::int64_t b = std::min(n, a + block);
    read(t, a, b, tv);
    for (std::int64_t j = a; j < b; ++j) {
      const auto type = tv[static_cast<std::size_t>(j - a)];
      if (nodes_of_type(static_cast<int>(type)) == 0) {
        add("E6", "cells", "cell " + std::to_string(j) + " has type " + std::to_string(type) +
                               ", not in spec section 15");
        return false;
      }
    }
    if (digest) {
      const std::vector<std::uint8_t> t8(tv.begin(), tv.end());
      digest->update(t8.data(), t8.size());
    }
  }
  // Offsets, with the types again for each cell's node count; where each
  // instance's connectivity starts is noted on the way.
  std::vector<std::int64_t> bound;
  std::size_t next = 0;
  for (std::int64_t a = 0; a <= n; a += block) {
    const std::int64_t b = std::min(n, a + block);    // cells [a, b), offsets [a, b]
    read(o, a, b + 1, ov);
    read(t, a, b, tv);
    if (a == 0 && ov[0] != 0) {
      add("E10", "cells", "cell_offsets must start at 0");
      return false;
    }
    for (std::int64_t j = a; j <= b; ++j) {
      while (next < cc.size() && cc[next] == j) {
        bound.push_back(ov[static_cast<std::size_t>(j - a)]);
        ++next;
      }
      if (j == b) break;
      const int want = nodes_of_type(static_cast<int>(tv[static_cast<std::size_t>(j - a)]));
      const std::int64_t have = ov[static_cast<std::size_t>(j - a + 1)] - ov[static_cast<std::size_t>(j - a)];
      if (have < 0 || (want > 0 && have != want) || (want < 0 && have < 3)) {
        add("E10", "cells", "cell " + std::to_string(j) + " has " + std::to_string(have) +
                                " nodes, which its type does not allow");
        return false;
      }
    }
    if (digest) digest->update(ov.data(), static_cast<std::size_t>(b - a) * 8);
    if (b == n) {
      if (ov.back() != nc) {
        add("E10", "cells", "cell_offsets must end at the connectivity's length, " +
                                std::to_string(nc));
        return false;
      }
      if (digest) digest->update(&ov.back(), 8);
      break;
    }
  }
  // Node numbers, each inside its instance.
  std::size_t k = 0;
  for (std::int64_t a = 0; a < nc; a += block) {
    const std::int64_t b = std::min(nc, a + block);
    read(c, a, b, cv);
    for (std::int64_t q = a; q < b; ++q) {
      while (k + 2 < bound.size() && q >= bound[k + 1]) ++k;
      const std::int64_t nodes = cn[k + 1] - cn[k];
      const auto v = cv[static_cast<std::size_t>(q - a)];
      if (v < 0 || v >= nodes) {
        add("E10", "cells", cn.size() == 2
                                ? "a node number is outside [0, " + std::to_string(nodes) + ")"
                                : "connectivity entry " + std::to_string(q) + " names node " +
                                      std::to_string(v) + ", outside its instance's " +
                                      std::to_string(nodes) + " nodes");
        return false;
      }
    }
    if (digest) digest->update(cv.data(), cv.size() * 8);
  }
  return true;
}

void Validator::root_attrs() {
  Object root;
  root.h5 = "/";
  root.concept = "";
  root.attrs = file_->attributes("/");
  check_attrs(root, kRootAttrs);
  const std::string format = root.text("format");
  if (format != "mestra/1") {
    add("E1", "", format.empty() ? "the file has no format attribute; it is not a file of this "
                                   "format"
                                 : "format is \"" + format + "\"; this version reads mestra/1");
  }
  kind_ = root.text("kind");
  if (kind_ != "data" && kind_ != "model") {
    add("E1", "", "kind must be data or model, and is \"" + kind_ + "\"");
  }
  for (const char* req : {"writer", "created", "file_id"}) {
    if (!root.has(req)) add("E2", "", std::string("the file needs the attribute ") + req);
  }
  const std::string created = root.text("created");
  if (!created.empty() && !iso8601_utc(created)) {
    add("W8", "", "created is \"" + created + "\", not an ISO 8601 UTC timestamp");
  }
  if (kind_ == "data" && root.has("trained_on")) {
    add("W5", "", "trained_on belongs to model files and is ignored here");
  }
}

void Validator::walk_links() {
  // Every link of the public tree: hard links only (E22), bounded depth (E23).
  std::vector<std::pair<std::string, int>> todo = {{"/", 0}};
  while (!todo.empty()) {
    const auto here = todo.back();
    todo.pop_back();
    if (here.second > kMaxGroupDepth) {
      add("E23", here.first, "nested deeper than this reader walks (" +
                             std::to_string(kMaxGroupDepth) + ")");
      continue;
    }
    for (const Member& m : file_->members(here.first)) {
      const std::string child = (here.first == "/" ? "/" : here.first + "/") + m.name;
      if (m.kind != LinkKind::Hard) {
        add("E22", child, std::string("is ") + link_kind_name(m.kind) +
                          "; a file holds hard links only, and readers never follow others");
        continue;
      }
      if (m.is_group && child != "/private" && child != "/VTKHDF") {
        todo.emplace_back(child, here.second + 1);
      }
    }
  }
}

void Validator::tables() {
  for (const Member& m : file_->members("/categories")) {
    if (m.kind != LinkKind::Hard) continue;
    const std::string concept = "categories/" + m.name;
    guarded(concept, [&] {
      if (!m.is_dataset) {
        add("W5", concept, "is not a table and is ignored");
        return;
      }
      Object o = object("/categories/" + m.name, concept, m.name);
      if (!legal_netcdf_name(m.name) || reserved_name(m.name)) {
        add("E8", concept, "\"" + m.name + "\" is not a legal table name");
      }
      check_attrs(o, kNone);
      if (o.info.type.klass != H5T_STRING || o.info.type.variable_length) {
        add("E4", concept, "a category table is a fixed-length UTF-8 string dataset");
        return;
      }
      if (o.info.type.cset != H5T_CSET_UTF8 || o.info.type.strpad != H5T_STR_NULLPAD) {
        add("E4", concept, "a category table is UTF-8 and NUL-padded");
      }
      check_dims(o, {"category_" + m.name}, {"/category_" + m.name});
      check_storage(o, true, {true});
      const std::vector<std::string> entries =
          file_->read_strings(o.h5, kMaxTableEntries, kMaxTableBytes);
      std::set<std::string> seen;
      std::size_t longest = 1;
      for (const auto& e : entries) {
        if (!valid_utf8(e)) add("E4", concept, "an entry is not valid UTF-8");
        if (!seen.insert(e).second) add("E9", concept, "the entry \"" + e + "\" is listed twice");
        longest = std::max(longest, e.size());
      }
      if (o.info.type.size > longest) {
        add("W7", concept, "its strings are " + std::to_string(o.info.type.size) +
                           " bytes wide and the longest entry needs " + std::to_string(longest));
      }
      tables_[m.name] = entries;
    });
  }
}

void Validator::row() {
  guarded("row", [&] {
    if (!file_->is_dataset("/row")) {
      add("E2", "row", "the file needs the row ids (/row)");
      return;
    }
    Object o = object("/row", "row", "row");
    DType t;
    if (!dtype_of(o.info.type, &t) || t != DType::Int64) add("E4", "row", "row ids are int64");
    if (!o.info.is_scale) add("E19", "row", "row is a coordinate variable: a dimension scale");
    if (!(o.info.attr_order_tracked && o.info.attr_order_indexed)) {
      add("E19", "row", "a dimension scale has attribute creation order tracked and indexed");
    }
    if (o.info.shape.size() != 1) {
      add("E5", "row", "row is one-dimensional");
      return;
    }
    rows_ = static_cast<std::int64_t>(o.info.shape[0]);
    check_storage(o, true, {true});
    // Writers give increasing ids, checked as they stream; other orders
    // are sorted (within the checker's cap) to find a repeat.
    bool increasing = true;
    std::int64_t last = 0;
    each<std::int64_t>(o, [&](std::size_t i, std::int64_t id) {
      if (i > 0 && id <= last) increasing = false;
      last = id;
      return increasing;
    });
    if (!increasing) {
      std::vector<std::int64_t> ids = ints(o);
      std::sort(ids.begin(), ids.end());
      const auto rep = std::adjacent_find(ids.begin(), ids.end());
      if (rep != ids.end()) add("E14", "row", "the row id " + std::to_string(*rep) + " is used twice");
    }
  });
}

void Validator::root_objects() {
  for (const Member& m : file_->members("/")) {
    if (m.kind != LinkKind::Hard) continue;
    if (m.name == "row") continue;
    // category_<t> is a table's dimension scale; anything else by that
    // name takes a reserved prefix (E8, through check_name below).
    if (m.name.compare(0, 9, "category_") == 0 && m.is_dataset &&
        file_->dataset_info("/" + m.name, false).is_dataset &&
        file_->attributes("/" + m.name).size() > 0) {
      bool scale = false;
      for (const auto& a : file_->attributes("/" + m.name)) scale = scale || a.name == "CLASS";
      if (scale) continue;
    }
    if (m.is_group) {
      if (m.name == "categories" || m.name == "mesh" || m.name == "models" ||
          m.name == "notes" || m.name == "private" || m.name == "VTKHDF") {
        continue;
      }
      add("W5", m.name, "the group " + m.name + " is not defined by this version and is ignored");
      continue;
    }
    guarded(m.name, [&] {
      Object o = object("/" + m.name, m.name, m.name);
      const std::string role = o.text("role");
      if (role.empty()) {
        if (!o.info.is_scale) add("W5", m.name, "has no role and is ignored");
        return;
      }
      check_name(m.name, m.name, true);
      DType t = DType::Float64;
      const bool typed = dtype_of(o.info.type, &t);
      if (kParameterRoles.count(role)) {
        check_attrs(o, kParameterAttrs);
        if (!typed || (t != DType::Float64 && t != DType::Int64)) {
          add("E4", m.name, "a parameter is float64 or int64");
        }
        check_units(o, true);
        const auto lo = o.real("lower"), hi = o.real("upper");
        if (lo.has_value() != hi.has_value()) {
          add("E16", m.name, "give both bounds or neither");
        } else if (lo && (!std::isfinite(*lo) || !std::isfinite(*hi) || *lo > *hi)) {
          add("E16", m.name, "bounds must be finite with lower <= upper");
        }
        if (kind_ == "model" && !lo) {
          add("E16", m.name, "a model file's parameters need bounds: the model's domain");
        }
        if (!o.text("run_group").empty() && role != "time") {
          add("E15", m.name, "run_group belongs on a time parameter");
        }
        if (check_dims(o, {"row"}, {"/row"})) check_storage(o, true, {true});
        parameters_[m.name] = o;
      } else if (kLabelRoles.count(role)) {
        check_attrs(o, kLabelAttrs);
        if (!typed || (t != DType::Int32 && t != DType::Int64)) {
          add("E4", m.name, "a label's codes are int32 or int64");
        }
        if (o.has("lower") || o.has("upper")) add("E16", m.name, "a label has no bounds");
        if (check_dims(o, {"row"}, {"/row"})) check_storage(o, true, {true});
        labels_[m.name] = o;
      } else if (role == "scalar") {
        check_attrs(o, kResultAttrs);
        if (!typed || (t != DType::Float32 && t != DType::Float64)) {
          add("E4", m.name, "a scalar is float32 or float64");
        }
        check_units(o, true);
        if (check_dims(o, {"row"}, {"/row"})) check_storage(o, true, {true});
        scalars_[m.name] = o;
      } else if (role == "constant") {
        check_attrs(o, kConstantAttrs);
        if (!typed || (t != DType::Float32 && t != DType::Float64 && t != DType::Int64)) {
          add("E4", m.name, "a constant is float32, float64 or int64");
        }
        check_units(o, true);
        if (!o.info.shape.empty()) add("E5", m.name, "a constant has no axes");
        constants_[m.name] = o;
      } else {
        used_names_.erase(m.name);
        add("W5", m.name, "the role \"" + role + "\" is not defined by this version; the object "
                          "is ignored");
      }
    });
  }
  // Labels and their tables; status at most once; the groups that are named.
  int status = 0;
  for (auto& kv : labels_) {
    const Object& o = kv.second;
    status += o.text("role") == "status";
    const std::string table = o.text("category");
    if (table.empty() || !tables_.count(table)) {
      add("E9", kv.first, "category must name a table under categories/");
      continue;
    }
    const std::int64_t size = static_cast<std::int64_t>(tables_[table].size());
    each<std::int64_t>(o, [&](std::size_t i, std::int64_t c) {
      if (c >= 0 && c < size) return true;
      add("E9", kv.first, "row " + std::to_string(i) + " has code " + std::to_string(c) +
                          ", outside its table of " + std::to_string(size));
      return false;
    });
  }
  if (status > 1) add("E15", "", "a file has at most one status label");
  auto is_group_label = [&](const std::string& name) {
    const auto it = labels_.find(name);
    return it != labels_.end() && it->second.text("role") == "group";
  };
  Object root;
  root.attrs = file_->attributes("/");
  const std::string gg = root.text("generalisation_group");
  if (!gg.empty() && !is_group_label(gg)) {
    add("E15", "", "generalisation_group must name a group label, and \"" + gg + "\" is not one");
  }
  for (const auto& kv : parameters_) {
    const std::string rg = kv.second.text("run_group");
    if (!rg.empty() && !is_group_label(rg)) {
      add("E15", kv.first, "run_group must name a group label, and \"" + rg + "\" is not one");
    }
  }
}

void Validator::mesh() {
  if (!file_->exists("/mesh")) return;
  if (!file_->is_group("/mesh")) {
    add("E2", "mesh", "mesh must be a group");
    return;
  }
  Object m;
  m.h5 = "/mesh";
  m.concept = "mesh";
  m.attrs = file_->attributes("/mesh");
  check_attrs(m, kMeshAttrs);
  mesh_kind_ = m.text("kind");
  per_ = m.text("per");
  if (mesh_kind_ != "shared" && mesh_kind_ != "changing") {
    add("E6", "mesh", "kind must be shared or changing, and is \"" + mesh_kind_ + "\"");
    return;
  }
  const bool group = per_.compare(0, 6, "group:") == 0;
  if (!(per_ == "fixed" || per_ == "run" || group) ||
      (mesh_kind_ == "changing" && per_ == "fixed")) {
    add("E6", "mesh", "per \"" + per_ + "\" is not allowed for a " + mesh_kind_ + " mesh");
    return;
  }
  if (group) {
    const auto it = labels_.find(per_.substr(6));
    if (it == labels_.end() || it->second.text("role") != "group") {
      add("E6", "mesh", "per = " + per_ + " must name a group label");
    }
  }
  auto scale_len = [&](const std::string& p) -> std::int64_t {
    const DsetInfo i = file_->dataset_info(p, false);
    return i.is_dataset && i.shape.size() == 1 ? static_cast<std::int64_t>(i.shape[0]) : -1;
  };
  const bool shared = mesh_kind_ == "shared";
  n_nodes_ = scale_len("/mesh/node");
  n_cells_ = std::max<std::int64_t>(0, scale_len("/mesh/cell"));
  if (n_nodes_ < 0) {
    add("E2", "mesh", "the mesh needs its node dimension scale");
    return;
  }
  static const std::set<std::string> known = {
      "node", "axis", "cell", "cell_plus_one", "index", "instance", "instance_plus_one",
      "node_value", "cell_value", "coordinates", "cell_types", "cell_offsets",
      "cell_connectivity", "node_labels", "cell_labels", "node_fields", "cell_fields",
      "row_instance", "instance_nodes", "instance_cells", "row_node_start", "row_cell_start"};
  for (const Member& mm : file_->members("/mesh")) {
    if (mm.kind == LinkKind::Hard && !known.count(mm.name)) {
      add("W5", "mesh/" + mm.name, "is not defined by this version and is ignored");
    }
  }
  if (!shared && file_->exists("/mesh/instance")) {
    add("W5", "mesh/instance", "a changing mesh has no instance scale; it is ignored");
  }
  // Coordinates.
  Object coords;
  if (!file_->is_dataset("/mesh/coordinates")) {
    add("E2", "coordinates", "the mesh needs coordinates");
    return;
  }
  coords = object("/mesh/coordinates", "coordinates", "coordinates");
  check_attrs(coords, kCoordinateAttrs);
  check_units(coords, true);
  DType ct;
  if (!dtype_of(coords.info.type, &ct) || (ct != DType::Float32 && ct != DType::Float64)) {
    add("E4", "coordinates", "coordinates are float32 or float64");
  }
  if (coords.info.shape.empty()) {
    add("E5", "coordinates", "coordinates have axes");
    return;
  }
  axes_ = static_cast<int>(coords.info.shape.back());
  if (axes_ < 1 || axes_ > 3) add("E24", "coordinates", "coordinates have one to three axes");
  const bool cells = file_->exists("/mesh/cell_types");
  // Cells.
  std::optional<Object> cell_types, cell_offsets, cell_connectivity;
  std::int64_t n_cells = 0;
  if (cells) {
    guarded("cells", [&] {
      Object t = object("/mesh/cell_types", "cells/types", "cell_types");
      Object o = object("/mesh/cell_offsets", "cells/offsets", "cell_offsets");
      Object c = object("/mesh/cell_connectivity", "cells/connectivity", "cell_connectivity");
      DType d;
      if (!dtype_of(t.info.type, &d) || d != DType::UInt8) add("E4", "cells/types", "cell types are uint8");
      if (!dtype_of(o.info.type, &d) || d != DType::Int64) add("E4", "cells/offsets", "offsets are int64");
      if (!dtype_of(c.info.type, &d) || d != DType::Int64) add("E4", "cells/connectivity", "connectivity is int64");
      const bool grows = !shared;
      // Cells whose lengths disagree with their scales are reported there
      // and not walked: a declared length is not read past what it claims.
      const bool types_dims = check_dims(t, {"cell"}, {"/mesh/cell"});
      const bool offsets_dims = check_dims(o, {"cell_plus_one"}, {"/mesh/cell_plus_one"});
      const bool connectivity_dims = check_dims(c, {"index"}, {"/mesh/index"});
      const bool dims = types_dims && offsets_dims && connectivity_dims;
      check_storage(t, false, {grows});
      check_storage(o, false, {grows});
      check_storage(c, false, {grows});
      if (t.info.shape.size() == 1) n_cells = static_cast<std::int64_t>(t.info.shape[0]);
      if (!dims) return;
      cell_types = t;
      cell_offsets = o;
      cell_connectivity = c;
    });
  }
  const bool have_cells = cell_types && cell_offsets && cell_connectivity;
  // Mesh labels.
  for (const char* prefix : {"node_labels", "cell_labels"}) {
    for (const Member& mm : file_->members(std::string("/mesh/") + prefix)) {
      if (mm.kind != LinkKind::Hard) continue;
      const std::string concept = std::string(prefix) + "/" + mm.name;
      guarded(concept, [&] {
        Object o = object(std::string("/mesh/") + prefix + "/" + mm.name, concept, mm.name);
        check_name(mm.name, concept, false);
        check_attrs(o, kMeshLabelAttrs);
        DType d;
        if (!dtype_of(o.info.type, &d) || (d != DType::Int32 && d != DType::Int64)) {
          add("E4", concept, "a mesh label is int32 or int64");
        }
        const std::string w = where_word(prefix);
        if (w == "cell" && !cells) add("E5", concept, "a mesh without cells has no cell labels");
        if (check_dims(o, {w}, {"/mesh/" + w})) check_storage(o, false, {!shared});
        const std::string table = o.text("category");
        if (!table.empty()) {
          if (!tables_.count(table)) {
            add("E9", concept, "category names no table");
          } else {
            const std::int64_t size = static_cast<std::int64_t>(tables_[table].size());
            for (const auto v : ints(o)) {
              if (v < 0 || v >= size) {
                add("E9", concept, "a code is outside its table");
                break;
              }
            }
          }
        }
        mesh_labels_[mm.name] = o;
      });
    }
  }
  // Fields.
  for (const char* prefix : {"node_fields", "cell_fields"}) {
    for (const Member& mm : file_->members(std::string("/mesh/") + prefix)) {
      if (mm.kind != LinkKind::Hard) continue;
      const std::string concept = std::string(prefix) + "/" + mm.name;
      guarded(concept, [&] {
        if (!mm.is_dataset) {
          add("E5", concept, "a field is a dataset (a served field is a zero-length one)");
          return;
        }
        Object o = object(std::string("/mesh/") + prefix + "/" + mm.name, concept, mm.name);
        check_name(mm.name, concept, false);
        check_attrs(o, kResultAttrs);
        if (o.has("role")) add("W5", concept, "a field carries no role; it is ignored");
        DType d;
        if (!dtype_of(o.info.type, &d) || (d != DType::Float32 && d != DType::Float64)) {
          add("E4", concept, "a field is float32 or float64");
        }
        check_units(o, true);
        const std::string w = where_word(prefix);
        if (w == "cell" && !cells) add("E5", concept, "a mesh without cells has no cell fields");
        if (shared) {
          if (check_dims(o, {"row", w}, {"/row", "/mesh/" + w})) check_storage(o, true, {true, false});
        } else {
          const std::string dim = w + "_value";
          if (check_dims(o, {dim}, {"/mesh/" + dim})) check_storage(o, false, {true});
        }
        fields_[mm.name] = o;
      });
    }
  }
  if (shared) {
    if (per_ == "fixed") {
      if (check_dims(coords, {"node", "axis"}, {"/mesh/node", "/mesh/axis"})) {
        check_storage(coords, false, {false, false});
      }
    } else if (per_ == "run") {
      if (check_dims(coords, {"row", "node", "axis"}, {"/row", "/mesh/node", "/mesh/axis"})) {
        check_storage(coords, true, {true, false, false});
      }
      instances_ = rows_;
    } else {
      if (check_dims(coords, {"instance", "node", "axis"},
                     {"/mesh/instance", "/mesh/node", "/mesh/axis"})) {
        check_storage(coords, true, {true, false, false});
      }
      instances_ = static_cast<std::int64_t>(coords.info.shape[0]);
    }
    for (const char* cut : {"n_nodes", "n_cells", "n_instances"}) {
      if (m.has(cut)) add("W5", "mesh", std::string(cut) + " is not an attribute of version 1");
    }
    // Cells and the support id (spec section 14), a block at a time.
    guarded("mesh", [&] {
      Sha256 h;
      const std::int64_t nn = n_nodes_;
      h.update(&nn, 8);
      if (cells && (!have_cells || !check_cells(*cell_types, *cell_offsets, *cell_connectivity,
                                                {0, n_nodes_}, {0, n_cells}, &h))) {
        return;
      }
      if (!cells && per_ == "fixed" && coords.info.shape.size() == 2) {
        // A point cloud's fixed coordinates, as float64, a block of nodes at a time.
        const std::int64_t nodes = static_cast<std::int64_t>(coords.info.shape[0]);
        const std::int64_t width = static_cast<std::int64_t>(coords.info.shape[1]);
        if (static_cast<std::uint64_t>(nodes) * static_cast<std::uint64_t>(width) > kMaxDatasetElements) {
          add("E23", "coordinates", "holds " + std::to_string(nodes) + " × " + std::to_string(width) +
                                        " values, more than the " + std::to_string(kMaxDatasetElements) +
                                        " a checker reads");
          return;
        }
        const std::int64_t step = std::max<std::int64_t>(1, (std::int64_t(1) << 16) / std::max<std::int64_t>(width, 1));
        std::vector<double> pts;
        for (std::int64_t a = 0; a < nodes; a += step) {
          const std::int64_t b = std::min(nodes, a + step);
          pts.resize(static_cast<std::size_t>((b - a) * width));
          file_->read(coords.h5, DType::Float64, {Selection::range(a, b)}, pts.data(), pts.size() * 8);
          h.update(pts.data(), pts.size() * 8);
        }
      }
      const std::string want = h.hex();
      const std::string have = m.text("support_id");
      if (have != want) {
        add("E11", "mesh", have.empty() ? "the mesh needs its support_id"
                                        : "support_id does not match the mesh (spec section 14)");
      }
    });
  } else {
    // Changing mesh.
    guarded("mesh", [&] {
      // Without cells, every cell object is absent (spec section 10.4).
      if (!cells) {
        for (const char* p : {"/mesh/instance_cells", "/mesh/row_cell_start", "/mesh/cell_value",
                              "/mesh/cell", "/mesh/cell_plus_one", "/mesh/index",
                              "/mesh/cell_offsets", "/mesh/cell_connectivity"}) {
          if (file_->exists(p)) {
            add("E5", "mesh", std::string(p).substr(1) + " is present in a mesh without cells");
          }
        }
      }
      Object in = object("/mesh/instance_nodes", "mesh/instance_nodes", "instance_nodes");
      check_dims(in, {"instance_plus_one"}, {"/mesh/instance_plus_one"});
      check_storage(in, false, {true});
      if (check_dims(coords, {"node", "axis"}, {"/mesh/node", "/mesh/axis"})) {
        check_storage(coords, false, {true, false});
      }
      const auto cn = ints(in);
      std::vector<std::int64_t> cc;
      if (cells) {
        Object ic = object("/mesh/instance_cells", "mesh/instance_cells", "instance_cells");
        check_dims(ic, {"instance_plus_one"}, {"/mesh/instance_plus_one"});
        check_storage(ic, false, {true});
        cc = ints(ic);
      }
      auto monotone = [&](const std::vector<std::int64_t>& v, std::int64_t end, const char* what) {
        if (v.empty() || v[0] != 0) {
          add("E21", "mesh", std::string(what) + " must start at 0");
          return false;
        }
        for (std::size_t k = 1; k < v.size(); ++k) {
          if (v[k] < v[k - 1]) {
            add("E21", "mesh", std::string(what) + " decreases");
            return false;
          }
        }
        if (v.back() != end) {
          add("E21", "mesh", std::string(what) + " must end at " + std::to_string(end));
          return false;
        }
        return true;
      };
      const bool nodes_ok = monotone(cn, n_nodes_, "instance_nodes");
      const bool cells_ok = !cells || monotone(cc, n_cells, "instance_cells");
      instances_ = std::max<std::int64_t>(0, static_cast<std::int64_t>(cn.size()) - 1);
      if (cells && cc.size() != cn.size()) {
        add("E21", "mesh", "instance_nodes and instance_cells differ in length");
      }
      if (nodes_ok && cells_ok && cells && have_cells && cc.size() == cn.size()) {
        check_cells(*cell_types, *cell_offsets, *cell_connectivity, cn, cc, nullptr);
      }
      // Row starts: checked while the rows fit the checker's cap, as ints().
      if (static_cast<std::uint64_t>(rows_) > kMaxCheckElements) return;
      std::vector<std::int64_t> inst(static_cast<std::size_t>(rows_));
      if (group) {
        if (!file_->is_dataset("/mesh/row_instance")) {
          add("E2", "mesh", "a mesh that changes per group needs row_instance");
          return;
        }
        inst = ints(object("/mesh/row_instance", "mesh/row_instance", "row_instance"));
      } else {
        for (std::int64_t r = 0; r < rows_; ++r) inst[static_cast<std::size_t>(r)] = r;
      }
      for (const char* which : {"node", "cell"}) {
        if (!cells && std::string(which) == "cell") continue;
        const std::string p = std::string("/mesh/row_") + which + "_start";
        if (!file_->is_dataset(p)) {
          add("E2", "mesh", std::string("a changing mesh needs row_") + which + "_start");
          continue;
        }
        Object rs = object(p, std::string("mesh/row_") + which + "_start", "");
        if (check_dims(rs, {"row"}, {"/row"})) check_storage(rs, true, {true});
        const auto starts = ints(rs);
        const auto& cum = std::string(which) == "node" ? cn : cc;
        std::int64_t at = 0;
        for (std::size_t r = 0; r < starts.size() && r < inst.size(); ++r) {
          const std::int64_t k = inst[r];
          if (k < 0 || k + 1 >= static_cast<std::int64_t>(cum.size())) {
            add("E21", "mesh", "row " + std::to_string(r) + " names instance " + std::to_string(k) +
                               ", which does not exist");
            return;
          }
          if (starts[r] != at) {
            add("E21", "mesh", std::string("row_") + which + "_start disagrees with the instance "
                               "sizes at row " + std::to_string(r));
            break;
          }
          at += cum[static_cast<std::size_t>(k + 1)] - cum[static_cast<std::size_t>(k)];
        }
        const std::string vdim = std::string("/mesh/") + which + "_value";
        const std::int64_t values = scale_len(vdim);
        if (values >= 0 && values != at) {
          add("E21", "mesh", std::string(which) + " fields hold " + std::to_string(values) +
                             " values and the rows need " + std::to_string(at));
        }
      }
    });
  }
  // row_instance (per group, both kinds).
  if (group) {
    guarded("mesh/row_instance", [&] {
      if (!file_->is_dataset("/mesh/row_instance")) {
        add("E2", "mesh", "a mesh per group needs row_instance");
        return;
      }
      Object ri = object("/mesh/row_instance", "mesh/row_instance", "row_instance");
      if (check_dims(ri, {"row"}, {"/row"})) check_storage(ri, true, {true});
      const auto inst = ints(ri);
      const std::string label = per_.substr(6);
      if (!labels_.count(label)) return;
      const auto codes = ints(labels_[label]);
      std::map<std::int64_t, std::int64_t> of_code;
      std::int64_t next = 0;
      for (std::size_t r = 0; r < inst.size() && r < codes.size(); ++r) {
        const auto it = of_code.find(codes[r]);
        if (it == of_code.end()) {
          if (inst[r] != next) {
            add("E21", "mesh/row_instance", "instances must be numbered by first appearance; row " +
                                                std::to_string(r) + " has " + std::to_string(inst[r]) +
                                                " where " + std::to_string(next) + " comes next");
            return;
          }
          of_code[codes[r]] = next++;
        } else if (it->second != inst[r]) {
          add("E21", "mesh/row_instance", "two rows of one category have different instances (row " +
                                              std::to_string(r) + ")");
          return;
        }
      }
      if (next != instances_) {
        add("E21", "mesh/row_instance", "the rows use " + std::to_string(next) + " instances and the "
                                        "mesh holds " + std::to_string(instances_));
      }
    });
  }
}

void Validator::models() {
  const bool has = file_->is_group("/models");
  if (kind_ == "data") {
    if (has) add("E16", "models", "a data file holds no models");
    for (const auto* group : {&scalars_, &fields_}) {
      for (const auto& kv : *group) {
        if (kv.second.has("model")) {
          add("E16", kv.second.concept, "a data file stores its results; model belongs to model "
                                        "files");
        }
      }
    }
    return;
  }
  if (kind_ != "model") return;
  if (rows_ != 0) add("E16", "", "a model file has no rows");
  if (!has) {
    add("E16", "models", "a model file holds at least one model");
    return;
  }
  for (const Member& m : file_->members("/models")) {
    if (m.kind != LinkKind::Hard || !m.is_group) continue;
    const std::string concept = "models/" + m.name;
    Object o;
    o.h5 = "/models/" + m.name;
    o.concept = concept;
    o.attrs = file_->attributes(o.h5);
    std::vector<RawAttr> named;
    for (const auto& a : o.attrs) {
      if (kModelAttrs.count(a.name)) named.push_back(a);
    }
    Object only = o;
    only.attrs = named;
    check_attrs(only, kModelAttrs);
    if (o.text("type").empty()) add("E17", concept, "a model needs its type");
    if (!o.has("inputs")) add("E17", concept, "a model lists its inputs");
    const auto inputs = split_spaces(o.text("inputs"));
    for (const auto& in : inputs) {
      if (in != "coordinates" && !parameters_.count(in) && !labels_.count(in)) {
        add("E17", concept, "the input \"" + in + "\" is not a parameter, a label or coordinates");
      }
    }
    model_ids_.insert(m.name);
    guarded(concept, [&] {
      const Dict numbers = read_dict_group(*file_, o.h5, true);
      if (o.text("type") != "nearest") return;
      const Nearest nm = nearest_from(numbers);
      if (std::set<std::string>(nm.columns.begin(), nm.columns.end()) !=
          std::set<std::string>(inputs.begin(), inputs.end())) {
        add("E17", concept, "a nearest model's columns are exactly its inputs");
      }
      for (std::size_t j = 0; j < nm.columns.size(); ++j) {
        const auto it = parameters_.find(nm.columns[j]);
        if (it == parameters_.end()) {
          add("E17", concept, "a nearest model reads parameters only (" + nm.columns[j] + ")");
          continue;
        }
        const auto lo = it->second.real("lower"), hi = it->second.real("upper");
        if (!lo || !hi || *lo != nm.lower[j] || *hi != nm.upper[j]) {
          add("E17", concept, "a nearest model's bounds equal its parameters' bounds (" +
                              nm.columns[j] + ")");
        }
      }
    });
  }
  if (model_ids_.empty()) add("E16", "models", "a model file holds at least one model");
  for (const auto* group : {&scalars_, &fields_}) {
    for (const auto& kv : *group) {
      const Object& o = kv.second;
      const std::string model = o.text("model");
      if (model.empty()) {
        add("E16", o.concept, "every result of a model file names the model that computes it");
      } else if (!model_ids_.count(model)) {
        add("E17", o.concept, "names the model \"" + model + "\", which does not exist");
      } else if (o.text("output").empty()) {
        add("E17", o.concept, "a served result names its model's output");
      }
    }
  }
}

void Validator::relations_and_vectors() {
  std::map<std::string, const Object*> results;
  for (const auto& kv : scalars_) results[kv.first] = &kv.second;
  for (const auto& kv : fields_) results[kv.first] = &kv.second;
  std::map<std::string, std::vector<const Object*>> vectors;
  for (const auto& kv : results) {
    const Object& o = *kv.second;
    const std::string of = o.text("of"), stat = o.text("statistic"), wrt = o.text("with_respect_to");
    const bool is_field = o.concept.find('/') != std::string::npos;
    const std::string loc = is_field ? where_word(o.concept) : "scalar";
    if (!stat.empty() && stat != "std" && stat != "quantile") {
      add("W5", o.concept, "the statistic \"" + stat + "\" is not defined by this version; the "
                           "result is read as a plain result");
      continue;
    }
    if (o.has("q") && stat != "quantile") add("E12", o.concept, "q belongs to a quantile");
    if (stat == "quantile") {
      const auto q = o.real("q");
      if (!q || !(*q > 0.0 && *q < 1.0)) add("E12", o.concept, "a quantile needs q in (0, 1)");
    }
    if (!stat.empty() && !wrt.empty()) {
      add("E12", o.concept, "a result is a statistic or a derivative, not both");
    }
    if ((!stat.empty() || !wrt.empty()) && of.empty()) {
      add("E12", o.concept, "a relation names its result in of");
    }
    if (!of.empty() && stat.empty() && wrt.empty()) {
      add("E12", o.concept, "of needs a statistic or with_respect_to");
    }
    if (!of.empty()) {
      const auto t = results.find(of);
      if (t == results.end()) {
        add("E12", o.concept, "of names \"" + of + "\", which is not a result");
      } else {
        const Object& target = *t->second;
        if (!target.text("statistic").empty() || !target.text("with_respect_to").empty()) {
          add("E12", o.concept, "of names a relation");
        }
        const bool target_field = target.concept.find('/') != std::string::npos;
        const std::string tloc = target_field ? where_word(target.concept) : "scalar";
        if (wrt == "coordinates") {
          if (!(loc == "node" && tloc == "scalar")) {
            add("E12", o.concept, "a derivative with respect to node position is a node field whose "
                                  "of is a scalar");
          }
        } else if (tloc != loc) {
          add("E12", o.concept, "a relation has the location of its of");
        }
        if ((stat == "std" || stat == "quantile") && target.text("units") != o.text("units")) {
          add("E12", o.concept, "a " + stat + " has the units of its result");
        }
      }
    }
    if (!wrt.empty() && wrt != "coordinates" && !parameters_.count(wrt)) {
      add("E12", o.concept, "with_respect_to names \"" + wrt + "\", which is not a parameter");
    }
    if (wrt == "coordinates" && o.text("axis").empty()) {
      add("E12", o.concept, "a derivative with respect to coordinates names its axis");
    }
    const std::string vec = o.text("vector"), axis = o.text("axis");
    if (!vec.empty()) {
      if (!is_field) add("E13", o.concept, "scalars do not declare vectors");
      vectors[vec].push_back(&o);
    } else if (!axis.empty() && wrt != "coordinates") {
      add("E13", o.concept, "axis without vector on a field that is not a derivative");
    }
    if (!axis.empty() && axis != "x" && axis != "y" && axis != "z") {
      add("E13", o.concept, "axis is x, y or z");
    }
  }
  for (const auto& kv : vectors) {
    std::set<std::string> axes;
    for (const Object* o : kv.second) {
      if (where_word(o->concept) != where_word(kv.second[0]->concept) ||
          o->text("units") != kv.second[0]->text("units")) {
        add("E13", o->concept, "the fields of vector " + kv.first + " differ in location or units");
      }
      if (!axes.insert(o->text("axis")).second) {
        add("E13", o->concept, "two fields of vector " + kv.first + " claim axis " + o->text("axis"));
      }
      const std::string a = o->text("axis");
      const int index = a == "x" ? 0 : (a == "y" ? 1 : 2);
      if (axes_ > 0 && index >= axes_) {
        add("E13", o->concept, "axis " + a + " is not among the coordinates' axes");
      }
    }
  }
}

void Validator::scales() {
  // Every pure dimension scale: creation order (E19).
  std::vector<std::string> candidates;
  for (const Member& m : file_->members("/")) {
    if (m.kind == LinkKind::Hard && m.is_dataset && m.name.compare(0, 9, "category_") == 0) {
      candidates.push_back("/" + m.name);
    }
  }
  for (const Member& m : file_->members("/mesh")) {
    if (m.kind == LinkKind::Hard && m.is_dataset) candidates.push_back("/mesh/" + m.name);
  }
  for (const auto& p : candidates) {
    const DsetInfo i = file_->dataset_info(p);
    if (!i.is_scale) continue;
    if (!(i.attr_order_tracked && i.attr_order_indexed)) {
      add("E19", p.substr(1), "a dimension scale has attribute creation order tracked and indexed "
                              "(spec section 9.4)");
    }
  }
}

void Validator::warnings() {
  // W2 status, W3 non-finite results, W4 bounds, W10 negative std.
  for (const auto& kv : labels_) {
    if (kv.second.text("role") != "status") continue;
    const std::string table = kv.second.text("category");
    if (!tables_.count(table)) continue;
    std::int64_t bad = 0, first = -1;
    each<std::int64_t>(kv.second, [&](std::size_t r, std::int64_t c) {
      if (c >= 0 && c < static_cast<std::int64_t>(tables_[table].size()) &&
          tables_[table][static_cast<std::size_t>(c)] != "converged") {
        if (first < 0) first = static_cast<std::int64_t>(r);
        ++bad;
      }
      return true;
    });
    if (bad > 0) {
      add("W2", kv.first, counted(bad, "row is", "rows are") + " not converged, the first row " +
                          std::to_string(first) + "; training skips such rows by default");
    }
  }
  auto nonfinite = [&](const Object& o, bool scalar) {
    if (!o.text("model").empty()) return;
    std::int64_t bad = 0, first = -1;
    bool negative = false;
    each<double>(o, [&](std::size_t i, double x) {
      if (!std::isfinite(x)) {
        if (first < 0) first = static_cast<std::int64_t>(i);
        ++bad;
      }
      negative = negative || x < 0;
      return true;
    });
    if (bad > 0) {
      // Where a reader would look: a row, and on a shared mesh the node or
      // cell; a changing mesh's values are stored end to end.
      const auto f = static_cast<std::uint64_t>(first);
      const std::vector<hsize_t>& shape = o.info.shape;
      const bool node = o.h5.find("/node_fields/") != std::string::npos;
      std::string at = "element " + std::to_string(f);
      if (scalar) {
        at = "row " + std::to_string(f);
      } else if (shape.size() == 2 && shape[1] > 0) {
        at = "row " + std::to_string(f / shape[1]) + ", " + (node ? "node " : "cell ") +
             std::to_string(f % shape[1]);
      } else if (shape.size() == 1) {
        // A changing mesh: rows' values end to end, each row's start recorded.
        const std::string p = node ? "/mesh/row_node_start" : "/mesh/row_cell_start";
        if (file_->is_dataset(p)) {
          const auto starts = ints(object(p, "", ""));
          const auto it = std::upper_bound(starts.begin(), starts.end(), static_cast<std::int64_t>(f));
          if (it != starts.begin()) {
            const auto r = static_cast<std::size_t>(it - starts.begin() - 1);
            at = "row " + std::to_string(r) + ", " + (node ? "node " : "cell ") +
                 std::to_string(static_cast<std::int64_t>(f) - starts[r]);
          }
        }
      }
      add("W3", o.concept, counted(bad, "value is", "values are") + " missing or not finite, the "
                           "first at " + at);
    }
    if (o.text("statistic") == "std" && negative) add("W10", o.concept, "a std is never negative");
  };
  for (const auto& kv : scalars_) nonfinite(kv.second, true);
  for (const auto& kv : fields_) nonfinite(kv.second, false);
  for (const auto& kv : parameters_) {
    // A parameter is never missing (spec section 3.8): E5, as the writer
    // refuses it. Bounds give W4.
    const auto lo = kv.second.real("lower"), hi = kv.second.real("upper");
    bool missing = false, outside = false;
    each<double>(kv.second, [&](std::size_t r, double x) {
      if (std::isnan(x) && !missing) {
        missing = true;
        add("E5", kv.first, "row " + std::to_string(r) + " has no value; a parameter is never "
                            "missing (spec section 3.8)");
      } else if (lo && hi && !outside && (x < *lo || x > *hi)) {
        outside = true;
        add("W4", kv.first, "row " + std::to_string(r) + " is outside the bounds [" +
                            format_f64(*lo) + ", " + format_f64(*hi) + "]");
      }
      return !(missing && (outside || !lo || !hi));
    });
  }
  // W1: a published split dividing a generalisation group or a run.
  Object root;
  root.attrs = file_->attributes("/");
  std::vector<std::string> units;
  const std::string gg = root.text("generalisation_group");
  if (!gg.empty() && labels_.count(gg)) units.push_back(gg);
  for (const auto& kv : parameters_) {
    const std::string rg = kv.second.text("run_group");
    if (!rg.empty() && labels_.count(rg) &&
        std::find(units.begin(), units.end(), rg) == units.end()) {
      units.push_back(rg);
    }
  }
  for (const auto& kv : labels_) {
    if (kv.second.text("role") != "split") continue;
    const auto split = ints(kv.second);
    for (const auto& u : units) {
      const auto groups = ints(labels_[u]);
      std::map<std::int64_t, std::int64_t> side;
      for (std::size_t r = 0; r < split.size() && r < groups.size(); ++r) {
        const auto it = side.find(groups[r]);
        if (it == side.end()) {
          side[groups[r]] = split[r];
        } else if (it->second != split[r]) {
          add("W1", kv.first, "the split places rows of one " + u + " on both sides (row " +
                              std::to_string(r) + ")");
          break;
        }
      }
    }
  }
  // W9: two rows of one run at the same time.
  for (const auto& kv : parameters_) {
    const std::string rg = kv.second.text("run_group");
    if (kv.second.text("role") != "time" || rg.empty() || !labels_.count(rg)) continue;
    const auto t = floats(kv.second);
    const auto g = ints(labels_[rg]);
    std::set<std::pair<std::int64_t, double>> seen;
    for (std::size_t r = 0; r < t.size() && r < g.size(); ++r) {
      if (!seen.insert({g[r], t[r]}).second) {
        add("W9", kv.first, "two rows of one run share the time " + format_f64(t[r]) + " (row " +
                            std::to_string(r) + ")");
        break;
      }
    }
  }
}

Report Validator::run() {
  try {
    file_.reset(new File(File::open_read(path_)));
  } catch (const Error& e) {
    add("E1", "", e.what());
    return report_;
  }
  guarded("", [&] { root_attrs(); });
  guarded("", [&] { walk_links(); });
  guarded("categories", [&] { tables(); });
  row();
  guarded("", [&] { root_objects(); });
  guarded("mesh", [&] { mesh(); });
  guarded("models", [&] { models(); });
  guarded("", [&] { relations_and_vectors(); });
  guarded("", [&] { scales(); });
  guarded("", [&] { warnings(); });
  return report_;
}

}  // namespace

Report validate_file(const std::string& path) { return Validator(path).run(); }

}  // namespace internal
}  // namespace mestra
