#include "codec.hpp"

#include <algorithm>
#include <cstdio>
#include <set>

#include "names.hpp"

namespace gamut_core {
namespace internal {

namespace {

// Spec section 12: one NUL byte then "null", size 5.
const char kNull[5] = {'\0', 'n', 'u', 'l', 'l'};

const std::set<std::string> kMachinery = {
    "CLASS", "NAME", "DIMENSION_LIST", "REFERENCE_LIST", "DIMENSION_LABELS",
    "_Netcdf4Dimid", "_Netcdf4Coordinates", "_nc3_strict", "_NCProperties"};
const std::set<std::string> kTopLevel = {"type", "inputs", "repr"};

std::string scale_name(const std::string& dataset, std::size_t axis) {
  char buffer[32];
  std::snprintf(buffer, sizeof buffer, "_d%zu", axis);
  return "gamut_" + dataset + buffer;
}

}  // namespace

Dict read_dict_group(const File& f, const std::string& path, bool top_level, int depth) {
  if (depth >= kMaxDictDepth) {
    throw Error("E23", "\"" + path + "\" is nested deeper than this reader walks");
  }
  Dict d;
  for (const RawAttr& a : f.attributes(path)) {
    if (kMachinery.count(a.name) || reserved_name(a.name)) continue;
    if (top_level && kTopLevel.count(a.name)) continue;
    if (a.too_large) throw Error("E18", "\"" + path + "\": the attribute " + a.name + " is not a scalar");
    if (a.type.klass == H5T_STRING && a.raw_bytes.size() == 5 &&
        std::equal(a.raw_bytes.begin(), a.raw_bytes.end(), kNull)) {
      d[a.name] = Value::null();
      continue;
    }
    switch (a.value.kind()) {
      case AttrValue::Kind::Bool: d[a.name] = Value::boolean(a.value.as_bool()); break;
      case AttrValue::Kind::Int: d[a.name] = Value::integer(a.value.as_int()); break;
      case AttrValue::Kind::Float: d[a.name] = Value::real(a.value.as_float()); break;
      case AttrValue::Kind::Str:
        if (embedded_nul(a.raw_bytes) || !valid_utf8(a.value.as_text())) {
          throw Error("E18", "\"" + path + "\": the string " + a.name + " is not valid UTF-8 "
                             "without NUL bytes");
        }
        d[a.name] = Value::text(a.value.as_text());
        break;
    }
  }
  for (const Member& m : f.members(path)) {
    if (reserved_name(m.name)) continue;
    const std::string child = path + "/" + m.name;
    if (m.kind != LinkKind::Hard) {
      throw Error("E22", "\"" + child + "\" is " + link_kind_name(m.kind) +
                             "; a reader never follows one");
    }
    if (m.is_group) {
      d[m.name] = Value::dict(read_dict_group(f, child, false, depth + 1));
      continue;
    }
    if (!m.is_dataset) continue;
    const DsetInfo info = f.dataset_info(child, false);
    if (info.shape.empty()) {
      throw Error("E18", "\"" + child + "\" is a zero-dimensional dataset; section 12 stores it "
                         "as the number it holds");
    }
    std::vector<std::int64_t> shape(info.shape.begin(), info.shape.end());
    DType t;
    if (!dtype_of(info.type, &t) ||
        !(t == DType::String || t == DType::Int8 || t == DType::Int32 || t == DType::Int64 ||
          t == DType::Float64)) {
      throw Error("E18", "\"" + child + "\" has a dtype model data may not hold");
    }
    if (t == DType::String) {
      if (shape.size() != 1) throw Error("E18", "\"" + child + "\": a list of strings is one-dimensional");
      d[m.name] = Value::strings(shape, f.read_strings(child));
      continue;
    }
    // The shape comes from the file: counted against the eager caps (spec
    // section 9.6) before it sizes anything.
    std::size_t n = 1;
    for (const auto e : shape) {
      const std::size_t x = static_cast<std::size_t>(e);
      if (x != 0 && n > kMaxDatasetElements / x) n = kMaxDatasetElements + 1;
      else n *= x;
    }
    if (n > kMaxDatasetElements || n > kMaxDatasetBytes / dtype_size(t)) {
      throw Error("E23", "\"" + child + "\" declares more elements than this reader reads "
                         "at once");
    }
    std::vector<unsigned char> bytes(n * dtype_size(t));
    if (n > 0) f.read(child, t, {}, bytes.data(), bytes.size());
    d[m.name] = Value::numbers(t, shape, std::move(bytes));
  }
  return d;
}

void check_dict(const Dict& d, bool top_level, int depth, const std::string& where) {
  if (depth >= kMaxDictDepth) {
    throw Error("E23", "\"" + where + "\" is nested deeper than this writer walks");
  }
  auto clean = [](const std::string& s) {
    return s.find('\0') == std::string::npos && valid_utf8(s);
  };
  for (const auto& entry : d) {
    const std::string& key = entry.first;
    const Value& v = entry.second;
    if (!legal_netcdf_name(key) || reserved_name(key)) {
      throw Error("E8", "the model-data key \"" + key + "\" is not a legal name; " +
                            std::string(kLegalName));
    }
    if (top_level && kTopLevel.count(key)) {
      throw Error("E18", "the model data's top level may not use \"" + key +
                             "\", which is an attribute of the model");
    }
    if (v.kind() == Value::Kind::Str && !clean(v.as_text())) {
      throw Error("E18", "the model-data string \"" + key + "\" is not valid UTF-8 without "
                         "NUL bytes");
    }
    if (v.kind() == Value::Kind::Strings) {
      for (const auto& s : v.items()) {
        if (!clean(s)) {
          throw Error("E18", "a model-data string in \"" + key + "\" is not valid UTF-8 "
                             "without NUL bytes");
        }
      }
    }
    if (v.kind() == Value::Kind::Dict) check_dict(v.as_dict(), false, depth + 1, where + "/" + key);
  }
}

void write_dict_group(File& f, const std::string& path, const Dict& d, bool top_level,
                      int depth) {
  if (depth >= kMaxDictDepth) {
    throw Error("E23", "\"" + path + "\" is nested deeper than this writer walks");
  }
  for (const auto& entry : d) {
    const std::string& key = entry.first;
    const Value& v = entry.second;
    if (!legal_netcdf_name(key) || reserved_name(key)) {
      throw Error("E8", "the model-data key \"" + key + "\" is not a legal name; " +
                            std::string(kLegalName));
    }
    if (top_level && kTopLevel.count(key)) {
      throw Error("E18", "the model data's top level may not use \"" + key +
                             "\", which is an attribute of the model");
    }
    const std::string child = path + "/" + key;
    switch (v.kind()) {
      case Value::Kind::Null: f.write_raw_string_attr(path, key, std::string(kNull, 5)); break;
      case Value::Kind::Bool: f.write_attr(path, key, AttrValue::boolean(v.as_bool())); break;
      case Value::Kind::Int: f.write_attr(path, key, AttrValue::integer(v.as_int())); break;
      case Value::Kind::Float: f.write_attr(path, key, AttrValue::real(v.as_float())); break;
      case Value::Kind::Str:
        if (v.as_text().find('\0') != std::string::npos || !valid_utf8(v.as_text())) {
          throw Error("E18", "the model-data string \"" + key + "\" is not valid UTF-8 without "
                             "NUL bytes");
        }
        f.write_attr(path, key, AttrValue::text(v.as_text()));
        break;
      case Value::Kind::Numbers:
      case Value::Kind::Strings: {
        std::vector<hsize_t> shape(v.shape().begin(), v.shape().end());
        const bool empty = std::find(shape.begin(), shape.end(), hsize_t(0)) != shape.end();
        std::vector<hsize_t> maxshape, chunk;
        if (empty) {
          // A zero-length axis is unlimited, the only legal way to write it.
          maxshape = shape;
          for (auto& e : maxshape) {
            if (e == 0) e = H5S_UNLIMITED;
          }
          chunk.assign(shape.size(), 1);
        }
        if (v.kind() == Value::Kind::Strings) {
          std::size_t width = 1;
          for (const auto& s : v.items()) {
            if (s.find('\0') != std::string::npos || !valid_utf8(s)) {
              throw Error("E18", "a model-data string in \"" + key + "\" is not valid UTF-8 "
                                 "without NUL bytes");
            }
            width = std::max(width, s.size());
          }
          f.create_dataset(child, DType::String, width, shape, maxshape, chunk, {});
          f.write_strings(child, 0, v.items());
        } else {
          f.create_dataset(child, v.dtype(), 0, shape, maxshape, chunk, {});
          if (!empty) {
            std::vector<hsize_t> start(shape.size(), 0);
            f.write(child, v.dtype(), start, shape, v.bytes().data());
          }
        }
        for (std::size_t axis = 0; axis < shape.size(); ++axis) {
          const std::string s = path + "/" + scale_name(key, axis);
          f.make_scale(s, shape[axis], shape[axis] == 0);
          f.attach_scale(child, s, static_cast<unsigned>(axis));
        }
        break;
      }
      case Value::Kind::Dict:
        f.make_group(child);
        write_dict_group(f, child, v.as_dict(), false, depth + 1);
        break;
    }
  }
}

}  // namespace internal
}  // namespace gamut_core
