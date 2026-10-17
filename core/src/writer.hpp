// Writing data files (spec sections 3 to 5, 10, 11): create, declare,
// then add runs, which go to disk in whole chunks as they arrive.
#ifndef MESTRA_CORE_WRITER_HPP
#define MESTRA_CORE_WRITER_HPP

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "h5.hpp"
#include "schema.hpp"
#include "types.hpp"

namespace mestra {
namespace internal {

// A typed column of values: `count` elements of `dtype`, packed.
struct Column {
  DType dtype = DType::Float64;
  std::vector<unsigned char> bytes;
  std::int64_t count = 0;

  template <class T>
  static Column of(DType t, const T* values, std::int64_t n) {
    Column c;
    c.dtype = t;
    c.count = n;
    const auto* p = reinterpret_cast<const unsigned char*>(values);
    c.bytes.assign(p, p + static_cast<std::size_t>(n) * sizeof(T));
    return c;
  }
};

// One geometry: node positions, and for a changing mesh its cells and
// mesh labels.
struct Geometry {
  Column points;                  // n_nodes x axes
  std::int64_t n_nodes = 0;
  int axes = 0;
  std::vector<std::uint8_t> types;
  std::vector<std::int64_t> offsets;     // n_cells + 1
  std::vector<std::int64_t> connectivity;
  std::map<std::string, std::vector<std::int64_t>> labels;   // by path
};

// Runs staged for one commit: all or nothing.
struct Batch {
  std::int64_t runs = 0;
  std::map<std::string, Column> values;                  // by name or path
  std::map<std::string, std::vector<std::string>> names;  // labels by name
  std::vector<Geometry> run_geometry;                     // per = run
  std::map<std::string, Geometry> member_geometry;        // per = group
};

class Writer {
 public:
  // A new data file.  `mesh_kind` is "", "shared" or "changing"; `per` is
  // "fixed", "run" or "group:<label>".
  static std::unique_ptr<Writer> create(const std::string& path,
                                        const std::string& writer_name,
                                        const std::string& mesh_kind,
                                        const std::string& per);
  // An existing data file, to add runs in place.
  static std::unique_ptr<Writer> open_append(const std::string& path);

  ~Writer();

  const Schema& schema() const { return schema_; }

  void set_attribute(const std::string& name, const std::string& value);
  void declare_parameter(const Parameter& p);
  void declare_label(const std::string& name, const std::string& role,
                     const std::vector<std::string>& categories);
  void declare_result(const Result& r);
  void declare_mesh_label(const MeshLabel& m,
                          const std::vector<std::string>& categories);
  // The coordinates' units, precision and axis count (1 to 3), before
  // set_mesh or the first run.
  void declare_coordinates(const std::string& units, DType dtype, int axes);
  void set_constant(const Constant& c);
  void set_generalisation_group(const std::string& label);
  void set_compression(const FilterPipeline& filters) { filters_ = filters; }

  // A shared mesh: its cells, its fixed mesh labels and, when per is
  // fixed, its coordinates.  When the coordinates change, `points` is
  // empty and `n_nodes` says how many nodes each geometry has.
  void set_mesh(const Geometry& g);

  // Commits a batch; returns the id of its first run.
  std::int64_t add_runs(const Batch& batch);

  // Writes every staged partial chunk.  Reading through the same handle
  // flushes first.
  void flush();
  void close();

 private:
  Writer() = default;
  struct Pending;
  static std::unique_ptr<Pending> make_pending(const std::string& path, DType t,
                                               const std::vector<hsize_t>& trailing,
                                               hsize_t chunk_rows,
                                               std::int64_t on_disk);

  void need_open() const;
  void need_no_runs(const std::string& what) const;
  void check_new_root_name(const std::string& name) const;
  void ensure_datasets();
  void create_root_dataset(const std::string& path, DType dtype,
                           const std::vector<hsize_t>& trailing,
                           const std::vector<std::string>& trailing_scales);
  void append_rows(const std::string& path, const unsigned char* data,
                   std::int64_t rows, DType mem);
  void grow_table(const std::string& table,
                  const std::vector<std::string>& added);
  std::int64_t code_of(const std::string& table, const std::string& name,
                       std::vector<std::string>* added) const;
  void write_mesh_labels_fixed(const Geometry& g);
  void check_relations() const;
  void write_cf_coordinates();

  std::unique_ptr<File> file_;
  std::string path_;
  Schema schema_;
  FilterPipeline filters_ = default_pipeline();
  bool closed_ = false;
  bool datasets_ready_ = false;
  std::int64_t next_id_ = 0;
  std::int64_t instances_written_ = 0;   // per-group or per-run geometries on disk
  std::int64_t node_values_ = 0;         // changing mesh: entries in node fields
  std::int64_t cell_values_ = 0;
  std::vector<std::int64_t> instance_nodes_, instance_cells_;   // changing
  std::map<std::int64_t, std::int64_t> member_instance_;   // per group: code -> instance
  std::map<std::string, std::unique_ptr<Pending>> pending_;
};

// A random version 4 UUID, lower case.
std::string new_uuid();
// The current time as ISO 8601 UTC, to the second.
std::string utc_now();

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_WRITER_HPP
