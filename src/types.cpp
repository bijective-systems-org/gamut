#include "types.hpp"

#include <cstring>

namespace gamut_core {

bool bytes_less(const std::string& a, const std::string& b) {
  const std::size_t n = a.size() < b.size() ? a.size() : b.size();
  const int c = n == 0 ? 0 : std::memcmp(a.data(), b.data(), n);
  if (c != 0) return c < 0;
  return a.size() < b.size();
}

const char* dtype_name(DType t) {
  switch (t) {
    case DType::UInt8: return "uint8";
    case DType::Int8: return "int8";
    case DType::Int32: return "int32";
    case DType::Int64: return "int64";
    case DType::Float32: return "float32";
    case DType::Float64: return "float64";
    case DType::String: return "string";
  }
  return "unknown";
}

std::size_t dtype_size(DType t) {
  switch (t) {
    case DType::UInt8:
    case DType::Int8: return 1;
    case DType::Int32:
    case DType::Float32: return 4;
    case DType::Int64:
    case DType::Float64: return 8;
    case DType::String: return 0;
  }
  return 0;
}

bool dtype_from_int(int code, DType* out) {
  if (code < 1 || code > 7) return false;
  *out = static_cast<DType>(code);
  return true;
}

AttrValue AttrValue::boolean(bool v) {
  AttrValue a;
  a.kind_ = Kind::Bool;
  a.b_ = v;
  return a;
}

AttrValue AttrValue::integer(std::int64_t v) {
  AttrValue a;
  a.kind_ = Kind::Int;
  a.i_ = v;
  return a;
}

AttrValue AttrValue::real(double v) {
  AttrValue a;
  a.kind_ = Kind::Float;
  a.d_ = v;
  return a;
}

AttrValue AttrValue::text(std::string v) {
  AttrValue a;
  a.kind_ = Kind::Str;
  a.s_ = std::move(v);
  return a;
}

bool AttrValue::operator==(const AttrValue& o) const {
  if (kind_ != o.kind_) return false;
  switch (kind_) {
    case Kind::Bool: return b_ == o.b_;
    case Kind::Int: return i_ == o.i_;
    case Kind::Float:
      // Bitwise, so that NaN equals itself and -0.0 differs from 0.0: an
      // attribute round-trips exactly or it does not.
      return std::memcmp(&d_, &o.d_, sizeof d_) == 0;
    case Kind::Str: return s_ == o.s_;
  }
  return false;
}

FilterPipeline default_pipeline() {
  return {FilterStep::shuffle(), FilterStep::gzip(1)};
}

std::int64_t Selection::count(std::int64_t length,
                              const std::string& what) const {
  switch (kind) {
    case All: return length;
    case Range:
      if (start < 0 || stop < start || stop > length) {
        // Positions count from 0 here; the 1-based languages say so too.
        throw Error("", what + ": the range [" + std::to_string(start) + ", " +
                            std::to_string(stop) + "), counting from 0, is outside the " +
                            std::to_string(length) + " positions");
      }
      return stop - start;
    case Index: {
      std::int64_t previous = -1;
      for (const std::int64_t i : index) {
        if (i < 0 || i >= length) {
          throw Error("", what + ": position " + std::to_string(i) +
                              ", counting from 0, is outside the " + std::to_string(length) +
                              " positions");
        }
        if (i <= previous) {
          throw Error("", what + ": positions must be strictly increasing, and " +
                              std::to_string(i) + " follows " + std::to_string(previous) +
                              " (counting from 0)");
        }
        previous = i;
      }
      return static_cast<std::int64_t>(index.size());
    }
  }
  return 0;
}

std::vector<std::pair<std::int64_t, std::int64_t>> Selection::runs(
    std::int64_t length, const std::string& what) const {
  std::vector<std::pair<std::int64_t, std::int64_t>> out;
  const std::int64_t n = count(length, what);
  if (n == 0) return out;
  switch (kind) {
    case All: out.emplace_back(0, length); break;
    case Range: out.emplace_back(start, stop - start); break;
    case Index: {
      std::int64_t first = index[0];
      std::int64_t len = 1;
      for (std::size_t k = 1; k < index.size(); ++k) {
        if (index[k] == first + len) {
          ++len;
        } else {
          out.emplace_back(first, len);
          first = index[k];
          len = 1;
        }
      }
      out.emplace_back(first, len);
      break;
    }
  }
  return out;
}

}  // namespace gamut_core
