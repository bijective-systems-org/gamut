// Reading files: the schema from metadata alone, and values by concept
// path with run and site selections.
#ifndef GAMUT_CORE_READER_HPP
#define GAMUT_CORE_READER_HPP

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "h5.hpp"
#include "schema.hpp"
#include "types.hpp"
#include "value.hpp"

namespace gamut_core {
namespace internal {

// Builds the schema from attributes, shapes and the (small) category
// tables, reading no field or model values, after refusing a file of
// another format version (E1).  Objects it does not know are left out;
// the validator reports them.
Schema load_schema(const File& f, const std::string& path);

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
  // How far each selected run's value of a parameter lies outside the
  // bounds the file declares for it, in its units: 0 inside or on a bound,
  // value - lower below, value - upper above, NaN where the value is
  // missing.  A parameter without bounds is refused.  `out` is a capacity,
  // as in read; the shape of a read of the parameter says what it needs.
  void outside(const std::string& name, const Selection& runs, double* out,
               std::size_t out_bytes) const;
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
  // The shape before the read limit is applied.
  std::vector<std::int64_t> unchecked_shape(const std::string& path,
                                            const Selection& runs,
                                            const Selection& sites) const;
  Reader() = default;
  std::int64_t instance_of_run(std::int64_t run) const;
  // Entries k and k + 1 of a cumulative count, checked (E21).
  std::pair<std::int64_t, std::int64_t> span(const std::string& cumulative, std::int64_t k,
                                             const std::string& path) const;
  std::vector<std::int64_t> row_instances(const Selection& runs) const;

  std::unique_ptr<File> file_;
  Schema schema_;
  int threads_ = 1;
};

// -1, 0 or 1 as the int64 v is below, at or above the finite b, exactly
// (as doubles, integers lose bits past 2^53).
int compare_int64(std::int64_t v, double b);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_READER_HPP
