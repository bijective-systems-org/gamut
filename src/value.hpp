// A model's numbers (spec section 12): a nested dictionary of numbers,
// booleans, strings, numeric arrays, lists of strings and nulls.
#ifndef GAMUT_CORE_VALUE_HPP
#define GAMUT_CORE_VALUE_HPP

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "types.hpp"

namespace gamut {
namespace internal {

struct BytesOrder {
  bool operator()(const std::string& a, const std::string& b) const {
    return bytes_less(a, b);
  }
};

class Value;
using Dict = std::map<std::string, Value, BytesOrder>;   // keys in UTF-8 byte order

const int kMaxDictDepth = 64;

class Value {
 public:
  enum class Kind { Null, Bool, Int, Float, Str, Numbers, Strings, Dict };

  Value() = default;
  static Value null() { return Value(); }
  static Value boolean(bool v);
  static Value integer(std::int64_t v);
  static Value real(double v);
  static Value text(std::string v);
  // `dtype` is Int8 (booleans), Int32, Int64 or Float64; `bytes` packed in C order.
  static Value numbers(DType dtype, std::vector<std::int64_t> shape,
                       std::vector<unsigned char> bytes);
  static Value strings(std::vector<std::int64_t> shape, std::vector<std::string> items);
  static Value dict(Dict d);

  Kind kind() const { return kind_; }
  bool as_bool() const { return i_ != 0; }
  std::int64_t as_int() const { return i_; }
  double as_float() const { return f_; }
  const std::string& as_text() const { return s_; }
  DType dtype() const { return dtype_; }
  const std::vector<std::int64_t>& shape() const { return shape_; }
  const std::vector<unsigned char>& bytes() const { return bytes_; }
  const std::vector<std::string>& items() const { return items_; }
  const Dict& as_dict() const { return *dict_; }
  Dict& as_dict() { return *dict_; }
  std::int64_t size() const;   // elements of an array

 private:
  Kind kind_ = Kind::Null;
  std::int64_t i_ = 0;
  double f_ = 0.0;
  std::string s_;
  DType dtype_ = DType::Float64;
  std::vector<std::int64_t> shape_;
  std::vector<unsigned char> bytes_;
  std::vector<std::string> items_;
  std::shared_ptr<Dict> dict_;
};

// The value at a '/'-separated key path ("" is the root dictionary), or
// null when absent.  Throws when a step is not a dictionary.
const Value* find_path(const Dict& root, const std::string& path);
// Sets the value at a key path, making dictionaries along the way.
void set_path(Dict& root, const std::string& path, Value v);

}  // namespace internal
}  // namespace gamut

#endif  // GAMUT_CORE_VALUE_HPP
