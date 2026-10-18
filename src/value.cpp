#include "value.hpp"

#include <cstdint>

namespace gamut_core {
namespace internal {

Value Value::boolean(bool v) {
  Value x;
  x.kind_ = Kind::Bool;
  x.i_ = v ? 1 : 0;
  return x;
}

Value Value::integer(std::int64_t v) {
  Value x;
  x.kind_ = Kind::Int;
  x.i_ = v;
  return x;
}

Value Value::real(double v) {
  Value x;
  x.kind_ = Kind::Float;
  x.f_ = v;
  return x;
}

Value Value::text(std::string v) {
  Value x;
  x.kind_ = Kind::Str;
  x.s_ = std::move(v);
  return x;
}

Value Value::numbers(DType dtype, std::vector<std::int64_t> shape,
                     std::vector<unsigned char> bytes) {
  if (dtype != DType::Int8 && dtype != DType::Int32 && dtype != DType::Int64 &&
      dtype != DType::Float64) {
    throw Error("E18", std::string("model data arrays are int8 (booleans), int32, int64 or "
                                   "float64, not ") + dtype_name(dtype));
  }
  Value x;
  x.kind_ = Kind::Numbers;
  x.dtype_ = dtype;
  x.shape_ = std::move(shape);
  x.bytes_ = std::move(bytes);
  if (x.shape_.empty()) {
    throw Error("E18", "a zero-dimensional array is stored as the number it holds");
  }
  const std::uint64_t n = static_cast<std::uint64_t>(x.size());
  if (n > SIZE_MAX / dtype_size(dtype) || n * dtype_size(dtype) != x.bytes_.size()) {
    throw Error("", "an array's bytes do not match its shape");
  }
  return x;
}

Value Value::strings(std::vector<std::int64_t> shape, std::vector<std::string> items) {
  Value x;
  x.kind_ = Kind::Strings;
  x.dtype_ = DType::String;
  x.shape_ = std::move(shape);
  x.items_ = std::move(items);
  if (x.shape_.size() != 1 || static_cast<std::size_t>(x.shape_[0]) != x.items_.size()) {
    throw Error("E18", "a list of strings is one-dimensional");
  }
  return x;
}

Value Value::dict(Dict d) {
  Value x;
  x.kind_ = Kind::Dict;
  x.dict_ = std::make_shared<Dict>(std::move(d));
  return x;
}

std::int64_t Value::size() const {
  std::int64_t n = 1;
  for (const auto e : shape_) {
    if (e < 0 || (e != 0 && n > INT64_MAX / e)) {
      throw Error("E18", "an array's shape is negative or too large");
    }
    n *= e;
  }
  return n;
}

namespace {

std::vector<std::string> steps(const std::string& path) {
  std::vector<std::string> out;
  std::size_t at = 0;
  while (at <= path.size() && !path.empty()) {
    const std::size_t next = path.find('/', at);
    out.push_back(path.substr(at, next == std::string::npos ? std::string::npos : next - at));
    if (next == std::string::npos) break;
    at = next + 1;
  }
  return out;
}

}  // namespace

const Value* find_path(const Dict& root, const std::string& path) {
  if (path.empty()) return nullptr;
  const Dict* d = &root;
  const auto parts = steps(path);
  for (std::size_t i = 0; i < parts.size(); ++i) {
    const auto it = d->find(parts[i]);
    if (it == d->end()) return nullptr;
    if (i + 1 == parts.size()) return &it->second;
    if (it->second.kind() != Value::Kind::Dict) {
      throw Error("", "\"" + parts[i] + "\" in " + path + " is not a dictionary");
    }
    d = &it->second.as_dict();
  }
  return nullptr;
}

void set_path(Dict& root, const std::string& path, Value v) {
  if (path.empty()) throw Error("", "a key path is not empty");
  Dict* d = &root;
  const auto parts = steps(path);
  for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
    auto it = d->find(parts[i]);
    if (it == d->end()) it = d->emplace(parts[i], Value::dict(Dict())).first;
    if (it->second.kind() != Value::Kind::Dict) {
      throw Error("", "\"" + parts[i] + "\" in " + path + " is not a dictionary");
    }
    d = &it->second.as_dict();
  }
  (*d)[parts.back()] = std::move(v);
}

}  // namespace internal
}  // namespace gamut_core
