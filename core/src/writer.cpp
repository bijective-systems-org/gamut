#include "writer.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <random>
#include <set>

#include "chunk.hpp"
#include "codec.hpp"
#include "names.hpp"
#include "nearest.hpp"
#include "reader.hpp"
#include "sha256.hpp"
#include "units.hpp"

namespace mestra {
namespace internal {

namespace {

void need(bool ok, const std::string& rule, const std::string& message,
          const std::string& path = {}) {
  if (!ok) throw Error(rule, message, path);
}

const std::set<std::string> kParameterRoles = {"design", "condition", "time"};
const std::set<std::string> kLabelRoles = {"group", "categorical", "status",
                                           "split"};
const std::set<std::string> kReserved = {"row", "coordinates", "categories",
                                         "mesh", "models", "notes", "private",
                                         "VTKHDF"};

bool is_float(DType t) { return t == DType::Float32 || t == DType::Float64; }
bool is_int(DType t) {
  return t == DType::Int8 || t == DType::Int32 || t == DType::Int64 ||
         t == DType::UInt8;
}

std::int64_t int_at(const Column& c, std::size_t i) {
  switch (c.dtype) {
    case DType::UInt8: return c.bytes[i];
    case DType::Int8: return static_cast<signed char>(c.bytes[i]);
    case DType::Int32: {
      std::int32_t x;
      std::memcpy(&x, &c.bytes[i * 4], 4);
      return x;
    }
    default: {
      std::int64_t x;
      std::memcpy(&x, &c.bytes[i * 8], 8);
      return x;
    }
  }
}

double float_at(const Column& c, std::size_t i) {
  if (c.dtype == DType::Float64) {
    double v;
    std::memcpy(&v, &c.bytes[i * 8], 8);
    return v;
  }
  float f;
  std::memcpy(&f, &c.bytes[i * 4], 4);
  return f;
}

// Converts `c` to `target`: floats among floats, integers among integers
// (range-checked), integers to floats.  Never floats to integers, even
// whole ones: a float given for a code or a count is taken as a mistake.
std::vector<unsigned char> convert(const Column& c, DType target,
                                   const std::string& what) {
  need(c.bytes.size() == static_cast<std::size_t>(c.count) * dtype_size(c.dtype),
       "", what + ": the values do not match their count and dtype", what);
  if (c.dtype == target) return c.bytes;
  const std::size_t n = static_cast<std::size_t>(c.count);
  std::vector<unsigned char> out(n * dtype_size(target));
  if (is_float(c.dtype) && is_float(target)) {
    for (std::size_t i = 0; i < n; ++i) {
      const double v = float_at(c, i);
      if (target == DType::Float64) {
        std::memcpy(&out[i * 8], &v, 8);
      } else {
        const float f = static_cast<float>(v);
        std::memcpy(&out[i * 4], &f, 4);
      }
    }
    return out;
  }
  if (is_int(c.dtype) && is_int(target)) {
    for (std::size_t i = 0; i < n; ++i) {
      const std::int64_t v = int_at(c, i);
      switch (target) {
        case DType::Int32: {
          need(v >= INT32_MIN && v <= INT32_MAX, "E4",
               what + ": " + std::to_string(v) + " does not fit in int32", what);
          const std::int32_t x = static_cast<std::int32_t>(v);
          std::memcpy(&out[i * 4], &x, 4);
          break;
        }
        case DType::Int64: std::memcpy(&out[i * 8], &v, 8); break;
        case DType::UInt8:
          need(v >= 0 && v <= 255, "E4",
               what + ": " + std::to_string(v) + " does not fit in uint8", what);
          out[i] = static_cast<unsigned char>(v);
          break;
        default:
          need(v >= -128 && v <= 127, "E4",
               what + ": " + std::to_string(v) + " does not fit in int8", what);
          out[i] = static_cast<unsigned char>(static_cast<signed char>(v));
          break;
      }
    }
    return out;
  }
  if (is_int(c.dtype) && is_float(target)) {
    for (std::size_t i = 0; i < n; ++i) {
      const double v = static_cast<double>(int_at(c, i));
      if (target == DType::Float64) {
        std::memcpy(&out[i * 8], &v, 8);
      } else {
        const float f = static_cast<float>(v);
        std::memcpy(&out[i * 4], &f, 4);
      }
    }
    return out;
  }
  throw Error("E4", what + ": " + dtype_name(c.dtype) +
                        " values cannot be stored as " + dtype_name(target) +
                        (is_float(c.dtype) ? "; give integers" : ""),
              what);
}

std::vector<std::int64_t> as_i64(const Column& c, const std::string& what) {
  const std::vector<unsigned char> b = convert(c, DType::Int64, what);
  std::vector<std::int64_t> out(static_cast<std::size_t>(c.count));
  if (!out.empty()) std::memcpy(out.data(), b.data(), b.size());
  return out;
}

// Spec section 11.3: keep `bits` explicit mantissa bits, round half to
// even, NaN and infinities unchanged.
void bitround(std::vector<unsigned char>* bytes, DType t, int bits) {
  if (bits < 0) return;
  if (t == DType::Float32) {
    if (bits >= 23) return;
    const int drop = 23 - bits;
    const std::uint32_t half = std::uint32_t(1) << (drop - 1);
    const std::uint32_t mask = ~((std::uint32_t(1) << drop) - 1);
    for (std::size_t i = 0; i + 4 <= bytes->size(); i += 4) {
      std::uint32_t u;
      std::memcpy(&u, &(*bytes)[i], 4);
      if ((u & 0x7f800000u) == 0x7f800000u) continue;
      u += half - 1 + ((u >> drop) & 1u);
      u &= mask;
      std::memcpy(&(*bytes)[i], &u, 4);
    }
  } else if (t == DType::Float64) {
    if (bits >= 52) return;
    const int drop = 52 - bits;
    const std::uint64_t half = std::uint64_t(1) << (drop - 1);
    const std::uint64_t mask = ~((std::uint64_t(1) << drop) - 1);
    for (std::size_t i = 0; i + 8 <= bytes->size(); i += 8) {
      std::uint64_t u;
      std::memcpy(&u, &(*bytes)[i], 8);
      if ((u & 0x7ff0000000000000ull) == 0x7ff0000000000000ull) continue;
      u += half - 1 + ((u >> drop) & 1u);
      u &= mask;
      std::memcpy(&(*bytes)[i], &u, 8);
    }
  }
}

std::string root(const std::string& name) { return "/" + name; }

std::string field_path(const Result& r) {
  return (r.where == "node" ? "/mesh/node_fields/" : "/mesh/cell_fields/") +
         r.name;
}

std::string label_dataset(const MeshLabel& m) {
  return (m.where == "node" ? "/mesh/node_labels/" : "/mesh/cell_labels/") +
         m.name;
}

void check_units(const std::string& units, const std::string& path) {
  need(!units.empty(), "E7", path + ": units are required", path);
  need(units_parse(units), "E7",
       path + ": the units \"" + units + "\" do not parse (spec section 13)",
       path);
}

// Spec section 15.
int nodes_of_type(int code) {
  switch (code) {
    case 1: return 1;
    case 3: return 2;
    case 5: return 3;
    case 7: return -3;    // three or more
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

void check_cells(const std::vector<std::uint8_t>& types,
                 const std::vector<std::int64_t>& offsets,
                 const std::vector<std::int64_t>& conn, std::int64_t n_nodes,
                 const std::string& where) {
  const std::size_t n = types.size();
  if (n == 0) {
    need(offsets.empty() && conn.empty(), "E10",
         where + ": no cells means no offsets and no connectivity");
    return;
  }
  need(offsets.size() == n + 1, "E10",
       where + ": cell_offsets needs one more entry than there are cells");
  need(offsets[0] == 0, "E10", where + ": cell_offsets must start at 0");
  for (std::size_t j = 0; j < n; ++j) {
    const int want = nodes_of_type(types[j]);
    need(want != 0, "E6",
         where + ": cell " + std::to_string(j) + " has type " +
             std::to_string(types[j]) + ", which is not in spec section 15");
    need(offsets[j + 1] >= offsets[j], "E10",
         where + ": cell_offsets decreases at cell " + std::to_string(j));
    const std::int64_t have = offsets[j + 1] - offsets[j];
    if (want > 0) {
      need(have == want, "E10",
           where + ": cell " + std::to_string(j) + " of type " +
               std::to_string(types[j]) + " has " + std::to_string(have) +
               " nodes and needs " + std::to_string(want));
    } else {
      need(have >= 3, "E10",
           where + ": polygon " + std::to_string(j) + " has fewer than 3 nodes");
    }
  }
  need(offsets.back() == static_cast<std::int64_t>(conn.size()), "E10",
       where + ": cell_offsets must end at the connectivity's length");
  for (const std::int64_t v : conn) {
    need(v >= 0 && v < n_nodes, "E10",
         where + ": node number " + std::to_string(v) + " is outside [0, " +
             std::to_string(n_nodes) + ")");
  }
}

std::string support_id_of(std::int64_t n_nodes,
                          const std::vector<std::uint8_t>& types,
                          const std::vector<std::int64_t>& offsets,
                          const std::vector<std::int64_t>& conn,
                          const std::vector<double>* fixed_cloud) {
  Sha256 h;
  h.update(&n_nodes, 8);
  if (!types.empty()) h.update(types.data(), types.size());
  if (!offsets.empty()) h.update(offsets.data(), offsets.size() * 8);
  if (!conn.empty()) h.update(conn.data(), conn.size() * 8);
  if (fixed_cloud != nullptr && !fixed_cloud->empty()) {
    h.update(fixed_cloud->data(), fixed_cloud->size() * 8);
  }
  return h.hex();
}

// A category table's chunk: the leading rule's, so a table that grows by
// appends rewrites at most 512 entries (spec section 11.4).
std::vector<hsize_t> table_chunk(std::size_t width) { return leading_chunk(width, {}); }

void write_table(File& f, const std::string& name,
                 const std::vector<std::string>& entries,
                 const FilterPipeline& filters) {
  const std::string path = "/categories/" + name;
  const std::string scale = "/category_" + name;
  std::size_t width = 1;
  for (const auto& e : entries) width = std::max(width, e.size());
  const hsize_t n = static_cast<hsize_t>(entries.size());
  f.make_scale(scale, n, true);
  f.create_dataset(path, DType::String, width, {n}, {H5S_UNLIMITED},
                   table_chunk(width), filters);
  f.write_strings(path, 0, entries);
  f.attach_scale(path, scale, 0);
}

}  // namespace

std::string new_uuid() {
  std::random_device rd;
  std::mt19937_64 gen((static_cast<std::uint64_t>(rd()) << 32) ^ rd() ^
                      static_cast<std::uint64_t>(
                          std::chrono::high_resolution_clock::now()
                              .time_since_epoch()
                              .count()));
  std::uint64_t a = gen(), b = gen();
  a = (a & 0xffffffffffff0fffull) | 0x0000000000004000ull;   // version 4
  b = (b & 0x3fffffffffffffffull) | 0x8000000000000000ull;   // variant 1
  char out[37];
  std::snprintf(out, sizeof out, "%08x-%04x-%04x-%04x-%012llx",
                static_cast<unsigned>(a >> 32),
                static_cast<unsigned>((a >> 16) & 0xffff),
                static_cast<unsigned>(a & 0xffff),
                static_cast<unsigned>(b >> 48),
                static_cast<unsigned long long>(b & 0xffffffffffffull));
  return out;
}

std::string utc_now() {
  const std::time_t t = std::time(nullptr);
  std::tm tm{};
#if defined(_WIN32)
  gmtime_s(&tm, &t);
#else
  gmtime_r(&t, &tm);
#endif
  char out[32];
  std::strftime(out, sizeof out, "%Y-%m-%dT%H:%M:%SZ", &tm);
  return out;
}

// A dataset whose first axis grows, buffered so rows reach the file in
// whole chunks within a session (spec section 11.4).
struct Writer::Pending {
  std::string path;
  DType dtype = DType::Float64;
  std::size_t entry_bytes = 0;
  std::vector<hsize_t> trailing;
  hsize_t chunk_rows = 1;
  std::int64_t on_disk = 0;
  std::vector<unsigned char> buffer;
  std::int64_t buffered = 0;
  std::int64_t total() const { return on_disk + buffered; }
};

std::unique_ptr<Writer::Pending> Writer::make_pending(
    const std::string& path, DType t, const std::vector<hsize_t>& trailing,
    hsize_t chunk_rows, std::int64_t on_disk) {
  auto p = std::make_unique<Pending>();
  p->path = path;
  p->dtype = t;
  p->trailing = trailing;
  hsize_t entries = 1;
  for (const hsize_t x : trailing) entries *= x;
  p->entry_bytes = dtype_size(t) * static_cast<std::size_t>(entries);
  p->chunk_rows = chunk_rows == 0 ? 1 : chunk_rows;
  p->on_disk = on_disk;
  return p;
}

std::unique_ptr<Writer> Writer::create(const std::string& path,
                                       const std::string& writer_name,
                                       const std::string& mesh_kind,
                                       const std::string& per) {
  need(mesh_kind.empty() || mesh_kind == "shared" || mesh_kind == "changing",
       "E6", "the mesh kind \"" + mesh_kind + "\" is not shared or changing");
  const bool group = per.compare(0, 6, "group:") == 0;
  if (mesh_kind.empty()) {
    need(per.empty() || per == "fixed", "E6", "a file without a mesh has no per");
  } else {
    need(per == "fixed" || per == "run" || group, "E6",
         "per \"" + per + "\" is not fixed, run or group:<label>");
    need(!(mesh_kind == "changing" && per == "fixed"), "E6",
         "a changing mesh changes per run or per group, never fixed");
  }
  std::unique_ptr<Writer> w(new Writer());
  w->path_ = path;
  w->file_.reset(new File(File::create(path)));
  w->created_ = true;
  Schema& s = w->schema_;
  s.kind = "data";
  s.writer = writer_name;
  s.created = utc_now();
  s.file_id = new_uuid();
  s.mesh.kind = mesh_kind;
  s.mesh.per = mesh_kind.empty() ? "fixed" : per;
  File& f = *w->file_;
  f.write_attr("/", "format", AttrValue::text("mestra/1"));
  f.write_attr("/", "kind", AttrValue::text("data"));
  f.write_attr("/", "writer", AttrValue::text(writer_name));
  f.write_attr("/", "created", AttrValue::text(s.created));
  f.write_attr("/", "file_id", AttrValue::text(s.file_id));
  const std::vector<hsize_t> chunk = leading_chunk(8, {});
  f.create_dataset("/row", DType::Int64, 0, {0}, {H5S_UNLIMITED}, chunk,
                   w->filters_, true);
  f.mark_coordinate_scale("/row", "row");
  w->pending_["/row"] = make_pending("/row", DType::Int64, {}, chunk[0], 0);
  return w;
}

std::unique_ptr<Writer> Writer::open_append(const std::string& path) {
  std::unique_ptr<Writer> w(new Writer());
  w->path_ = path;
  w->file_.reset(new File(File::open_write(path)));
  w->schema_ = load_schema(*w->file_);
  need(w->schema_.kind == "data", "E16",
       "runs are appended to data files, and \"" + path + "\" is a model file");
  File& f = *w->file_;
  w->filters_ = pipeline_of(f.dataset_info("/row", false));
  w->datasets_ready_ = true;
  w->schema_.mesh.set_done = !w->schema_.mesh.kind.empty();
  auto resume = [&](const std::string& p) {
    const DsetInfo info = f.dataset_info(p, false);
    if (!info.is_dataset || info.shape.empty()) return;
    DType t;
    if (!dtype_of(info.type, &t) || t == DType::String) return;
    w->pending_[p] = make_pending(
        p, t, std::vector<hsize_t>(info.shape.begin() + 1, info.shape.end()),
        info.chunked ? info.chunk[0] : 1, static_cast<std::int64_t>(info.shape[0]));
  };
  const Schema& s = w->schema_;
  resume("/row");
  for (const auto& x : s.parameters) resume(root(x.name));
  for (const auto& x : s.labels) resume(root(x.name));
  for (const auto& r : s.results) {
    resume(r.where == "scalar" ? root(r.name) : field_path(r));
  }
  const Mesh& m = s.mesh;
  if (m.kind == "shared" && m.per != "fixed") resume("/mesh/coordinates");
  if (!m.per_group().empty()) resume("/mesh/row_instance");
  if (m.kind == "changing") {
    for (const char* p : {"/mesh/instance_nodes", "/mesh/instance_cells",
                          "/mesh/coordinates", "/mesh/cell_types",
                          "/mesh/cell_offsets", "/mesh/cell_connectivity",
                          "/mesh/row_node_start", "/mesh/row_cell_start"}) {
      resume(p);
    }
    for (const auto& ml : m.labels) resume(label_dataset(ml));
    const bool cells = f.exists("/mesh/cell_types");
    w->schema_.mesh.has_cells = cells ? 1 : 0;
    const std::vector<std::int64_t> cn = f.read_i64("/mesh/instance_nodes");
    const std::vector<std::int64_t> cc = cells ? f.read_i64("/mesh/instance_cells")
                                               : std::vector<std::int64_t>(cn.size(), 0);
    for (std::size_t k = 0; k + 1 < cn.size(); ++k) {
      w->instance_nodes_.push_back(cn[k + 1] - cn[k]);
      w->instance_cells_.push_back(cc[k + 1] - cc[k]);
    }
    w->node_values_ = static_cast<std::int64_t>(f.dataset_info("/mesh/node_value", false).shape[0]);
    w->cell_values_ = cells ? static_cast<std::int64_t>(
                                  f.dataset_info("/mesh/cell_value", false).shape[0])
                            : 0;
  }
  w->instances_written_ = m.n_instances;
  if (!m.per_group().empty() && s.rows > 0) {
    const std::vector<std::int64_t> codes = f.read_i64("/" + m.per_group());
    const std::vector<std::int64_t> inst = f.read_i64("/mesh/row_instance");
    for (std::size_t i = 0; i < codes.size() && i < inst.size(); ++i) {
      w->member_instance_.emplace(codes[i], inst[i]);
    }
  }
  const std::vector<std::int64_t> ids = f.read_i64("/row");
  for (const std::int64_t id : ids) w->next_id_ = std::max(w->next_id_, id + 1);
  return w;
}

std::unique_ptr<Writer> Writer::create_model(const std::string& path,
                                             const std::string& writer_name,
                                             const std::string& mesh_kind,
                                             const std::string& per) {
  need(mesh_kind.empty() || mesh_kind == "shared", "E6",
       "a model file's mesh is shared (spec section 10.3)");
  need(mesh_kind.empty() || per == "fixed" || per == "run", "E6",
       "a model file's mesh is fixed, or computed per run by a model");
  std::unique_ptr<Writer> w = create(path, writer_name, mesh_kind, mesh_kind.empty() ? "fixed" : per);
  w->model_ = true;
  w->schema_.kind = "model";
  w->file_->replace_attr("/", "kind", AttrValue::text("model"));
  return w;
}

Writer::~Writer() {
  if (!closed_ && file_) {
    try {
      close();
    } catch (...) {
      // A destructor must not throw; close() is the call that reports.
    }
  }
}

void Writer::need_open() const { need(!closed_, "", "the file is closed"); }

void Writer::need_no_runs(const std::string& what) const {
  need(!datasets_ready_, "", what + " must come before the first run is added");
}

void Writer::check_new_root_name(const std::string& name) const {
  need(legal_netcdf_name(name), "E8",
       "\"" + name + "\" is not a legal name (spec section 9.3)", name);
  need(!reserved_name(name), "E8",
       "\"" + name + "\" takes the reserved prefix mestra_", name);
  need(kReserved.count(name) == 0 && name.compare(0, 9, "category_") != 0, "E8",
       "\"" + name + "\" is a reserved name (spec section 9.3)", name);
  need(!schema_.name_taken(name), "E8",
       "\"" + name + "\" is already used; names are unique in a file", name);
}

void Writer::set_attribute(const std::string& name, const std::string& value) {
  need_open();
  static const std::set<std::string> allowed = {"title", "license",
                                                "references", "source"};
  const bool special = (name == "trained_on" && model_) || (name == "evaluated_from" && !model_);
  need(allowed.count(name) == 1 || special, "",
       "\"" + name + "\" is not one of title, license, references, source" +
           std::string(model_ ? ", trained_on" : ", evaluated_from"));
  need(valid_utf8(value), "E3", name + " is not valid UTF-8");
  file_->replace_attr("/", name, AttrValue::text(value));
  if (name == "title") schema_.title = value;
  if (name == "license") schema_.license = value;
  if (name == "references") schema_.references = value;
  if (name == "source") schema_.source = value;
  if (name == "trained_on") schema_.trained_on = value;
  if (name == "evaluated_from") schema_.evaluated_from = value;
}

void Writer::set_note(const std::string& key, const AttrValue& value) {
  need_open();
  need(legal_netcdf_name(key) && !reserved_name(key), "E8",
       "the note key \"" + key + "\" is not a legal name", key);
  need(value.kind() != AttrValue::Kind::Str || valid_utf8(value.as_text()), "E3",
       key + ": a note is valid UTF-8", key);
  file_->make_group("/notes");
  file_->replace_attr("/notes", key, value);
}

void Writer::set_private(const std::string& name, const std::vector<unsigned char>& bytes) {
  need_open();
  need(legal_netcdf_name(name) && !reserved_name(name), "E8",
       "the private record \"" + name + "\" is not a legal name", name);
  file_->make_group("/private");
  const std::string path = "/private/" + name;
  if (file_->exists(path)) file_->remove_link(path);
  const hsize_t n = static_cast<hsize_t>(bytes.size());
  file_->create_dataset(path, DType::UInt8, 0, {n}, {}, {}, {});
  if (n > 0) file_->write(path, DType::UInt8, {0}, {n}, bytes.data());
}

void Writer::declare_parameter(const Parameter& p) {
  need_open();
  need_no_runs("declaring a parameter");
  check_new_root_name(p.name);
  need(kParameterRoles.count(p.role) == 1, "",
       p.name + ": the role \"" + p.role + "\" is not design, condition or time",
       p.name);
  check_units(p.units, p.name);
  need(p.auto_dtype || p.dtype == DType::Float64 || p.dtype == DType::Int64, "E4",
       p.name + ": a parameter is float64 or int64", p.name);
  need(p.lower.has_value() == p.upper.has_value(), "E16",
       p.name + ": give both bounds or neither", p.name);
  if (p.lower) {
    need(std::isfinite(*p.lower) && std::isfinite(*p.upper) && *p.lower <= *p.upper,
         "E16", p.name + ": bounds must be finite with lower <= upper", p.name);
  }
  need(p.run_group.empty() || p.role == "time", "E15",
       p.name + ": run_group belongs on a time parameter", p.name);
  need(!model_ || p.lower.has_value(), "E16",
       p.name + ": a model file's parameters need bounds, the model's domain", p.name);
  schema_.parameters.push_back(p);
}

void Writer::declare_label(const std::string& name, const std::string& role,
                           const std::vector<std::string>& categories) {
  need_open();
  need_no_runs("declaring a label");
  check_new_root_name(name);
  need(kLabelRoles.count(role) == 1, "",
       name + ": the role \"" + role +
           "\" is not group, categorical, status or split",
       name);
  if (role == "status") {
    for (const auto& l : schema_.labels) {
      need(l.role != "status", "E15", "a file has at most one status label", name);
    }
  }
  std::set<std::string> seen;
  for (const auto& c : categories) {
    need(valid_utf8(c), "E4", name + ": a category is not valid UTF-8", name);
    need(seen.insert(c).second, "E9",
         name + ": the category \"" + c + "\" is listed twice", name);
  }
  Label l;
  l.name = name;
  l.role = role;
  l.category = name;
  schema_.labels.push_back(l);
  schema_.tables[name] = categories;
}

void Writer::declare_result(const Result& r) {
  need_open();
  need_no_runs("declaring a result");
  need(r.where == "scalar" || r.where == "node" || r.where == "cell", "",
       r.name + ": a result is a scalar or a node or cell field", r.name);
  check_new_root_name(r.name);
  const std::string path = result_path(r);
  if (r.where != "scalar") {
    need(!schema_.mesh.kind.empty(), "",
         path + ": a field needs a mesh; create the file with one", path);
  }
  check_units(r.units, path);
  need(r.auto_dtype || is_float(r.dtype), "E4", path + ": results are float32 or float64",
       path);
  if (model_) {
    need(r.served() && !r.output.empty(), "E16",
         path + ": every result of a model file names its model and output", path);
  } else {
    need(!r.served(), "E16", path + ": a data file stores its results", path);
  }
  const Relation& rel = r.relation;
  need(rel.statistic.empty() || rel.statistic == "std" || rel.statistic == "quantile",
       "E12", path + ": statistic is std or quantile", path);
  need(!rel.q || rel.statistic == "quantile", "E12",
       path + ": q belongs to a quantile", path);
  if (rel.statistic == "quantile") {
    need(rel.q && *rel.q > 0.0 && *rel.q < 1.0, "E12",
         path + ": a quantile needs q in (0, 1)", path);
  }
  need(rel.statistic.empty() || rel.with_respect_to.empty(), "E12",
       path + ": a result is a statistic or a derivative, not both", path);
  need((rel.statistic.empty() && rel.with_respect_to.empty()) || !rel.of.empty(),
       "E12", path + ": a relation names its result in of", path);
  need(rel.of.empty() || !rel.statistic.empty() || !rel.with_respect_to.empty(),
       "E12", path + ": of needs a statistic or with_respect_to", path);
  need(rel.with_respect_to != "coordinates" || !rel.axis.empty(), "E12",
       path + ": a derivative with respect to coordinates names its axis", path);
  need(r.vector.empty() || r.where != "scalar", "E13",
       path + ": scalars do not declare vectors", path);
  need(r.vector.empty() == r.axis.empty(), "E13",
       path + ": vector and axis go together", path);
  for (const std::string& a : {r.axis, rel.axis}) {
    need(a.empty() || a == "x" || a == "y" || a == "z", "E13",
         path + ": axis is x, y or z", path);
  }
  need(r.round_bits < 0 ||
           (r.round_bits >= 1 && r.round_bits < (!r.auto_dtype && r.dtype == DType::Float32 ? 23 : 52)),
       "", path + ": round_bits keeps 1 to 22 bits of a float32, 1 to 51 of a "
                  "float64",
       path);
  schema_.results.push_back(r);
}

void Writer::declare_mesh_label(const MeshLabel& m,
                                const std::vector<std::string>& categories) {
  need_open();
  need(!schema_.mesh.kind.empty(), "", "a mesh label needs a mesh");
  need(m.where == "node" || m.where == "cell", "",
       "a mesh label is at nodes or cells");
  need(!schema_.mesh.set_done && !datasets_ready_, "",
       "mesh labels are declared before the mesh is set and before the first run");
  check_new_root_name(m.name);
  MeshLabel copy = m;
  copy.dtype = DType::Int32;
  if (!categories.empty()) {
    std::set<std::string> seen;
    for (const auto& c : categories) {
      need(valid_utf8(c), "E4", m.name + ": a category is not valid UTF-8", m.name);
      need(seen.insert(c).second, "E9",
           m.name + ": the category \"" + c + "\" is listed twice", m.name);
    }
    copy.category = m.name;
    need(schema_.tables.count(m.name) == 0, "E8",
         m.name + ": a table of that name already exists", m.name);
    schema_.tables[m.name] = categories;
  }
  schema_.mesh.labels.push_back(copy);
}

void Writer::declare_coordinates(const std::string& units, DType dtype, int axes,
                                 const std::string& model, const std::string& output) {
  need_open();
  need(model.empty() || (model_ && schema_.mesh.per == "run"), "E16",
       "coordinates computed by a model belong to a model file whose mesh is per run");
  need(!model_ || schema_.mesh.per == "fixed" || !model.empty(), "E16",
       "a model file's coordinates per run are computed by a model; name it");
  schema_.mesh.coordinate_model = model;
  schema_.mesh.coordinate_output = output;
  need(!schema_.mesh.kind.empty(), "", "coordinates need a mesh");
  need(!schema_.mesh.set_done && !datasets_ready_, "",
       "the coordinates are declared before the mesh is set and before the "
       "first run");
  check_units(units, "coordinates");
  need(axes >= 1 && axes <= 3, "E24", "coordinates have 1 to 3 axes");
  schema_.mesh.coordinate_units = units;
  schema_.mesh.coordinate_dtype_auto = dtype == DType::String;   // String: "as given"
  need(schema_.mesh.coordinate_dtype_auto || is_float(dtype), "E4",
       "coordinates are float32 or float64");
  schema_.mesh.coordinate_dtype = schema_.mesh.coordinate_dtype_auto ? DType::Float64 : dtype;
  schema_.mesh.axes = axes;
}

void Writer::set_constant(const Constant& c) {
  need_open();
  check_new_root_name(c.name);
  check_units(c.units, c.name);
  need(c.dtype == DType::Float32 || c.dtype == DType::Float64 ||
           c.dtype == DType::Int64,
       "E4", c.name + ": a constant is float32, float64 or int64", c.name);
  const std::string p = root(c.name);
  file_->create_dataset(p, c.dtype, 0, {}, {}, {}, {});
  if (c.dtype == DType::Int64) {
    file_->write(p, DType::Int64, {}, {}, &c.i);
  } else if (c.dtype == DType::Float32) {
    const float v = static_cast<float>(c.f);
    file_->write(p, DType::Float32, {}, {}, &v);
  } else {
    file_->write(p, DType::Float64, {}, {}, &c.f);
  }
  file_->write_attr(p, "role", AttrValue::text("constant"));
  file_->write_attr(p, "units", AttrValue::text(c.units));
  schema_.constants.push_back(c);
}

void Writer::set_generalisation_group(const std::string& label) {
  need_open();
  const Label* l = schema_.label(label);
  need(l != nullptr && l->role == "group", "E15",
       "the generalisation group must name a group label, and \"" + label +
           "\" is not one");
  schema_.generalisation_group = label;
  file_->replace_attr("/", "generalisation_group", AttrValue::text(label));
}

void Writer::set_mesh(const Geometry& g) {
  need_open();
  Mesh& m = schema_.mesh;
  need(m.kind == "shared", "",
       "set_mesh is for a shared mesh; a changing mesh takes its geometry with "
       "each run");
  need(!m.set_done, "", "the mesh is already set");
  need(!m.coordinate_units.empty(), "E7",
       "declare the coordinates (units, precision, axes) before set_mesh");
  need(g.axes == m.axes, "E24",
       "the geometry has " + std::to_string(g.axes) +
           " axes and the coordinates were declared with " + std::to_string(m.axes));
  need(g.n_nodes >= 1, "", "a mesh has at least one node");
  if (m.per == "fixed") {
    need(g.points.count == g.n_nodes * g.axes, "E5",
         "coordinates: expected n_nodes x axes values");
    need(is_float(g.points.dtype), "E4", "coordinates are float32 or float64");
  } else {
    need(g.points.count == 0, "",
         "coordinates that change per run or per group come with the runs");
  }
  check_cells(g.types, g.offsets, g.connectivity, g.n_nodes, "the mesh");
  // Everything is checked and converted before anything is written (a
  // refused call adds nothing).
  check_mesh_labels_fixed(g, g.n_nodes, static_cast<std::int64_t>(g.types.size()));
  std::vector<unsigned char> stored_points;
  if (m.per == "fixed") {
    const DType t = m.coordinate_dtype_auto ? g.points.dtype : m.coordinate_dtype;
    stored_points = convert(g.points, t, "coordinates");
    m.coordinate_dtype = t;
    m.coordinate_dtype_auto = false;
  }
  m.n_nodes = g.n_nodes;
  m.n_cells = static_cast<std::int64_t>(g.types.size());
  m.n_conn = static_cast<std::int64_t>(g.connectivity.size());
  File& f = *file_;
  f.make_group("/mesh");
  f.make_scale("/mesh/node", static_cast<hsize_t>(m.n_nodes), false);
  f.make_scale("/mesh/axis", static_cast<hsize_t>(m.axes), false);
  if (m.n_cells > 0) {
    const hsize_t nc = static_cast<hsize_t>(m.n_cells);
    const hsize_t ni = static_cast<hsize_t>(m.n_conn);
    f.make_scale("/mesh/cell", nc, false);
    f.make_scale("/mesh/cell_plus_one", nc + 1, false);
    f.make_scale("/mesh/index", ni, false);
    f.create_dataset("/mesh/cell_types", DType::UInt8, 0, {nc}, {},
                     end_to_end_chunk(1, {}), filters_);
    f.write("/mesh/cell_types", DType::UInt8, {0}, {nc}, g.types.data());
    f.attach_scale("/mesh/cell_types", "/mesh/cell", 0);
    f.create_dataset("/mesh/cell_offsets", DType::Int64, 0, {nc + 1}, {},
                     end_to_end_chunk(8, {}), filters_);
    f.write("/mesh/cell_offsets", DType::Int64, {0}, {nc + 1}, g.offsets.data());
    f.attach_scale("/mesh/cell_offsets", "/mesh/cell_plus_one", 0);
    f.create_dataset("/mesh/cell_connectivity", DType::Int64, 0, {ni}, {},
                     end_to_end_chunk(8, {}), filters_);
    f.write("/mesh/cell_connectivity", DType::Int64, {0}, {ni}, g.connectivity.data());
    f.attach_scale("/mesh/cell_connectivity", "/mesh/index", 0);
  }
  std::vector<double> cloud;
  if (m.n_cells == 0 && m.per == "fixed") {
    // Spec section 14 hashes the stored coordinates, widened to float64.
    Column stored;
    stored.dtype = m.coordinate_dtype;
    stored.count = g.points.count;
    stored.bytes = stored_points;
    const std::vector<unsigned char> b = convert(stored, DType::Float64, "coordinates");
    cloud.resize(b.size() / 8);
    if (!cloud.empty()) std::memcpy(cloud.data(), b.data(), b.size());
  }
  m.support_id = support_id_of(m.n_nodes, g.types, g.offsets, g.connectivity,
                               m.n_cells == 0 && m.per == "fixed" ? &cloud : nullptr);
  f.write_attr("/mesh", "kind", AttrValue::text("shared"));
  f.write_attr("/mesh", "per", AttrValue::text(m.per));
  f.write_attr("/mesh", "support_id", AttrValue::text(m.support_id));
  if (m.per == "fixed") {
    const DType t = m.coordinate_dtype;
    const hsize_t n = static_cast<hsize_t>(m.n_nodes);
    const hsize_t a = static_cast<hsize_t>(m.axes);
    f.create_dataset("/mesh/coordinates", t, 0, {n, a}, {},
                     end_to_end_chunk(dtype_size(t), {a}), filters_);
    f.write("/mesh/coordinates", t, {0, 0}, {n, a}, stored_points.data());
    f.attach_scale("/mesh/coordinates", "/mesh/node", 0);
    f.attach_scale("/mesh/coordinates", "/mesh/axis", 1);
    f.write_attr("/mesh/coordinates", "units", AttrValue::text(m.coordinate_units));
  }
  write_mesh_labels_fixed(g);
  m.set_done = true;
}

void Writer::check_mesh_labels_fixed(const Geometry& g, std::int64_t n_nodes,
                                     std::int64_t n_cells) const {
  const Mesh& m = schema_.mesh;
  for (const auto& ml : m.labels) {
    const auto it = g.labels.find(ml.name);
    const std::string p = mesh_label_path(ml);
    need(it != g.labels.end(), "E2", p + ": the mesh label's values are missing", p);
    need(ml.where == "node" || n_cells > 0, "", p + ": a point cloud has no cells", p);
    const std::size_t len = static_cast<std::size_t>(ml.where == "node" ? n_nodes : n_cells);
    need(it->second.size() == len, "E5", p + ": expected " + std::to_string(len) + " values", p);
    for (const std::int64_t x : it->second) {
      need(x >= INT32_MIN && x <= INT32_MAX, "E4", p + ": a code does not fit in int32", p);
      if (!ml.category.empty()) {
        need(x >= 0 && static_cast<std::size_t>(x) < schema_.tables.at(ml.category).size(), "E9",
             p + ": a code is outside its table", p);
      }
    }
  }
  for (const auto& kv : g.labels) {
    bool known = false;
    for (const auto& ml : m.labels) known = known || ml.name == kv.first;
    need(known, "E2", kv.first + " is given but not declared as a mesh label", kv.first);
  }
}

void Writer::write_mesh_labels_fixed(const Geometry& g) {
  // check_mesh_labels_fixed() has passed.
  const Mesh& m = schema_.mesh;
  File& f = *file_;
  for (const auto& ml : m.labels) {
    const std::vector<std::int64_t>& codes = g.labels.at(ml.name);
    const hsize_t len = static_cast<hsize_t>(codes.size());
    std::vector<std::int32_t> v(codes.size());
    for (std::size_t i = 0; i < v.size(); ++i) v[i] = static_cast<std::int32_t>(codes[i]);
    const std::string p = label_dataset(ml);
    f.create_dataset(p, DType::Int32, 0, {len}, {}, end_to_end_chunk(4, {}), filters_);
    if (len > 0) f.write(p, DType::Int32, {0}, {len}, v.data());
    f.attach_scale(p, ml.where == "node" ? "/mesh/node" : "/mesh/cell", 0);
    if (!ml.category.empty()) f.write_attr(p, "category", AttrValue::text(ml.category));
  }
}

void Writer::create_root_dataset(const std::string& path, DType dtype,
                                 const std::vector<hsize_t>& trailing,
                                 const std::vector<std::string>& trailing_scales) {
  File& f = *file_;
  std::vector<hsize_t> shape = {0}, maxshape = {H5S_UNLIMITED};
  for (const hsize_t t : trailing) {
    shape.push_back(t);
    maxshape.push_back(t);
  }
  const std::vector<hsize_t> chunk = leading_chunk(dtype_size(dtype), trailing);
  f.create_dataset(path, dtype, 0, shape, maxshape, chunk, filters_);
  f.attach_scale(path, "/row", 0);
  for (std::size_t i = 0; i < trailing_scales.size(); ++i) {
    f.attach_scale(path, trailing_scales[i], static_cast<unsigned>(i + 1));
  }
  pending_[path] = make_pending(path, dtype, trailing, chunk[0], 0);
}

void Writer::check_preconditions(Schema& s, const Batch* first) {
  // The structure the first rows need, checked on `s`; nothing here writes.
  const Mesh& m = s.mesh;
  const std::string group = m.per_group();
  if (!group.empty()) {
    const Label* l = s.label(group);
    need(l != nullptr && l->role == "group", "E6", "per = group:" + group + " must name a group label");
  }
  if (m.kind == "shared") {
    need(m.set_done, "", "a shared mesh needs set_mesh before the first run");
    for (const auto& r : s.results) {
      need(r.where != "cell" || m.n_cells > 0, "", r.name + ": a point cloud has no cells",
           r.name);
    }
  } else if (m.kind == "changing") {
    need(m.axes >= 1 && m.axes <= 3 && !m.coordinate_units.empty(), "E24",
         "a changing mesh declares its coordinates (units, precision, axes) before the first run");
    if (m.has_cells < 0) {
      // Whether instances have cells is fixed by the first geometry; without
      // one, by whether cell fields or labels were declared.
      const Geometry* g = nullptr;
      if (first != nullptr && !first->run_geometry.empty()) g = &first->run_geometry[0];
      if (first != nullptr && g == nullptr && !first->member_geometry.empty()) {
        g = &first->member_geometry.begin()->second;
      }
      bool cell_things = false;
      for (const auto& r : s.results) cell_things = cell_things || r.where == "cell";
      for (const auto& ml : m.labels) cell_things = cell_things || ml.where == "cell";
      s.mesh.has_cells = g != nullptr ? (g->types.empty() ? 0 : 1) : (cell_things ? 1 : 0);
    }
    if (s.mesh.has_cells == 0) {
      for (const auto& r : s.results) {
        need(r.where != "cell", "", r.name + ": a changing mesh without cells has no cell fields",
             r.name);
      }
      for (const auto& ml : m.labels) {
        need(ml.where != "cell", "", ml.name + ": a changing mesh without cells has no cell labels",
             ml.name);
      }
    }
  }
}

void Writer::resolve_autos(Schema& s, const Batch* first) {
  // Precision as given (spec section 11.1): what was declared "as given"
  // takes the dtype of the first values written, float64 when there are none.
  auto given = [&](const std::string& name) -> const Column* {
    if (first == nullptr) return nullptr;
    const auto it = first->values.find(name);
    return it == first->values.end() ? nullptr : &it->second;
  };
  for (auto& p : s.parameters) {
    if (!p.auto_dtype) continue;
    const Column* c = given(p.name);
    p.dtype = c != nullptr && is_int(c->dtype) ? DType::Int64 : DType::Float64;
    p.auto_dtype = false;
  }
  for (auto& r : s.results) {
    if (!r.auto_dtype) continue;
    const Column* c = given(r.name);
    r.dtype = c != nullptr && c->dtype == DType::Float32 ? DType::Float32 : DType::Float64;
    r.auto_dtype = false;
    r.given_precision = true;
    need(r.round_bits < 0 || r.round_bits < (r.dtype == DType::Float32 ? 23 : 52), "",
         result_path(r) + ": round_bits keeps 1 to 22 bits of a float32, 1 to 51 of a float64",
         result_path(r));
  }
  Mesh& m = s.mesh;
  if (m.coordinate_dtype_auto) {
    const Geometry* g = nullptr;
    if (first != nullptr && !first->run_geometry.empty()) g = &first->run_geometry[0];
    if (first != nullptr && g == nullptr && !first->member_geometry.empty()) {
      g = &first->member_geometry.begin()->second;
    }
    m.coordinate_dtype = g != nullptr && g->points.dtype == DType::Float32 ? DType::Float32
                                                                           : DType::Float64;
    m.coordinate_dtype_auto = false;
  }
}

void Writer::ensure_datasets(const Batch* first) {
  if (datasets_ready_) return;
  check_relations();
  check_preconditions(schema_, first);
  resolve_autos(schema_, first);
  File& f = *file_;
  Schema& s = schema_;
  Mesh& m = s.mesh;
  for (const auto& kv : s.tables) write_table(f, kv.first, kv.second, filters_);
  for (const auto& p : s.parameters) {
    const std::string path = root(p.name);
    create_root_dataset(path, p.dtype, {}, {});
    f.write_attr(path, "role", AttrValue::text(p.role));
    f.write_attr(path, "units", AttrValue::text(p.units));
    if (p.lower) f.write_attr(path, "lower", AttrValue::real(*p.lower));
    if (p.upper) f.write_attr(path, "upper", AttrValue::real(*p.upper));
    if (!p.run_group.empty()) f.write_attr(path, "run_group", AttrValue::text(p.run_group));
  }
  for (const auto& l : s.labels) {
    const std::string path = root(l.name);
    create_root_dataset(path, l.dtype, {}, {});
    f.write_attr(path, "role", AttrValue::text(l.role));
    f.write_attr(path, "category", AttrValue::text(l.category));
  }
  auto write_result_attrs = [&](const std::string& path, const Result& r) {
    if (r.where == "scalar") f.write_attr(path, "role", AttrValue::text("scalar"));
    f.write_attr(path, "units", AttrValue::text(r.units));
    const Relation& rel = r.relation;
    if (!rel.of.empty()) f.write_attr(path, "of", AttrValue::text(rel.of));
    if (!rel.statistic.empty()) f.write_attr(path, "statistic", AttrValue::text(rel.statistic));
    if (rel.q) f.write_attr(path, "q", AttrValue::real(*rel.q));
    if (!rel.method.empty()) f.write_attr(path, "method", AttrValue::text(rel.method));
    if (!rel.with_respect_to.empty()) {
      f.write_attr(path, "with_respect_to", AttrValue::text(rel.with_respect_to));
    }
    const std::string axis = !rel.axis.empty() ? rel.axis : r.axis;
    if (!axis.empty()) f.write_attr(path, "axis", AttrValue::text(axis));
    if (!r.vector.empty()) f.write_attr(path, "vector", AttrValue::text(r.vector));
    if (!r.model.empty()) f.write_attr(path, "model", AttrValue::text(r.model));
    if (!r.output.empty()) f.write_attr(path, "output", AttrValue::text(r.output));
    if (r.round_bits >= 0) {
      f.write_attr(path, "_QuantizeBitRoundNumberOfSignificantBits",
                   AttrValue::integer(r.round_bits));
    }
  };
  for (const auto& r : s.results) {
    if (r.where != "scalar") continue;
    create_root_dataset(root(r.name), r.dtype, {}, {});
    write_result_attrs(root(r.name), r);
  }
  const std::string group = m.per_group();
  if (m.kind == "shared") {
    const hsize_t n = static_cast<hsize_t>(m.n_nodes);
    const hsize_t a = static_cast<hsize_t>(m.axes);
    const DType t = m.coordinate_dtype;
    if (m.per == "run") {
      create_root_dataset("/mesh/coordinates", t, {n, a}, {"/mesh/node", "/mesh/axis"});
    } else if (!group.empty()) {
      f.make_scale("/mesh/instance", 0, true);
      const std::vector<hsize_t> chunk = leading_chunk(dtype_size(t), {n, a});
      f.create_dataset("/mesh/coordinates", t, 0, {0, n, a}, {H5S_UNLIMITED, n, a}, chunk,
                       filters_);
      f.attach_scale("/mesh/coordinates", "/mesh/instance", 0);
      f.attach_scale("/mesh/coordinates", "/mesh/node", 1);
      f.attach_scale("/mesh/coordinates", "/mesh/axis", 2);
      pending_["/mesh/coordinates"] = make_pending("/mesh/coordinates", t, {n, a}, chunk[0], 0);
      create_root_dataset("/mesh/row_instance", DType::Int64, {}, {});
    }
    if (m.per != "fixed") {
      f.write_attr("/mesh/coordinates", "units", AttrValue::text(m.coordinate_units));
      if (!m.coordinate_model.empty()) {
        f.write_attr("/mesh/coordinates", "model", AttrValue::text(m.coordinate_model));
        f.write_attr("/mesh/coordinates", "output", AttrValue::text(m.coordinate_output));
      }
    }
    for (const auto& r : s.results) {
      if (r.where == "scalar") continue;
      const hsize_t len = static_cast<hsize_t>(r.where == "node" ? m.n_nodes : m.n_cells);
      create_root_dataset(field_path(r), r.dtype, {len},
                          {r.where == "node" ? "/mesh/node" : "/mesh/cell"});
      write_result_attrs(field_path(r), r);
    }
  } else if (m.kind == "changing") {
    f.make_group("/mesh");
    const bool cells = m.has_cells == 1;
    for (const char* sc : {"/mesh/instance_plus_one", "/mesh/node", "/mesh/node_value"}) {
      f.make_scale(sc, 0, true);
    }
    if (cells) {
      for (const char* sc : {"/mesh/cell", "/mesh/cell_plus_one", "/mesh/index", "/mesh/cell_value"}) {
        f.make_scale(sc, 0, true);
      }
    }
    f.make_scale("/mesh/axis", static_cast<hsize_t>(m.axes), false);
    auto end_to_end = [&](const std::string& path, DType t,
                          const std::vector<hsize_t>& trailing,
                          const std::string& scale,
                          const std::vector<std::string>& more) {
      std::vector<hsize_t> shape = {0}, maxshape = {H5S_UNLIMITED};
      for (const hsize_t x : trailing) {
        shape.push_back(x);
        maxshape.push_back(x);
      }
      const std::vector<hsize_t> chunk = end_to_end_chunk(dtype_size(t), trailing);
      f.create_dataset(path, t, 0, shape, maxshape, chunk, filters_);
      f.attach_scale(path, scale, 0);
      for (std::size_t i = 0; i < more.size(); ++i) {
        f.attach_scale(path, more[i], static_cast<unsigned>(i + 1));
      }
      pending_[path] = make_pending(path, t, trailing, chunk[0], 0);
    };
    end_to_end("/mesh/instance_nodes", DType::Int64, {}, "/mesh/instance_plus_one", {});
    if (cells) end_to_end("/mesh/instance_cells", DType::Int64, {}, "/mesh/instance_plus_one", {});
    end_to_end("/mesh/coordinates", m.coordinate_dtype, {static_cast<hsize_t>(m.axes)},
               "/mesh/node", {"/mesh/axis"});
    f.write_attr("/mesh/coordinates", "units", AttrValue::text(m.coordinate_units));
    if (cells) {
      end_to_end("/mesh/cell_types", DType::UInt8, {}, "/mesh/cell", {});
      end_to_end("/mesh/cell_offsets", DType::Int64, {}, "/mesh/cell_plus_one", {});
      end_to_end("/mesh/cell_connectivity", DType::Int64, {}, "/mesh/index", {});
    }
    for (const auto& ml : m.labels) {
      const std::string p = label_dataset(ml);
      end_to_end(p, DType::Int32, {}, ml.where == "node" ? "/mesh/node" : "/mesh/cell", {});
      if (!ml.category.empty()) f.write_attr(p, "category", AttrValue::text(ml.category));
    }
    if (!group.empty()) create_root_dataset("/mesh/row_instance", DType::Int64, {}, {});
    create_root_dataset("/mesh/row_node_start", DType::Int64, {}, {});
    if (cells) create_root_dataset("/mesh/row_cell_start", DType::Int64, {}, {});
    for (const auto& r : s.results) {
      if (r.where == "scalar") continue;
      end_to_end(field_path(r), r.dtype, {},
                 r.where == "node" ? "/mesh/node_value" : "/mesh/cell_value", {});
      write_result_attrs(field_path(r), r);
    }
    const std::int64_t zero = 0;
    const auto* z = reinterpret_cast<const unsigned char*>(&zero);
    append_rows("/mesh/instance_nodes", z, 1, DType::Int64);
    if (cells) {
      append_rows("/mesh/instance_cells", z, 1, DType::Int64);
      append_rows("/mesh/cell_offsets", z, 1, DType::Int64);
    }
    f.write_attr("/mesh", "kind", AttrValue::text("changing"));
    f.write_attr("/mesh", "per", AttrValue::text(m.per));
    m.set_done = true;
  }
  datasets_ready_ = true;
}

void Writer::append_rows(const std::string& path, const unsigned char* data,
                         std::int64_t rows, DType mem) {
  if (rows == 0) return;
  auto it = pending_.find(path);
  need(it != pending_.end(), "", "internal: no pending state for " + path);
  Pending& p = *it->second;
  need(mem == p.dtype, "", "internal: dtype mismatch for " + path);
  const std::size_t bytes = static_cast<std::size_t>(rows) * p.entry_bytes;
  p.buffer.insert(p.buffer.end(), data, data + bytes);
  p.buffered += rows;
  File& f = *file_;
  while (p.buffered > 0) {
    const std::int64_t c = static_cast<std::int64_t>(p.chunk_rows);
    const std::int64_t boundary = (p.on_disk / c + 1) * c;
    const std::int64_t want = boundary - p.on_disk;
    if (p.buffered < want) break;
    std::vector<hsize_t> shape = {static_cast<hsize_t>(p.on_disk + want)};
    std::vector<hsize_t> start = {static_cast<hsize_t>(p.on_disk)};
    std::vector<hsize_t> count = {static_cast<hsize_t>(want)};
    for (const hsize_t t : p.trailing) {
      shape.push_back(t);
      start.push_back(0);
      count.push_back(t);
    }
    f.set_extent(p.path, shape);
    f.write(p.path, p.dtype, start, count, p.buffer.data());
    const std::size_t done = static_cast<std::size_t>(want) * p.entry_bytes;
    p.buffer.erase(p.buffer.begin(), p.buffer.begin() + static_cast<std::ptrdiff_t>(done));
    p.buffered -= want;
    p.on_disk += want;
  }
}

std::int64_t Writer::code_of(const std::string& table, const std::string& name,
                             std::vector<std::string>* added) const {
  const auto& entries = schema_.tables.at(table);
  for (std::size_t i = 0; i < entries.size(); ++i) {
    if (entries[i] == name) return static_cast<std::int64_t>(i);
  }
  for (std::size_t i = 0; i < added->size(); ++i) {
    if ((*added)[i] == name) return static_cast<std::int64_t>(entries.size() + i);
  }
  need(valid_utf8(name), "E4", table + ": a name is not valid UTF-8", table);
  added->push_back(name);
  return static_cast<std::int64_t>(entries.size() + added->size() - 1);
}

void Writer::grow_table(const std::string& table, const std::vector<std::string>& added) {
  if (added.empty()) return;
  File& f = *file_;
  std::vector<std::string>& entries = schema_.tables[table];
  const std::string path = "/categories/" + table;
  const std::string scale = "/category_" + table;
  const DsetInfo info = f.dataset_info(path, false);
  std::size_t width = info.type.size;
  bool wider = false;
  for (const auto& a : added) {
    if (a.size() > width) {
      width = a.size();
      wider = true;
    }
  }
  const std::size_t old = entries.size();
  entries.insert(entries.end(), added.begin(), added.end());
  f.set_scale_length(scale, entries.size());
  if (wider) {
    // A wider string type is a new dataset: detach, delete, recreate,
    // reattach (spec section 11.5).
    f.detach_scale(path, scale, 0);
    f.remove_link(path);
    f.create_dataset(path, DType::String, width, {entries.size()}, {H5S_UNLIMITED},
                     table_chunk(width), filters_);
    f.write_strings(path, 0, entries);
    f.attach_scale(path, scale, 0);
  } else {
    f.set_extent(path, {entries.size()});
    f.write_strings(path, old, added);
  }
}

void Writer::check_relations() const {
  const Schema& s = schema_;
  for (const auto& r : s.results) {
    const std::string path = result_path(r);
    const Relation& rel = r.relation;
    if (!rel.of.empty()) {
      const Result* t = nullptr;
      for (const auto& c : s.results) {
        if (c.name == rel.of) t = &c;
      }
      need(t != nullptr, "E12", path + ": of names \"" + rel.of + "\", which is not a result",
           path);
      need(t->relation.statistic.empty() && t->relation.with_respect_to.empty(), "E12",
           path + ": of names a relation", path);
      if (rel.with_respect_to == "coordinates") {
        need(r.where == "node" && t->where == "scalar", "E12",
             path + ": a derivative with respect to node position is a node field "
                    "whose of is a scalar",
             path);
      } else {
        need(t->where == r.where, "E12",
             path + ": a relation has the location of its of (" + t->where + ")", path);
      }
      if (rel.statistic == "std" || rel.statistic == "quantile") {
        need(t->units == r.units, "E12",
             path + ": a " + rel.statistic + " has the units of its result (" + t->units + ")",
             path);
      }
    }
    if (!rel.with_respect_to.empty() && rel.with_respect_to != "coordinates") {
      need(s.parameter(rel.with_respect_to) != nullptr, "E12",
           path + ": with_respect_to names \"" + rel.with_respect_to +
               "\", which is not a parameter",
           path);
    }
  }
  std::map<std::string, std::vector<const Result*>> vectors;
  for (const auto& r : s.results) {
    if (!r.vector.empty()) vectors[r.vector].push_back(&r);
  }
  for (const auto& kv : vectors) {
    std::set<std::string> axes;
    for (const Result* r : kv.second) {
      need(r->where == kv.second[0]->where && r->units == kv.second[0]->units, "E13",
           "vector " + kv.first + ": its fields differ in location or units");
      need(axes.insert(r->axis).second, "E13",
           "vector " + kv.first + ": two fields claim axis " + r->axis);
      const int index = r->axis == "x" ? 0 : (r->axis == "y" ? 1 : 2);
      need(index < s.mesh.axes, "E13",
           "vector " + kv.first + ": axis " + r->axis + " is not among the coordinates' axes");
    }
  }
  for (const auto& p : s.parameters) {
    if (p.run_group.empty()) continue;
    const Label* l = s.label(p.run_group);
    need(l != nullptr && l->role == "group", "E15",
         p.name + ": run_group must name a group label", p.name);
  }
}

std::int64_t Writer::add_runs(const Batch& batch) {
  need_open();
  need(!model_, "E16", "a model file has no runs; evaluate it to get a data file");
  // Before the first rows, the declarations are resolved against this batch
  // (precisions as given, whether a changing mesh has cells) on the schema,
  // and put back if the batch is refused: a refused call adds nothing.
  struct Restore {
    Writer* w;
    std::vector<Parameter> parameters;
    std::vector<Result> results;
    Mesh mesh;
    bool active = false;
    ~Restore() {
      if (active) {
        w->schema_.parameters = parameters;
        w->schema_.results = results;
        w->schema_.mesh = mesh;
      }
    }
  } restore{this, {}, {}, {}, false};
  if (!datasets_ready_) {
    check_relations();
    restore.parameters = schema_.parameters;
    restore.results = schema_.results;
    restore.mesh = schema_.mesh;
    restore.active = true;
    check_preconditions(schema_, &batch);
    resolve_autos(schema_, &batch);
  }
  const Schema& s = schema_;
  const Mesh& m = s.mesh;
  const std::int64_t n = batch.runs;
  need(n >= 0, "", "a batch has zero or more runs");
  if (n == 0) return next_id_;
  const std::size_t N = static_cast<std::size_t>(n);
  // --- check everything before writing anything --------------------------
  std::set<std::string> known;
  std::map<std::string, std::vector<unsigned char>> root_bytes;
  for (const auto& p : s.parameters) {
    known.insert(p.name);
    const auto it = batch.values.find(p.name);
    need(it != batch.values.end(), "E2", p.name + ": every run needs a value", p.name);
    need(it->second.count == n, "E5",
         p.name + ": expected " + std::to_string(n) + " values", p.name);
    root_bytes[p.name] = convert(it->second, p.dtype, p.name);
    if (p.dtype == DType::Float64) {
      for (std::size_t i = 0; i < N; ++i) {
        double v;
        std::memcpy(&v, &root_bytes[p.name][i * 8], 8);
        need(!std::isnan(v), "E5", p.name + ": a parameter is never missing", p.name);
      }
    }
  }
  std::map<std::string, std::vector<std::string>> added;
  std::map<std::string, std::vector<std::int64_t>> codes;
  for (const auto& l : s.labels) {
    known.insert(l.name);
    std::vector<std::int64_t>& c = codes[l.name];
    const auto byname = batch.names.find(l.name);
    const auto bycode = batch.values.find(l.name);
    need(!(byname != batch.names.end() && bycode != batch.values.end()), "",
         l.name + ": give names or codes, not both", l.name);
    if (byname != batch.names.end()) {
      need(byname->second.size() == N, "E5",
           l.name + ": expected " + std::to_string(n) + " names", l.name);
      for (const auto& nm : byname->second) c.push_back(code_of(l.category, nm, &added[l.category]));
    } else {
      need(bycode != batch.values.end(), "E2", l.name + ": every run needs a value", l.name);
      need(bycode->second.count == n, "E5",
           l.name + ": expected " + std::to_string(n) + " codes", l.name);
      c = as_i64(bycode->second, l.name);
      const std::int64_t size = static_cast<std::int64_t>(s.tables.at(l.category).size());
      for (const std::int64_t v : c) {
        need(v >= 0 && v < size, "E9",
             l.name + ": code " + std::to_string(v) + " is outside its table", l.name);
      }
    }
  }
  for (const auto& r : s.results) {
    if (r.where != "scalar") continue;
    known.insert(r.name);
    const auto it = batch.values.find(r.name);
    if (it == batch.values.end()) {
      const std::vector<double> nan(N, std::nan(""));
      root_bytes[r.name] = convert(Column::of(DType::Float64, nan.data(), n), r.dtype, r.name);
    } else {
      need(it->second.count == n, "E5",
           r.name + ": expected " + std::to_string(n) + " values", r.name);
      need(!(r.given_precision && r.dtype == DType::Float32 && it->second.dtype == DType::Float64),
           "E4", r.name + ": its first values were float32, so it is stored as float32; give "
                          "float32 values, or declare its precision to convert",
           r.name);
      root_bytes[r.name] = convert(it->second, r.dtype, r.name);
    }
    bitround(&root_bytes[r.name], r.dtype, r.round_bits);
  }
  // --- instances (spec sections 4.2 and 5) ----------------------------------
  const std::string group = m.per_group();
  std::vector<std::int64_t> instance_of(N, 0);
  std::vector<const Geometry*> new_geometry;     // in instance order
  if (!group.empty()) {
    const Label* gl = s.label(group);
    const auto& entries = s.tables.at(gl->category);
    const auto& more = added[gl->category];
    std::map<std::int64_t, std::int64_t> fresh;
    for (std::size_t i = 0; i < N; ++i) {
      const std::int64_t code = codes.at(group)[i];
      const auto known_it = member_instance_.find(code);
      if (known_it != member_instance_.end()) {
        instance_of[i] = known_it->second;
        continue;
      }
      const auto fresh_it = fresh.find(code);
      if (fresh_it != fresh.end()) {
        instance_of[i] = fresh_it->second;
        continue;
      }
      const std::int64_t inst = instances_written_ + static_cast<std::int64_t>(fresh.size());
      fresh[code] = inst;
      instance_of[i] = inst;
      const std::string nm = code < static_cast<std::int64_t>(entries.size())
                                 ? entries[static_cast<std::size_t>(code)]
                                 : more[static_cast<std::size_t>(code) - entries.size()];
      const auto g = batch.member_geometry.find(nm);
      need(g != batch.member_geometry.end(), "E2",
           "the " + group + " \"" + nm + "\" appears for the first time and needs its geometry",
           group);
      new_geometry.push_back(&g->second);
    }
    for (const auto& kv : batch.member_geometry) {
      bool used = false;
      for (const Geometry* g : new_geometry) used = used || g == &kv.second;
      need(used, "", "geometry was given for \"" + kv.first + "\", which is not new in this batch");
    }
    need(batch.run_geometry.empty(), "",
         "a mesh that changes per group takes geometry by group, not per run");
  } else if (m.per == "run") {
    need(batch.run_geometry.size() == N, "E2",
         "a mesh that changes per run needs one geometry per run");
    need(batch.member_geometry.empty(), "", "a mesh that changes per run takes geometry per run");
    for (std::size_t i = 0; i < N; ++i) {
      instance_of[i] = instances_written_ + static_cast<std::int64_t>(i);
      new_geometry.push_back(&batch.run_geometry[i]);
    }
  } else {
    need(batch.run_geometry.empty() && batch.member_geometry.empty(), "",
         "this file's geometry does not change; give no geometry with the runs");
  }
  for (std::size_t k = 0; k < new_geometry.size(); ++k) {
    const Geometry& g = *new_geometry[k];
    const std::string who =
        "geometry " + std::to_string(instances_written_ + static_cast<std::int64_t>(k));
    need(is_float(g.points.dtype), "E4", who + ": coordinates are float32 or float64");
    if (m.kind == "shared") {
      need(g.n_nodes == m.n_nodes && g.axes == m.axes && g.points.count == m.n_nodes * m.axes,
           "E5", who + ": coordinates must be " + std::to_string(m.n_nodes) + " nodes x " +
                     std::to_string(m.axes) + " axes");
      need(g.types.empty() && g.offsets.empty() && g.connectivity.empty() && g.labels.empty(),
           "", who + ": a shared mesh keeps its cells and mesh labels; give coordinates only");
    } else {
      need(g.axes == m.axes && g.n_nodes >= 1 && g.points.count == g.n_nodes * g.axes, "E5",
           who + ": coordinates must be n_nodes x " + std::to_string(m.axes) + " axes");
      // Whether a changing mesh has cells is fixed by its first instance.
      need((g.types.empty() ? 0 : 1) == m.has_cells, "",
           who + (m.has_cells == 1 ? ": this mesh's instances have cells; give them"
                                   : ": this mesh's instances have no cells"));
      check_cells(g.types, g.offsets, g.connectivity, g.n_nodes, who);
      for (const auto& ml : m.labels) {
        const auto it = g.labels.find(ml.name);
        const std::string p = mesh_label_path(ml);
        need(it != g.labels.end(), "E2", who + ": mesh label " + ml.name + " missing", p);
        const std::int64_t len =
            ml.where == "node" ? g.n_nodes : static_cast<std::int64_t>(g.types.size());
        need(static_cast<std::int64_t>(it->second.size()) == len, "E5",
             who + ": mesh label " + ml.name + " expects " + std::to_string(len) + " values", p);
        for (const std::int64_t v : it->second) {
          need(v >= INT32_MIN && v <= INT32_MAX, "E4",
               who + ": a mesh-label code does not fit in int32", p);
          if (!ml.category.empty()) {
            need(v >= 0 && v < static_cast<std::int64_t>(s.tables.at(ml.category).size()), "E9",
                 who + ": mesh label " + ml.name + " has a code outside its table", p);
          }
        }
      }
    }
  }
  std::vector<std::int64_t> inst_nodes(N, m.n_nodes), inst_cells(N, m.n_cells);
  if (m.kind == "changing") {
    for (std::size_t i = 0; i < N; ++i) {
      const std::int64_t k = instance_of[i];
      if (k < instances_written_) {
        inst_nodes[i] = instance_nodes_[static_cast<std::size_t>(k)];
        inst_cells[i] = instance_cells_[static_cast<std::size_t>(k)];
      } else {
        const Geometry& g = *new_geometry[static_cast<std::size_t>(k - instances_written_)];
        inst_nodes[i] = g.n_nodes;
        inst_cells[i] = static_cast<std::int64_t>(g.types.size());
      }
    }
  }
  std::map<std::string, std::vector<unsigned char>> field_bytes;
  for (const auto& r : s.results) {
    if (r.where == "scalar") continue;
    known.insert(r.name);
    std::int64_t expected = 0;
    for (std::size_t i = 0; i < N; ++i) expected += r.where == "node" ? inst_nodes[i] : inst_cells[i];
    const auto it = batch.values.find(r.name);
    if (it == batch.values.end()) {
      const std::vector<double> nan(static_cast<std::size_t>(expected), std::nan(""));
      field_bytes[r.name] =
          convert(Column::of(DType::Float64, nan.data(), expected), r.dtype, r.name);
    } else {
      need(it->second.count == expected, "E5",
           result_path(r) + ": expected " + std::to_string(expected) + " values", result_path(r));
      need(!(r.given_precision && r.dtype == DType::Float32 && it->second.dtype == DType::Float64),
           "E4", result_path(r) + ": its first values were float32, so it is stored as float32; "
                                  "give float32 values, or declare its precision to convert",
           result_path(r));
      field_bytes[r.name] = convert(it->second, r.dtype, result_path(r));
    }
    bitround(&field_bytes[r.name], r.dtype, r.round_bits);
  }
  for (const auto& kv : batch.values) {
    need(known.count(kv.first) == 1, "E2", kv.first + " is given but not declared", kv.first);
  }
  for (const auto& kv : batch.names) {
    need(s.label(kv.first) != nullptr, "E2", kv.first + " is given by name but is not a label",
         kv.first);
  }
  // --- write -----------------------------------------------------------------
  if (!datasets_ready_) {
    restore.active = false;
    ensure_datasets(nullptr);
  }
  for (const auto& kv : added) grow_table(kv.first, kv.second);
  std::vector<std::int64_t> ids(N);
  for (std::size_t i = 0; i < N; ++i) ids[i] = next_id_ + static_cast<std::int64_t>(i);
  append_rows("/row", reinterpret_cast<const unsigned char*>(ids.data()), n, DType::Int64);
  for (const auto& p : s.parameters) append_rows(root(p.name), root_bytes[p.name].data(), n, p.dtype);
  for (const auto& l : s.labels) {
    std::vector<std::int32_t> v(N);
    for (std::size_t i = 0; i < N; ++i) v[i] = static_cast<std::int32_t>(codes[l.name][i]);
    append_rows(root(l.name), reinterpret_cast<const unsigned char*>(v.data()), n, DType::Int32);
  }
  for (const auto& r : s.results) {
    if (r.where == "scalar") append_rows(root(r.name), root_bytes[r.name].data(), n, r.dtype);
  }
  for (const Geometry* gp : new_geometry) {
    const Geometry& g = *gp;
    const std::vector<unsigned char> b = convert(g.points, m.coordinate_dtype, "coordinates");
    if (m.kind == "shared") {
      append_rows("/mesh/coordinates", b.data(), 1, m.coordinate_dtype);
    } else {
      const std::int64_t base =
          m.has_cells == 1 ? pending_.at("/mesh/cell_connectivity")->total() : 0;
      std::vector<std::int64_t> offs;
      if (!g.offsets.empty()) offs.assign(g.offsets.begin() + 1, g.offsets.end());
      for (auto& o : offs) o += base;
      append_rows("/mesh/coordinates", b.data(), g.n_nodes, m.coordinate_dtype);
      for (const auto& ml : m.labels) {
        const auto& vals = g.labels.at(ml.name);
        std::vector<std::int32_t> v(vals.size());
        for (std::size_t i = 0; i < v.size(); ++i) v[i] = static_cast<std::int32_t>(vals[i]);
        append_rows(label_dataset(ml), reinterpret_cast<const unsigned char*>(v.data()),
                    static_cast<std::int64_t>(v.size()), DType::Int32);
      }
      const std::int64_t total_nodes = pending_.at("/mesh/coordinates")->total();
      append_rows("/mesh/instance_nodes", reinterpret_cast<const unsigned char*>(&total_nodes), 1,
                  DType::Int64);
      if (m.has_cells == 1) {
        append_rows("/mesh/cell_types", g.types.data(), static_cast<std::int64_t>(g.types.size()),
                    DType::UInt8);
        append_rows("/mesh/cell_offsets", reinterpret_cast<const unsigned char*>(offs.data()),
                    static_cast<std::int64_t>(offs.size()), DType::Int64);
        append_rows("/mesh/cell_connectivity",
                    reinterpret_cast<const unsigned char*>(g.connectivity.data()),
                    static_cast<std::int64_t>(g.connectivity.size()), DType::Int64);
        const std::int64_t total_cells = pending_.at("/mesh/cell_types")->total();
        append_rows("/mesh/instance_cells", reinterpret_cast<const unsigned char*>(&total_cells), 1,
                    DType::Int64);
      }
      instance_nodes_.push_back(g.n_nodes);
      instance_cells_.push_back(static_cast<std::int64_t>(g.types.size()));
    }
    ++instances_written_;
  }
  if (!group.empty()) {
    append_rows("/mesh/row_instance", reinterpret_cast<const unsigned char*>(instance_of.data()), n,
                DType::Int64);
    for (std::size_t i = 0; i < N; ++i) member_instance_.emplace(codes.at(group)[i], instance_of[i]);
  }
  if (m.kind == "changing") {
    std::vector<std::int64_t> ns(N), cs(N);
    for (std::size_t i = 0; i < N; ++i) {
      ns[i] = node_values_;
      cs[i] = cell_values_;
      node_values_ += inst_nodes[i];
      cell_values_ += inst_cells[i];
    }
    append_rows("/mesh/row_node_start", reinterpret_cast<const unsigned char*>(ns.data()), n,
                DType::Int64);
    if (m.has_cells == 1) {
      append_rows("/mesh/row_cell_start", reinterpret_cast<const unsigned char*>(cs.data()), n,
                  DType::Int64);
    }
  }
  for (const auto& r : s.results) {
    if (r.where == "scalar") continue;
    const std::int64_t rows =
        m.kind == "shared"
            ? n
            : static_cast<std::int64_t>(field_bytes[r.name].size() / dtype_size(r.dtype));
    append_rows(field_path(r), field_bytes[r.name].data(), rows, r.dtype);
  }
  const std::int64_t first = next_id_;
  next_id_ += n;
  schema_.rows += n;
  schema_.mesh.n_instances = instances_written_;
  return first;
}

void Writer::add_model(const std::string& id, const std::string& type,
                       const std::vector<std::string>& inputs, const Dict& numbers,
                       const std::string& repr) {
  need_open();
  need(model_, "E16", "models belong to model files (mestra.create_model)");
  need(legal_netcdf_name(id) && !reserved_name(id), "E8", "\"" + id + "\" is not a legal model id");
  for (const auto& m : schema_.models) {
    need(m.id != id, "E8", "a model called \"" + id + "\" already exists");
  }
  need(!type.empty(), "E17", id + ": a model names its type");
  need(!inputs.empty(), "E17", id + ": a model lists the inputs it reads");
  std::set<std::string> seen;
  for (const auto& in : inputs) {
    need(seen.insert(in).second, "E17", id + ": the input " + in + " is listed twice");
    need(in == "coordinates" ? !schema_.mesh.kind.empty()
                             : (schema_.parameter(in) != nullptr || schema_.label(in) != nullptr),
         "E17", id + ": the input \"" + in + "\" is not a parameter, a label or coordinates");
  }
  if (type == "nearest") {
    const Nearest nm = nearest_from(numbers);
    std::set<std::string> want(inputs.begin(), inputs.end());
    std::set<std::string> have(nm.columns.begin(), nm.columns.end());
    need(want == have, "E17", id + ": a nearest model's columns are exactly its inputs");
    for (std::size_t j = 0; j < nm.columns.size(); ++j) {
      const Parameter* p = schema_.parameter(nm.columns[j]);
      need(p != nullptr, "E17", id + ": a nearest model reads parameters only");
      need(p->lower && *p->lower == nm.lower[j] && *p->upper == nm.upper[j], "E17",
           id + ": a nearest model's bounds equal its parameters' bounds (" + nm.columns[j] + ")");
    }
  }
  const std::string group = "/models/" + id;
  file_->make_group(group);
  file_->write_attr(group, "type", AttrValue::text(type));
  std::string joined;
  for (const auto& in : inputs) joined += (joined.empty() ? "" : " ") + in;
  file_->write_attr(group, "inputs", AttrValue::text(joined));
  if (!repr.empty()) file_->write_attr(group, "repr", AttrValue::text(repr));
  write_dict_group(*file_, group, numbers, true);
  Model m;
  m.id = id;
  m.type = type;
  m.inputs = inputs;
  m.repr = repr;
  schema_.models.push_back(m);
}

void Writer::flush() {
  if (closed_ || !file_) return;
  File& f = *file_;
  for (auto& kv : pending_) {
    Pending& p = *kv.second;
    if (p.buffered == 0) continue;
    std::vector<hsize_t> shape = {static_cast<hsize_t>(p.total())};
    std::vector<hsize_t> start = {static_cast<hsize_t>(p.on_disk)};
    std::vector<hsize_t> count = {static_cast<hsize_t>(p.buffered)};
    for (const hsize_t t : p.trailing) {
      shape.push_back(t);
      start.push_back(0);
      count.push_back(t);
    }
    f.set_extent(p.path, shape);
    f.write(p.path, p.dtype, start, count, p.buffer.data());
    p.on_disk += p.buffered;
    p.buffered = 0;
    p.buffer.clear();
  }
  // Scales whose lengths follow the data (spec section 9.4).
  const Mesh& m = schema_.mesh;
  if (datasets_ready_ && m.kind == "shared" && !m.per_group().empty()) {
    f.set_scale_length("/mesh/instance", static_cast<hsize_t>(instances_written_));
  }
  if (datasets_ready_ && m.kind == "changing") {
    auto len = [&](const std::string& p) {
      const DsetInfo i = f.dataset_info(p, false);
      return i.shape.empty() ? hsize_t(0) : i.shape[0];
    };
    f.set_scale_length("/mesh/instance_plus_one", len("/mesh/instance_nodes"));
    f.set_scale_length("/mesh/node", len("/mesh/coordinates"));
    f.set_scale_length("/mesh/node_value", static_cast<hsize_t>(node_values_));
    if (m.has_cells == 1) {
      f.set_scale_length("/mesh/cell", len("/mesh/cell_types"));
      f.set_scale_length("/mesh/cell_plus_one", len("/mesh/cell_offsets"));
      f.set_scale_length("/mesh/index", len("/mesh/cell_connectivity"));
      f.set_scale_length("/mesh/cell_value", static_cast<hsize_t>(cell_values_));
    }
  }
  f.flush();
}

void Writer::write_cf_coordinates() {
  std::vector<std::string> names;
  for (const auto& p : schema_.parameters) names.push_back(p.name);
  for (const auto& l : schema_.labels) names.push_back(l.name);
  std::sort(names.begin(), names.end(), bytes_less);
  std::string joined;
  for (const auto& nm : names) joined += (joined.empty() ? "" : " ") + nm;
  if (joined.empty()) return;
  for (const auto& r : schema_.results) {
    if (r.where == "scalar") file_->replace_attr(root(r.name), "coordinates", AttrValue::text(joined));
  }
}

void Writer::abandon(bool remove) {
  if (closed_) return;
  closed_ = true;
  pending_.clear();
  file_.reset();
  if (remove && created_) std::remove(path_.c_str());
}

void Writer::close() {
  if (closed_) return;
  ensure_datasets(nullptr);
  if (model_) {
    need(!schema_.models.empty(), "E16", "a model file holds at least one model; add one with "
                                         "add_model before closing");
    auto has = [&](const std::string& id) {
      for (const auto& m : schema_.models) {
        if (m.id == id) return true;
      }
      return false;
    };
    for (const auto& r : schema_.results) {
      need(has(r.model), "E17", result_path(r) + ": names the model \"" + r.model +
                                    "\", which was never added");
    }
    if (!schema_.mesh.coordinate_model.empty()) {
      need(has(schema_.mesh.coordinate_model), "E17", "coordinates: name a model that was added");
    }
  }
  flush();
  write_cf_coordinates();
  file_->flush();
  file_.reset();
  closed_ = true;
}

}  // namespace internal
}  // namespace mestra
