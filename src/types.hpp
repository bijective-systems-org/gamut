// The core's internal vocabulary: errors, dtypes, attribute values,
// filter pipelines.  Internal; nothing here crosses the C interface.
#ifndef GAMUT_CORE_TYPES_HPP
#define GAMUT_CORE_TYPES_HPP

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace gamut_core {

// Every failure the core raises.  `rule` is the identifier of SPEC.md
// section 16 when one applies (E1 ... E24, W1 ... W10) and empty when no
// rule covers the failure (a missing file, a wrong argument).  `path` is
// a concept path (`node_fields/p`), never an HDF5 path, or empty.
class Error : public std::runtime_error {
 public:
  Error(std::string rule, const std::string& message, std::string path = {})
      : std::runtime_error(message), rule_(std::move(rule)),
        path_(std::move(path)) {}
  const std::string& rule() const { return rule_; }
  const std::string& path() const { return path_; }

 private:
  std::string rule_;
  std::string path_;
};

// Byte order of UTF-8 strings: the order in which names are listed and
// dictionary keys are written (spec section 12).
bool bytes_less(const std::string& a, const std::string& b);

// The element types the format stores.  The numeric codes are the C
// interface's `gamut_dtype`, so a binding passes them straight through.
enum class DType : int {
  UInt8 = 1,    // cell_types
  Int8 = 2,     // a boolean inside model data
  Int32 = 3,
  Int64 = 4,
  Float32 = 5,
  Float64 = 6,
  String = 7    // fixed-length UTF-8, NUL-padded
};

const char* dtype_name(DType t);
std::size_t dtype_size(DType t);   // bytes per element; 0 for String
bool dtype_from_int(int code, DType* out);

// One attribute value of spec section 9.2 (and int8 booleans inside
// model data, section 12).
class AttrValue {
 public:
  enum class Kind { Bool, Int, Float, Str };

  AttrValue() : kind_(Kind::Int) {}
  static AttrValue boolean(bool v);
  static AttrValue integer(std::int64_t v);
  static AttrValue real(double v);
  static AttrValue text(std::string v);

  Kind kind() const { return kind_; }
  bool as_bool() const { return b_; }
  std::int64_t as_int() const { return i_; }
  double as_float() const { return d_; }
  const std::string& as_text() const { return s_; }

  bool operator==(const AttrValue& o) const;
  bool operator!=(const AttrValue& o) const { return !(*this == o); }

 private:
  Kind kind_;
  bool b_ = false;
  std::int64_t i_ = 0;
  double d_ = 0.0;
  std::string s_;
};

// The filters of spec section 11.2, in pipeline order.
struct FilterStep {
  enum Kind { Shuffle, Gzip };
  Kind kind = Shuffle;
  int level = 0;    // gzip level 1 to 9; unused for shuffle

  static FilterStep shuffle() { return FilterStep{Shuffle, 0}; }
  static FilterStep gzip(int level) { return FilterStep{Gzip, level}; }
  bool operator==(const FilterStep& o) const {
    return kind == o.kind && (kind != Gzip || level == o.level);
  }
};
using FilterPipeline = std::vector<FilterStep>;

// The default pipeline writers use: shuffle, then gzip level 1.
FilterPipeline default_pipeline();

// A selection along one axis: everything, a half-open range, or a
// strictly increasing list of indices.
struct Selection {
  enum Kind { All = 0, Range = 1, Index = 2 };
  Kind kind = All;
  std::int64_t start = 0;
  std::int64_t stop = 0;
  std::vector<std::int64_t> index;

  static Selection all() { return Selection{}; }
  static Selection range(std::int64_t a, std::int64_t b) {
    Selection s;
    s.kind = Range;
    s.start = a;
    s.stop = b;
    return s;
  }
  static Selection list(std::vector<std::int64_t> i) {
    Selection s;
    s.kind = Index;
    s.index = std::move(i);
    return s;
  }
  // The number of positions selected out of `length`; throws Error when
  // the selection is outside [0, length) or an index list is not
  // strictly increasing.
  std::int64_t count(std::int64_t length, const std::string& what) const;
  // The selected positions as maximal runs of consecutive indices:
  // (start, count) pairs, for hyperslab unions.
  std::vector<std::pair<std::int64_t, std::int64_t>> runs(
      std::int64_t length, const std::string& what) const;
};

}  // namespace gamut_core

#endif  // GAMUT_CORE_TYPES_HPP
