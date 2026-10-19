// Writing data files (spec sections 3 to 5, 10, 11): create, declare,
// then add runs, which go to disk in whole chunks as they arrive.
#ifndef GAMUT_CORE_WRITER_HPP
#define GAMUT_CORE_WRITER_HPP

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "h5.hpp"
#include "schema.hpp"
#include "types.hpp"
#include "value.hpp"

namespace gamut_core {
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
  // Row ids to keep instead of assigning new ones: copies only (extract,
  // write_copy), from a file that has passed validation.
  std::vector<std::int64_t> ids;
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
  // A new model file (spec section 7): no runs; inputs with bounds; results
  // served by models.  `mesh_kind` is "" or "shared", `per` "fixed" or "run".
  static std::unique_ptr<Writer> create_model(const std::string& path,
                                              const std::string& writer_name,
                                              const std::string& mesh_kind,
                                              const std::string& per);

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
  void declare_coordinates(const std::string& units, DType dtype, int axes,
                           const std::string& model = "", const std::string& output = "");
  // A model of a model file: its type, the inputs it reads, its numbers.
  void add_model(const std::string& id, const std::string& type,
                 const std::vector<std::string>& inputs, const Dict& numbers,
                 const std::string& repr);
  void set_constant(const Constant& c);
  void set_generalisation_group(const std::string& label);
  void set_compression(const FilterPipeline& filters) { filters_ = filters; }
  // A free-form public attribute under /notes (spec section 8).
  void set_note(const std::string& key, const AttrValue& value);
  // A producer's own record under /private, bytes no reader interprets.
  void set_private(const std::string& name, const std::vector<unsigned char>& bytes);

  // A shared mesh: its cells, its fixed mesh labels and, when per is
  // fixed, its coordinates.  When the coordinates change, `points` is
  // empty and `n_nodes` says how many nodes each geometry has.
  void set_mesh(const Geometry& g);

  // Commits a batch; returns the id of its first run.  With `check_only`,
  // makes every check and writes nothing (a copy checks all its batches
  // before the first is written).
  std::int64_t add_runs(const Batch& batch, bool check_only = false);

  // Whether the group member `name` already has its geometry here.
  bool has_member(const std::string& name) const;
  // A rewrite of one file keeps its identity: file_id and created.
  void keep_identity(const std::string& file_id, const std::string& created);

  // Writes every staged partial chunk.  Reading through the same handle
  // flushes first.
  void flush();
  void close();
  // Releases the file without finishing it; with `remove`, deletes a file
  // this writer created.  For giving up after an error.
  void abandon(bool remove);

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
  void ensure_datasets(const Batch* first);
  // What must hold before the first rows create datasets, checked on `s`
  // (where it fixes whether a changing mesh has cells); writes nothing.
  static void check_preconditions(Schema& s, const Batch* first);
  static void resolve_autos(Schema& s, const Batch* first);
  void check_mesh_labels_fixed(const Geometry& g, std::int64_t n_nodes,
                               std::int64_t n_cells) const;
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
  bool model_ = false;
  bool created_ = false;
  bool datasets_ready_ = false;
  std::int64_t next_id_ = 0;
  std::int64_t instances_written_ = 0;   // per-group or per-run geometries on disk
  std::int64_t node_values_ = 0;         // changing mesh: entries in node fields
  std::int64_t cell_values_ = 0;
  std::vector<std::int64_t> instance_nodes_, instance_cells_;   // changing
  std::map<std::int64_t, std::int64_t> member_instance_;   // per group: code -> instance
  // Per group: a fingerprint of each instance's stored geometry, so a
  // member given its geometry again is checked without keeping it.
  std::map<std::int64_t, std::string> instance_print_;
  std::string geometry_print(const Geometry& g) const;
  std::string instance_print(std::int64_t instance);
  std::map<std::string, std::unique_ptr<Pending>> pending_;
};

// A random version 4 UUID, lower case.
std::string new_uuid();
// The current time as ISO 8601 UTC, to the second.
std::string utc_now();

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_WRITER_HPP
