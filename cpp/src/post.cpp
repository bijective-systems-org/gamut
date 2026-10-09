// integrate and field_statistics.  Both work on a Dataset already in
// memory and neither opens a file.
#include "mestra/post.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>

#include "mestra/affine.hpp"
#include "mestra/io.hpp"
#include "mestra/weights.hpp"
#include "names.hpp"

namespace mestra {
namespace {

[[noreturn]] void refuse(const std::string& what, const std::string& why) {
  throw Error("", "mestra::" + what + ": " + why);
}

// Where a slot was found: which support, which location, and the slot
// itself.
struct Found {
  const Support* support = nullptr;
  Location where = Location::Node;
  const ArraySlot* slot = nullptr;
};

std::string slot_path(const Support& s, const ArraySlot& a) {
  if (a.role == "coordinates") return "/supports/" + s.name + "/coordinates";
  return "/supports/" + s.name +
         (a.location == Location::Node ? "/node_arrays/" : "/cell_arrays/") +
         a.name;
}

// A slot by name, or by the path `info` prints.  Two slots of one
// name in one file are an ambiguity the caller has to settle, so it
// is reported rather than resolved by picking the first.
Found find_slot(const Dataset& d, const std::string& what,
                const std::string& slot) {
  Found found;
  std::vector<std::string> matches;
  for (const Support& s : d.supports) {
    std::vector<const ArraySlot*> all;
    if (s.coordinates.has_value()) all.push_back(&*s.coordinates);
    for (const ArraySlot& a : s.node_arrays) all.push_back(&a);
    for (const ArraySlot& a : s.cell_arrays) all.push_back(&a);
    for (const ArraySlot* a : all) {
      const std::string path = slot_path(s, *a);
      if (a->name != slot && path != slot) continue;
      matches.push_back(path);
      if (matches.size() == 1) {
        found.support = &s;
        found.where = a->location;
        found.slot = a;
      }
    }
  }
  if (matches.empty()) {
    refuse(what, "no slot named \"" + slot + "\" is in this file");
  }
  if (matches.size() > 1) {
    std::string listed;
    for (const std::string& m : matches) {
      if (!listed.empty()) listed += " and ";
      listed += m;
    }
    refuse(what, "\"" + slot + "\" names " + listed +
                     "; give the whole path to say which");
  }
  return found;
}

// The file's own key columns as a keys table (section 26).
KeysTable own_keys(const Dataset& d) {
  KeysTable t;
  for (const Key& k : d.keys) {
    if (k.dtype == DType::String) {
      t.add_text_column(k.name, k.str);
    } else if (k.dtype == DType::Float64) {
      t.add_column(k.name, k.f64);
    } else {
      std::vector<double> values;
      values.reserve(k.i64.size());
      for (const std::int64_t v : k.i64) {
        values.push_back(static_cast<double>(v));
      }
      t.add_column(k.name, std::move(values));
    }
  }
  return t;
}

// The record a callable gives for `output`, with the file's own rows
// as the keys table when the caller gave none.
Prediction served(const Dataset& d, const std::string& id,
                  const std::string& output, const std::string& where,
                  const KeysTable* keys) {
  Affine::register_type();
  const StoredCallable* stored = nullptr;
  for (const StoredCallable& c : d.callables) {
    if (c.id == id) stored = &c;
  }
  if (stored == nullptr) {
    throw Error("E14", "the slot \"" + where + "\" names the callable \"" +
                           id + "\", which the file does not hold");
  }
  const std::unique_ptr<Callable> object =
      CallableRegistry::from_dict(stored->type, stored->dict);
  if (!object) {
    refuse("prediction", "no factory is registered for the callable type \"" +
                             stored->type + "\"; the dictionary may be "
                             "copied but not interpreted. " + internal::kRegisterHint);
  }
  KeysTable own;
  if (keys == nullptr) {
    if (d.n_rows == 0) {
      refuse("prediction", "this file has no rows to evaluate \"" + where +
                               "\" on; pass a keys table with one column "
                               "per key");
    }
    own = own_keys(d);
    keys = &own;
  }
  const Outputs out = object->call(*keys);
  if (!out.has(output)) {
    throw Error("E14", "the callable \"" + id + "\" produced no output "
                       "called \"" + output + "\"");
  }
  Prediction record = out.at(output);
  record.check(where);
  return record;
}

std::size_t element_count(const Support& s, Location where) {
  return static_cast<std::size_t>(where == Location::Node ? s.n_nodes
                                                          : s.n_cells);
}

// Which instance of an array a row reads: itself for `row`, its
// category for `group:<k>`, and the only one for `none`.
std::size_t instance_of_row(const Dataset& d, const ArraySlot& a,
                            std::size_t row, const std::string& what) {
  if (a.varies == "none") return 0;
  if (a.varies == "row") return row;
  const std::string group = internal::group_of_varies(a.varies);
  const Key* k = d.key(group);
  if (k == nullptr) {
    refuse(what, "the array varies along \"" + a.varies +
                     "\" and the file declares no key \"" + group + "\"");
  }
  if (row >= k->i64.size()) {
    refuse(what, "the key \"" + group + "\" has no value for row " +
                     internal::format_i64(static_cast<std::int64_t>(row)));
  }
  return static_cast<std::size_t>(k->i64[row]);
}

}  // namespace

std::size_t Integral::rows() const {
  return shape.size() == 2 ? shape[0] : 1;
}

std::size_t Integral::components() const {
  return shape.empty() ? 0 : shape.back();
}

double Integral::at(std::size_t row, std::size_t component) const {
  const std::size_t at = row * components() + component;
  return at < values.size() ? values[at] : 0.0;
}

Integral integrate(const Dataset& d, const std::string& slot,
                   const IntegrateOptions& options) {
  const Found found = find_slot(d, "integrate", slot);
  const Support& s = *found.support;
  const ArraySlot& a = *found.slot;
  if (a.is_callable()) {
    refuse("integrate", slot_path(s, a) +
                            " is served by a callable and holds no values; "
                            "evaluate the file first");
  }
  const std::size_t count = element_count(s, found.where);
  const std::size_t components = static_cast<std::size_t>(a.components);
  if (count == 0 || components == 0) {
    refuse("integrate", slot_path(s, a) + " has nothing to integrate over");
  }

  // The weight array: the one named, else the one of role `weight` at
  // this location, else one computed here and said so.
  Support copy;
  const ArraySlot* w = nullptr;
  bool recomputed = false;
  const std::vector<ArraySlot>& here =
      found.where == Location::Node ? s.node_arrays : s.cell_arrays;
  for (const ArraySlot& candidate : here) {
    if (!options.weight.empty()) {
      if (candidate.name == options.weight) w = &candidate;
    } else if (candidate.role == "weight" && !candidate.is_callable()) {
      w = &candidate;
    }
  }
  if (w == nullptr && !options.weight.empty()) {
    refuse("integrate", "this file has no array \"" + options.weight +
                            "\" at the location of " + slot_path(s, a));
  }
  if (w == nullptr) {
    copy = s;
    w = &compute_weights(copy, found.where);
    recomputed = true;
  }
  if (w->is_callable() || w->data.f64.empty()) {
    refuse("integrate", "the weight array \"" + w->name +
                            "\" holds no values");
  }

  const bool per_row = a.varies != "none";
  const std::size_t rows =
      per_row ? static_cast<std::size_t>(d.n_rows) : std::size_t(1);
  Integral out;
  out.weight = w->name;
  out.weight_recomputed = recomputed;
  out.units = internal::units_product(a.units.value_or(""),
                                      w->units.value_or(""));
  if (per_row) {
    out.dims.push_back("row");
    out.shape.push_back(rows);
  }
  out.dims.push_back("component");
  out.shape.push_back(components);
  out.values.assign(rows * components, 0.0);

  for (std::size_t r = 0; r < rows; ++r) {
    const std::size_t value_instance =
        per_row ? instance_of_row(d, a, r, "integrate") : 0;
    const std::size_t weight_instance =
        instance_of_row(d, *w, r, "integrate");
    const std::size_t value_at = value_instance * count * components;
    const std::size_t weight_at = weight_instance * count;
    for (std::size_t i = 0; i < count; ++i) {
      if (weight_at + i >= w->data.f64.size()) break;
      const double weight = w->data.f64[weight_at + i];
      for (std::size_t c = 0; c < components; ++c) {
        const std::size_t at = value_at + i * components + c;
        if (at >= a.data.f64.size()) continue;
        out.values[r * components + c] += a.data.f64[at] * weight;
      }
    }
  }
  return out;
}

FieldStatistics field_statistics(const Dataset& d, const std::string& slot,
                                 const std::string& by) {
  const Found found = find_slot(d, "field_statistics", slot);
  const Support& s = *found.support;
  const ArraySlot& a = *found.slot;
  if (a.is_callable()) {
    refuse("field_statistics",
           slot_path(s, a) +
               " is served by a callable and holds no values; evaluate "
               "the file first");
  }
  const std::size_t count = element_count(s, found.where);
  const std::size_t components = static_cast<std::size_t>(a.components);

  const ArraySlot* label = nullptr;
  if (!by.empty()) {
    const std::vector<ArraySlot>& here =
        found.where == Location::Node ? s.node_arrays : s.cell_arrays;
    for (const ArraySlot& candidate : here) {
      if (candidate.name == by) label = &candidate;
    }
    if (label == nullptr) {
      refuse("field_statistics",
             "no label \"" + by + "\" sits beside " + slot_path(s, a) +
                 "; a label groups values only where it is on the same "
                 "support at the same location");
    }
    if (label->components != 1) {
      refuse("field_statistics", "the label \"" + by +
                                     "\" has more than one component");
    }
    if (label->varies != "none" && label->varies != a.varies) {
      refuse("field_statistics",
             "the label \"" + by + "\" varies along \"" + label->varies +
                 "\" and the slot along \"" + a.varies +
                 "\", so no value has one group");
    }
  }

  // One accumulator per group, in ascending order of the label's
  // value, so that the table reads the way the category table does.
  struct Accumulator {
    std::size_t count = 0;
    std::size_t missing = 0;
    double minimum = std::numeric_limits<double>::infinity();
    double maximum = -std::numeric_limits<double>::infinity();
    double sum = 0.0;
    double sum_squares = 0.0;
  };
  std::map<std::int64_t, Accumulator> groups;
  const std::size_t instances =
      count * components == 0
          ? 0
          : a.data.f64.size() / (count * components);
  for (std::size_t instance = 0; instance < instances; ++instance) {
    const std::size_t label_at =
        (label != nullptr && label->varies != "none") ? instance * count : 0;
    for (std::size_t i = 0; i < count; ++i) {
      std::int64_t group = 0;
      if (label != nullptr) {
        const std::size_t at = label_at + i;
        group = at < label->data.i64.size() ? label->data.i64[at] : 0;
      }
      Accumulator& into = groups[group];
      for (std::size_t c = 0; c < components; ++c) {
        const std::size_t at =
            (instance * count + i) * components + c;
        if (at >= a.data.f64.size()) continue;
        const double v = a.data.f64[at];
        if (!std::isfinite(v)) {
          ++into.missing;
          continue;
        }
        ++into.count;
        into.sum += v;
        into.sum_squares += v * v;
        into.minimum = std::min(into.minimum, v);
        into.maximum = std::max(into.maximum, v);
      }
    }
  }
  if (groups.empty()) groups[0] = Accumulator();

  FieldStatistics out;
  out.units = a.units.value_or("");
  if (label != nullptr) out.group_by = by;
  const CategoryTable* table =
      (label != nullptr && label->category.has_value())
          ? d.category(*label->category)
          : nullptr;
  for (const auto& entry : groups) {
    if (label != nullptr) {
      const std::int64_t at = entry.first;
      if (table != nullptr && at >= 0 &&
          static_cast<std::size_t>(at) < table->entries.size()) {
        out.groups.push_back(table->entries[static_cast<std::size_t>(at)]);
      } else {
        // A label with no table is its own category (section 3).
        out.groups.push_back(internal::format_i64(at));
      }
    }
    const Accumulator& acc = entry.second;
    const double n = static_cast<double>(acc.count);
    const double mean = acc.count == 0 ? 0.0 : acc.sum / n;
    double variance = 0.0;
    if (acc.count != 0) {
      variance = acc.sum_squares / n - mean * mean;
      if (variance < 0.0) variance = 0.0;   // rounding, not negativity
    }
    out.count.push_back(acc.count);
    out.missing.push_back(acc.missing);
    out.minimum.push_back(acc.count == 0 ? 0.0 : acc.minimum);
    out.mean.push_back(mean);
    out.maximum.push_back(acc.count == 0 ? 0.0 : acc.maximum);
    out.deviation.push_back(std::sqrt(variance));
  }
  return out;
}

Prediction prediction(const Dataset& d, const std::string& slot,
                      const KeysTable* keys) {
  // A scalar by name or by path, else an array as the other helpers
  // find one.
  const Scalar* scalar = nullptr;
  for (const Scalar& s : d.scalars) {
    if (s.name == slot || "/scalars/" + s.name == slot) scalar = &s;
  }
  Found found;
  if (scalar == nullptr) found = find_slot(d, "prediction", slot);

  const std::optional<std::string>& statistic =
      scalar != nullptr ? scalar->statistic : found.slot->statistic;
  const std::optional<std::string>& of =
      scalar != nullptr ? scalar->of : found.slot->of;
  const std::string s = statistic.value_or("value");
  if (s == "band") {
    refuse("prediction", "\"" + slot + "\" is the band of \"" +
                             of.value_or("") +
                             "\"; name the base slot and the band comes "
                             "with it");
  }
  if (s != "value" && s != "mean") {
    refuse("prediction", "\"" + slot + "\" holds the " + s + " of \"" +
                             of.value_or("") +
                             "\", which is stored data about stored data "
                             "and not a prediction; name the base slot");
  }

  const bool is_callable =
      scalar != nullptr ? scalar->is_callable() : found.slot->is_callable();
  const std::string where =
      scalar != nullptr ? "/scalars/" + scalar->name
                        : slot_path(*found.support, *found.slot);
  if (is_callable) {
    const std::string id =
        scalar != nullptr ? scalar->callable_id() : found.slot->callable_id();
    const std::string output =
        scalar != nullptr ? scalar->output.value_or(scalar->name)
                          : found.slot->output.value_or(found.slot->name);
    return served(d, id, output, where, keys);
  }
  if (keys != nullptr) {
    refuse("prediction", "\"" + slot + "\" holds stored data, which has "
                             "values on its own rows only; pass no keys "
                             "table, or name a slot a callable serves");
  }

  Prediction record;
  if (scalar != nullptr) {
    record.mean.dtype = DType::Float64;
    record.mean.shape = {scalar->values.size()};
    record.mean.dims = {"row"};
    record.mean.f64 = scalar->values;
    for (const Scalar& other : d.scalars) {
      if (other.statistic.value_or("") == "band" &&
          other.of.value_or("") == scalar->name && !other.is_callable()) {
        Array band;
        band.dtype = DType::Float64;
        band.shape = {other.values.size()};
        band.dims = {"row"};
        band.f64 = other.values;
        record.uncertainty = std::move(band);
        record.level = other.level;
        record.method = other.method;
        break;
      }
    }
  } else {
    record.mean = found.slot->data;
    const std::vector<ArraySlot>& siblings =
        found.where == Location::Node ? found.support->node_arrays
                                      : found.support->cell_arrays;
    for (const ArraySlot& other : siblings) {
      if (other.statistic.value_or("") == "band" &&
          other.of.value_or("") == found.slot->name && !other.is_callable()) {
        record.uncertainty = other.data;
        record.level = other.level;
        record.method = other.method;
        break;
      }
    }
  }
  record.check(where);
  return record;
}

}  // namespace mestra
