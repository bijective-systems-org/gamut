#include "nearest.hpp"

#include <cmath>
#include <cstring>
#include <limits>
#include <set>

namespace gamut_core {
namespace internal {

namespace {

void need(bool ok, const std::string& rule, const std::string& message) {
  if (!ok) throw Error(rule, message);
}

std::vector<double> as_doubles(const Value& v, const std::string& what) {
  need(v.kind() == Value::Kind::Numbers, "E17", "nearest: " + what + " is a numeric array");
  std::vector<double> out(static_cast<std::size_t>(v.size()));
  const auto& b = v.bytes();
  for (std::size_t i = 0; i < out.size(); ++i) {
    switch (v.dtype()) {
      case DType::Float64: std::memcpy(&out[i], &b[i * 8], 8); break;
      case DType::Int64: {
        std::int64_t x;
        std::memcpy(&x, &b[i * 8], 8);
        out[i] = static_cast<double>(x);
        break;
      }
      case DType::Int32: {
        std::int32_t x;
        std::memcpy(&x, &b[i * 4], 4);
        out[i] = static_cast<double>(x);
        break;
      }
      default: out[i] = static_cast<double>(static_cast<signed char>(b[i])); break;
    }
  }
  return out;
}

}  // namespace

Nearest nearest_from(const Dict& numbers) {
  Nearest m;
  const Value* columns = find_path(numbers, "columns");
  need(columns != nullptr && columns->kind() == Value::Kind::Strings, "E17",
       "nearest: columns is a list of the input names");
  m.columns = columns->items();
  std::set<std::string> seen(m.columns.begin(), m.columns.end());
  need(seen.size() == m.columns.size() && !m.columns.empty(), "E17",
       "nearest: columns names each input once");
  const std::size_t c = m.columns.size();
  const Value* lower = find_path(numbers, "lower");
  const Value* upper = find_path(numbers, "upper");
  need(lower != nullptr && upper != nullptr, "E17", "nearest: lower and upper are required");
  m.lower = as_doubles(*lower, "lower");
  m.upper = as_doubles(*upper, "upper");
  need(m.lower.size() == c && m.upper.size() == c, "E17",
       "nearest: lower and upper give one bound per column");
  for (std::size_t j = 0; j < c; ++j) {
    need(std::isfinite(m.lower[j]) && std::isfinite(m.upper[j]) && m.lower[j] <= m.upper[j], "E17",
         "nearest: bounds are finite with lower <= upper");
  }
  const Value* x = find_path(numbers, "x");
  need(x != nullptr && x->kind() == Value::Kind::Numbers && x->shape().size() == 2 &&
           static_cast<std::size_t>(x->shape()[1]) == c,
       "E17", "nearest: x is points x columns");
  m.points = x->shape()[0];
  need(m.points >= 1, "E17", "nearest: a model holds at least one point");
  m.x = as_doubles(*x, "x");
  const Value* outputs = find_path(numbers, "outputs");
  need(outputs != nullptr && outputs->kind() == Value::Kind::Dict, "E17",
       "nearest: outputs is a dictionary of arrays");
  for (const auto& kv : outputs->as_dict()) {
    need(kv.second.kind() == Value::Kind::Numbers && !kv.second.shape().empty() &&
             kv.second.shape()[0] == m.points,
         "E17", "nearest: the output " + kv.first + " is an array whose first axis is the points");
    m.outputs[kv.first] = kv.second;
  }
  return m;
}

Dict nearest_numbers(const Nearest& m) {
  Dict d;
  d["columns"] = Value::strings({static_cast<std::int64_t>(m.columns.size())}, m.columns);
  auto doubles = [](const std::vector<double>& v, std::vector<std::int64_t> shape) {
    std::vector<unsigned char> b(v.size() * 8);
    if (!v.empty()) std::memcpy(b.data(), v.data(), b.size());
    return Value::numbers(DType::Float64, std::move(shape), std::move(b));
  };
  d["lower"] = doubles(m.lower, {static_cast<std::int64_t>(m.lower.size())});
  d["upper"] = doubles(m.upper, {static_cast<std::int64_t>(m.upper.size())});
  d["x"] = doubles(m.x, {m.points, static_cast<std::int64_t>(m.columns.size())});
  Dict outputs;
  for (const auto& kv : m.outputs) outputs[kv.first] = kv.second;
  d["outputs"] = Value::dict(std::move(outputs));
  return d;
}

std::vector<std::int64_t> nearest_indices(const Nearest& m,
                                          const std::map<std::string, const double*>& inputs,
                                          std::int64_t rows) {
  const std::size_t c = m.columns.size();
  std::vector<const double*> q(c, nullptr);
  for (std::size_t j = 0; j < c; ++j) {
    const auto it = inputs.find(m.columns[j]);
    need(it != inputs.end() && it->second != nullptr, "E17",
         "nearest: the input " + m.columns[j] + " is missing");
    q[j] = it->second;
  }
  std::vector<std::int64_t> out(static_cast<std::size_t>(rows), -1);
  for (std::int64_t r = 0; r < rows; ++r) {
    bool finite = true;
    for (std::size_t j = 0; j < c; ++j) {
      if (m.upper[j] != m.lower[j] && !std::isfinite(q[j][r])) finite = false;
    }
    if (!finite) continue;
    // Spec section 7.5: t_j = (q_j - x_ij) / (upper_j - lower_j), rounded to
    // float64 before squaring; summed left to right in column order, each
    // step rounded, no fused multiply-add (the build forbids contraction).
    double best = std::numeric_limits<double>::infinity();
    std::int64_t best_i = -1;
    for (std::int64_t i = 0; i < m.points; ++i) {
      double d = 0.0;
      for (std::size_t j = 0; j < c; ++j) {
        const double span = m.upper[j] - m.lower[j];
        if (span == 0.0) continue;
        const double t = (q[j][r] - m.x[static_cast<std::size_t>(i) * c + j]) / span;
        const double tt = t * t;
        d = d + tt;
      }
      if (d < best) {
        best = d;
        best_i = i;
      }
    }
    out[static_cast<std::size_t>(r)] = best_i;
  }
  return out;
}

std::int64_t nearest_output_size(const Nearest& m, const std::string& output) {
  const auto it = m.outputs.find(output);
  need(it != m.outputs.end(), "E17", "nearest: there is no output called " + output);
  return it->second.size() / m.points;
}

std::vector<double> nearest_values(const Nearest& m, const std::string& output,
                                   const std::vector<std::int64_t>& index) {
  const auto it = m.outputs.find(output);
  need(it != m.outputs.end(), "E17", "nearest: there is no output called " + output);
  const std::vector<double> all = as_doubles(it->second, "outputs/" + output);
  const std::size_t per = static_cast<std::size_t>(it->second.size() / m.points);
  std::vector<double> out(index.size() * per, std::numeric_limits<double>::quiet_NaN());
  for (std::size_t r = 0; r < index.size(); ++r) {
    if (index[r] < 0) continue;
    std::memcpy(&out[r * per], &all[static_cast<std::size_t>(index[r]) * per], per * 8);
  }
  return out;
}

}  // namespace internal
}  // namespace gamut_core
