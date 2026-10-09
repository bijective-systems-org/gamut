#include "mestra/evaluate.hpp"

#include <cstdlib>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>

#include "mestra/affine.hpp"
#include "mestra/io.hpp"
#include "names.hpp"

namespace mestra {
namespace {

// The types this package itself defines.  A static library drops an
// object file nothing references, so the registration is a call and
// not a static initialiser.
void ensure_builtin_types() {
  static const bool once = [] {
    Affine::register_type();
    return true;
  }();
  (void)once;
}

// Section 10: which part of the record fills a slot is its statistic.
// A band slot takes the uncertainty and, with it, the level and the
// method the record states.
const Array& part_of(const Prediction& record,
                     const std::optional<std::string>& statistic,
                     const std::string& where, std::optional<double>* level,
                     std::optional<std::string>* method) {
  const std::string s = statistic.value_or("value");
  if (s == "band") {
    if (!record.uncertainty.has_value()) {
      throw Error("E12", "the band slot \"" + where +
                             "\" takes the uncertainty of its output and "
                             "the callable returned none; a band without a "
                             "level cannot be stored, so drop the slot or "
                             "give the model a band");
    }
    *level = record.level;
    *method = record.method;
    return *record.uncertainty;
  }
  if (s == "value" || s == "mean") return record.mean;
  throw Error("E12", "a callable serves value, mean and band slots; \"" +
                         where + "\" is " + s);
}

void materialise(ArraySlot* slot, const Prediction& record,
                 const std::string& where) {
  const Array& produced =
      part_of(record, slot->statistic, where, &slot->level, &slot->method);
  if (produced.dims.empty() || produced.dims.front() != "row") {
    throw Error("", "the callable filling \"" + where +
                        "\" returned no row dimension");
  }
  slot->data = produced;
  slot->source = "data";
  slot->output.reset();
  const int comp = slot->data.axis("component");
  if (comp >= 0) {
    slot->components =
        static_cast<std::int64_t>(slot->data.shape[
            static_cast<std::size_t>(comp)]);
  }
  slot->varies = "row";
}

}  // namespace

KeysTable empty_keys_table(const Dataset& d) {
  KeysTable t;
  for (const std::string& name : d.key_order()) {
    const Key* k = d.key(name);
    if (k != nullptr && k->role == "id" && k->dtype == DType::String) {
      t.add_text_column(name, {});
    } else {
      t.add_column(name, {});
    }
  }
  return t;
}

Dataset evaluate(const Dataset& d, const KeysTable& keys) {
  ensure_builtin_types();
  const std::size_t rows = keys.rows();

  Dataset out;
  out.format = d.format;
  out.writer = d.writer;
  out.created = d.created;
  out.aligned = d.aligned;
  out.generalisation_group = d.generalisation_group;
  out.n_rows = static_cast<std::int64_t>(rows);
  out.categories = d.categories;
  out.container_groups = d.container_groups;
  // Conventions section 7: evaluating turns every callable slot into
  // a stored slot, so the result has no callable to keep and the
  // /callables group is absent from it, not present and empty.  It is
  // the same rule as section 13's container groups, and it is what
  // makes the four writers' evaluated files identical.
  out.container_groups.erase("/callables");
  out.root_extra = d.root_extra;
  out.notes = d.notes;
  out.has_notes = d.has_notes;

  // The key columns become the table the file was evaluated on.
  for (const Key& k : d.keys) {
    Key n = k;
    n.f64.clear();
    n.i64.clear();
    n.str.clear();
    if (keys.has(k.name)) {
      if (k.dtype == DType::String) {
        n.str = keys.text_column(k.name);
      } else if (k.dtype == DType::Float64) {
        n.f64 = keys.column(k.name);
      } else {
        for (const double v : keys.column(k.name)) {
          n.i64.push_back(static_cast<std::int64_t>(v));
        }
      }
    } else {
      throw Error("", "the keys table has no column for the key \"" +
                          k.name + "\"");
    }
    out.keys.push_back(std::move(n));
  }

  // Every callable the file holds is built once through the registry
  // and called once, however many slots it serves.
  std::map<std::string, Outputs, BytesLess> produced;
  for (const StoredCallable& c : d.callables) {
    const std::unique_ptr<Callable> object =
        CallableRegistry::from_dict(c.type, c.dict);
    if (!object) {
      throw Error("", "no factory is registered for the callable type \"" +
                          c.type + "\"; the dictionary may be copied but "
                                   "not interpreted. " + internal::kRegisterHint);
    }
    produced[c.id] = object->call(keys);
  }

  auto outputs_for = [&](const std::string& id, const std::string& output,
                         const std::string& where) -> const Prediction& {
    const auto it = produced.find(id);
    if (it == produced.end()) {
      throw Error("E14", "the slot \"" + where + "\" names the callable \"" +
                             id + "\", which the file does not hold");
    }
    return it->second.at(output);
  };

  out.scalars = d.scalars;
  for (Scalar& s : out.scalars) {
    if (!s.is_callable()) {
      if (s.values.size() != rows) s.values.assign(rows, 0.0);
      continue;
    }
    const std::string output = s.output.value_or(s.name);
    const std::string where = "/scalars/" + s.name;
    const Prediction& record = outputs_for(s.callable_id(), output, where);
    s.values = part_of(record, s.statistic, where, &s.level, &s.method).f64;
    s.source = "data";
    s.output.reset();
  }

  out.supports = d.supports;
  for (Support& support : out.supports) {
    if (support.coordinates.has_value() && support.coordinates->is_callable()) {
      ArraySlot& c = *support.coordinates;
      const std::string where = "/supports/" + support.name + "/coordinates";
      const std::string output = c.output.value_or(c.name);
      materialise(&c, outputs_for(c.callable_id(), output, where), where);
    }
    for (int which = 0; which < 2; ++which) {
      std::vector<ArraySlot>& slots =
          which == 0 ? support.node_arrays : support.cell_arrays;
      for (ArraySlot& slot : slots) {
        if (!slot.is_callable()) continue;
        const std::string where = "/supports/" + support.name +
                                  (which == 0 ? "/node_arrays/"
                                              : "/cell_arrays/") +
                                  slot.name;
        const std::string output = slot.output.value_or(slot.name);
        materialise(&slot, outputs_for(slot.callable_id(), output, where),
                    where);
      }
    }
  }

  if (d.row_support.has_value() && d.row_support->size() == rows) {
    out.row_support = d.row_support;
  }
  return out;
}

KeysTable read_keys_csv(const Dataset& d, const std::string& path) {
  std::ifstream in(path);
  if (!in) throw Error("", "cannot read the keys table \"" + path + "\"");
  std::string line;
  if (!std::getline(in, line)) {
    throw Error("", "the keys table \"" + path + "\" is empty");
  }
  if (!line.empty() && line.back() == '\r') line.pop_back();

  std::vector<std::string> names;
  {
    std::stringstream header(line);
    std::string cell;
    while (std::getline(header, cell, ',')) names.push_back(cell);
  }
  std::vector<std::vector<std::string>> cells(names.size());
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) continue;
    std::stringstream row(line);
    std::string cell;
    std::size_t at = 0;
    while (std::getline(row, cell, ',') && at < cells.size()) {
      cells[at].push_back(cell);
      ++at;
    }
  }

  KeysTable t;
  for (std::size_t i = 0; i < names.size(); ++i) {
    const Key* k = d.key(names[i]);
    if (k != nullptr && k->role == "id" && k->dtype == DType::String) {
      t.add_text_column(names[i], cells[i]);
    } else {
      std::vector<double> values;
      values.reserve(cells[i].size());
      for (const std::string& c : cells[i]) {
        values.push_back(std::strtod(c.c_str(), nullptr));
      }
      t.add_column(names[i], std::move(values));
    }
  }
  return t;
}

}  // namespace mestra
