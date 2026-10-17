// Reading files: the schema from metadata alone, and values by concept
// path with run and site selections (interface section 4).
#ifndef MESTRA_CORE_READER_HPP
#define MESTRA_CORE_READER_HPP

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "h5.hpp"
#include "schema.hpp"
#include "types.hpp"
#include "value.hpp"

namespace mestra {
namespace internal {

// Builds the schema from attributes, shapes and the (small) category
// tables, reading no field or model values.  Objects it does not know
// are left out; the validator reports them.
Schema load_schema(const File& f);

class Reader {
 public:
  static std::unique_ptr<Reader> open(const std::string& path);
  const Schema& schema() const { return schema_; }
  const File& file() const { return *file_; }

  // Names in a group: "parameters", "labels", "scalars", "constants",
  // "node_fields", "cell_fields", "node_labels", "cell_labels", "tables",
  // "models".
  std::vector<std::string> names(const std::string& group) const;
  // Every attribute of a concept as (key, value) text pairs, plus `kind`
  // (parameter, label, scalar, constant, field, mesh_label, coordinates).
  std::vector<std::pair<std::string, std::string>> describe(
      const std::string& path) const;

  // The shape a read of `path` with these selections returns.
  // Paths: a root name, "row", "coordinates", "node_fields/<n>",
  // "cell_fields/<n>", "node_labels/<n>", "cell_labels/<n>",
  // "cells/types", "cells/offsets", "cells/connectivity".
  std::vector<std::int64_t> shape(const std::string& path,
                                  const Selection& runs,
                                  const Selection& sites) const;
  void read(const std::string& path, const Selection& runs,
            const Selection& sites, DType mem, void* out,
            std::size_t out_bytes) const;
  // A label's values as names, for the selected runs.
  std::vector<std::string> label_names(const std::string& name,
                                       const Selection& runs) const;
  std::vector<std::string> table(const std::string& name) const;
  // A model's numbers (spec section 12).
  Dict model_numbers(const std::string& id) const;
  // The free-form attributes under /notes.
  std::vector<std::pair<std::string, AttrValue>> notes() const;
  std::vector<std::string> private_names() const;
  std::vector<unsigned char> private_record(const std::string& name) const;
  // Worker threads for reading fields (1: serial through HDF5).
  void set_threads(int n) { threads_ = n < 1 ? 1 : n; }

 private:
  Reader() = default;
  std::int64_t instance_of_run(std::int64_t run) const;
  std::vector<std::int64_t> row_instances(const Selection& runs) const;

  std::unique_ptr<File> file_;
  Schema schema_;
  int threads_ = 1;
};

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_READER_HPP
