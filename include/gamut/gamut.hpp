// The C++ interface: the C interface of gamut.h in C++ terms, header-only.
//
// A Study owns an open file and closes it when it goes out of scope; a
// failure throws gamut::Error with the rule of spec section 16, the path of
// what it concerns and a message.  Names follow the Python package
// (create, open, add_run, get_field, select, describe), positions count
// from 0, and arrays come back in C order.  Model files, notes and the
// other calls this header does not cover are reached through gamut.h,
// with Study::handle() for the open file.
#ifndef GAMUT_HPP
#define GAMUT_HPP

#include <gamut/gamut.h>

#include <algorithm>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace gamut {

// A refused call: what gamut_error holds.
class Error : public std::runtime_error {
 public:
  explicit Error(const gamut_error& e)
      : std::runtime_error(e.rule[0] ? std::string(e.rule) + ": " + e.message : std::string(e.message)),
        rule_(e.rule), path_(e.path) {}
  Error(const std::string& rule, const std::string& message)
      : std::runtime_error(rule.empty() ? message : rule + ": " + message), rule_(rule) {}
  const std::string& rule() const noexcept { return rule_; }   // "E7", or empty
  const std::string& path() const noexcept { return path_; }   // "node_fields/p", or empty

 private:
  std::string rule_, path_;
};

namespace detail {

inline void check(int status, const gamut_error& e) {
  if (status != 0) throw Error(e);
}

inline const char* or_null(const std::string& s) { return s.empty() ? nullptr : s.c_str(); }

// Owns a list of strings from the library until it goes out of scope.
struct Strings {
  gamut_strings* s = nullptr;
  Strings() = default;
  Strings(const Strings&) = delete;
  Strings& operator=(const Strings&) = delete;
  ~Strings() { gamut_strings_free(s); }
  std::vector<std::string> take() const {
    std::vector<std::string> out;
    for (int64_t i = 0; i < gamut_strings_count(s); ++i) out.emplace_back(gamut_strings_get(s, i));
    return out;
  }
};

// The limit of docs/security.md on the rows a selection scans, checked here
// too so that a buffer the core would refuse is not allocated first.  (The
// core checks a read's size in gamut_shape, before any buffer exists.)
constexpr int64_t kMaxRowsSelected = int64_t(1) << 27;

inline std::vector<const char*> pointers(const std::vector<std::string>& items) {
  std::vector<const char*> out;
  for (const std::string& s : items) out.push_back(s.c_str());
  return out;
}

template <class T> constexpr int dtype();
template <> constexpr int dtype<double>() { return GAMUT_FLOAT64; }
template <> constexpr int dtype<float>() { return GAMUT_FLOAT32; }
template <> constexpr int dtype<int64_t>() { return GAMUT_INT64; }
template <> constexpr int dtype<int32_t>() { return GAMUT_INT32; }
template <> constexpr int dtype<uint8_t>() { return GAMUT_UINT8; }
template <> constexpr int dtype<int8_t>() { return GAMUT_INT8; }

}  // namespace detail

// Rows, nodes or cells to read: everything (the default, gamut::all, or {}),
// a range [start, stop), or strictly increasing positions ({0, 4, 9}; an
// empty vector of positions selects nothing).
class Selection {
 public:
  Selection() = default;
  Selection(std::initializer_list<int64_t> positions) : kind_(GAMUT_SEL_INDEX), index_(positions) {}
  Selection(std::vector<int64_t> positions) : kind_(GAMUT_SEL_INDEX), index_(std::move(positions)) {}
  static Selection range(int64_t start, int64_t stop) {
    Selection s;
    s.kind_ = GAMUT_SEL_RANGE;
    s.start_ = start;
    s.stop_ = stop;
    return s;
  }
  // The selection in the C interface's terms, valid while this one lives.
  gamut_sel c() const { return {kind_, start_, stop_, index_.data(), static_cast<int64_t>(index_.size())}; }

 private:
  int kind_ = GAMUT_SEL_ALL;
  int64_t start_ = 0, stop_ = 0;
  std::vector<int64_t> index_;
};

inline const Selection all{};

// What a read returns: values in C order and their shape (runs x nodes for
// a field on a shared mesh).
template <class T>
struct Array {
  std::vector<int64_t> shape;
  std::vector<T> values;
  T operator[](size_t i) const { return values[i]; }
  T operator()(int64_t i, int64_t j) const { return values[static_cast<size_t>(i * shape.at(1) + j)]; }
  size_t size() const { return values.size(); }
  typename std::vector<T>::const_iterator begin() const { return values.begin(); }
  typename std::vector<T>::const_iterator end() const { return values.end(); }
};

// Cells in VTK's convention: a type per cell, where each cell's nodes start
// in connectivity (one more entry than cells), and node numbers from 0.
struct Cells {
  std::vector<uint8_t> types;
  std::vector<int64_t> offsets, connectivity;
};

using MeshLabels = std::map<std::string, std::vector<int64_t>>;

// A run's own geometry, when it changes from run to run or from one group
// member to the next: points as nodes x axes in C order.
struct Geometry {
  std::vector<double> points;
  std::optional<Cells> cells;
  MeshLabels labels;
};

// What describes a result (spec section 6), from Study::related.
struct Related {
  std::string std_dev;                              // its standard deviation, or ""
  std::map<double, std::string> quantiles;          // by q
  std::map<std::string, std::string> derivatives;   // by what each is taken with respect to;
                                                    // "coordinates:x" for node position along x
  std::vector<std::string> vector;                  // the parts of its vector, itself among them
};

// A result's relation to another (spec section 6), made by std_of,
// quantile_of or derivative_of.
struct Relation {
  std::string of, statistic;
  std::optional<double> q;
  std::string with_respect_to, axis;
};
// The standard deviation of `of`.
inline Relation std_of(const std::string& of) { return {of, "std", std::nullopt, "", ""}; }
// The q quantile of `of`, 0 < q < 1.
inline Relation quantile_of(const std::string& of, double q) { return {of, "quantile", q, "", ""}; }
// The derivative of `of` with respect to a parameter, or to "coordinates"
// along an axis ("x", "y", "z").
inline Relation derivative_of(const std::string& of, const std::string& with_respect_to,
                              const std::string& axis = "") {
  return {of, "", std::nullopt, with_respect_to, axis};
}

// A run's parameters and scalars as numbers (integers stay integers), its
// labels by name.
using Values = std::map<std::string, std::variant<double, int64_t, std::string>>;
// Many runs at once: a column per name, one entry per run.
using Columns = std::map<std::string, std::variant<std::vector<double>, std::vector<int64_t>,
                                                   std::vector<std::string>>>;
// A run's fields, one value per node or cell (for add_runs, every run's
// values one after another).
using Fields = std::map<std::string, std::vector<double>>;

class Study;
Study create(const std::string& path, const std::string& writer, const std::string& mesh = "",
             const std::string& per = "");
Study open(const std::string& path, const std::string& mode = "r", int threads = 1);

// A file open to write (from create, or open(path, "a")) or to read.
class Study {
 public:
  Study(Study&& other) noexcept { *this = std::move(other); }
  Study& operator=(Study&& other) noexcept {
    if (this != &other) {
      finish();
      f_ = std::exchange(other.f_, nullptr);
      writing_ = other.writing_;
      group_ = std::move(other.group_);
      axes_ = other.axes_;
    }
    return *this;
  }
  Study(const Study&) = delete;
  Study& operator=(const Study&) = delete;
  // Closes the file; a writer whose close is refused (a shared mesh never
  // set) is discarded, and a file it created is removed.  Call close() to
  // see the refusal instead.
  ~Study() { finish(); }

  // Finishes the file.  A refused close keeps it open to fix and close again.
  void close() {
    if (!f_) return;
    gamut_error e{};
    detail::check(gamut_close(f_, &e), e);
    f_ = nullptr;
  }
  // Gives up on the file without finishing it; with remove, deletes a file
  // this study created (a file opened to append is never deleted).
  void abandon(bool remove = true) noexcept {
    if (f_) gamut_abandon(std::exchange(f_, nullptr), remove ? 1 : 0);
  }
  gamut_file* handle() const { return f_; }

  // --- writing -----------------------------------------------------------

  void declare_coordinates(const std::string& units, int axes) {
    gamut_error e{};
    detail::check(gamut_declare_coordinates(need_writer(), units.c_str(), GAMUT_AS_GIVEN, axes, "",
                                            "", &e), e);
    axes_ = axes;
  }
  // role: "design", "condition" or "time"; run_group names the label that
  // groups a time parameter's rows into runs. T is double, or int64_t for
  // whole numbers such as a count or a seed: declare_parameter<int64_t>(...).
  template <class T = double>
  void declare_parameter(const std::string& name, const std::string& role, const std::string& units,
                         const std::string& run_group = "") {
    static_assert(std::is_same_v<T, double> || std::is_same_v<T, int64_t>,
                  "a parameter is double or int64_t");
    gamut_error e{};
    detail::check(gamut_declare_parameter(need_writer(), name.c_str(), role.c_str(), units.c_str(),
                                          detail::dtype<T>(), 0, 0.0, 0.0, run_group.c_str(), &e), e);
  }
  // With the bounds the values lie in (a model file's domain).
  template <class T = double>
  void declare_parameter(const std::string& name, const std::string& role, const std::string& units,
                         double lower, double upper, const std::string& run_group = "") {
    static_assert(std::is_same_v<T, double> || std::is_same_v<T, int64_t>,
                  "a parameter is double or int64_t");
    gamut_error e{};
    detail::check(gamut_declare_parameter(need_writer(), name.c_str(), role.c_str(), units.c_str(),
                                          detail::dtype<T>(), 1, lower, upper, run_group.c_str(), &e), e);
  }
  // role: "categorical", "status", "group" or "split"; without categories
  // the table grows as names appear.
  void declare_label(const std::string& name, const std::string& role,
                     const std::vector<std::string>& categories = {}) {
    gamut_error e{};
    const std::vector<const char*> c = detail::pointers(categories);
    detail::check(gamut_declare_label(need_writer(), name.c_str(), role.c_str(), c.data(),
                                      static_cast<int64_t>(c.size()), &e), e);
  }
  void declare_scalar(const std::string& name, const std::string& units, const Relation& relation = {}) {
    declare_result(name, "scalar", units, relation);
  }
  // at: "node" or "cell".
  void declare_field(const std::string& name, const std::string& at, const std::string& units,
                     const Relation& relation = {}) {
    declare_result(name, at, units, relation);
  }
  void declare_mesh_label(const std::string& name, const std::string& at,
                          const std::vector<std::string>& categories) {
    gamut_error e{};
    const std::vector<const char*> c = detail::pointers(categories);
    detail::check(gamut_declare_mesh_label(need_writer(), name.c_str(), at.c_str(), c.data(),
                                           static_cast<int64_t>(c.size()), &e), e);
  }
  void set_constant(const std::string& name, double value, const std::string& units) {
    gamut_error e{};
    detail::check(gamut_set_constant(need_writer(), name.c_str(), units.c_str(), GAMUT_FLOAT64, value, 0,
                                     &e), e);
  }
  // title, license, references, source or portion_marking.
  void set_attribute(const std::string& name, const std::string& value) {
    gamut_error e{};
    detail::check(gamut_set_attribute(need_writer(), name.c_str(), value.c_str(), &e), e);
  }
  void set_generalisation_group(const std::string& label) {
    gamut_error e{};
    detail::check(gamut_set_generalisation_group(need_writer(), label.c_str(), &e), e);
  }

  // A shared mesh: points (nodes x axes, C order), cells and fixed mesh
  // labels, when the geometry is fixed.
  void set_mesh(const std::vector<double>& points, const Cells& cells, const MeshLabels& labels = {}) {
    gamut_error e{};
    detail::check(gamut_geometry_begin(need_writer(), &e), e);
    stage(points, &cells, labels);
    detail::check(gamut_set_mesh(f_, &e), e);
  }
  // A shared mesh whose coordinates come with the runs: its node count.
  void set_mesh(int64_t n_nodes, const Cells& cells, const MeshLabels& labels = {}) {
    gamut_error e{};
    detail::check(gamut_geometry_begin(need_writer(), &e), e);
    detail::check(gamut_geometry_points(f_, GAMUT_FLOAT64, nullptr, 0, n_nodes, axes_, &e), e);
    stage({}, &cells, labels);
    detail::check(gamut_set_mesh(f_, &e), e);
  }

  // Adds one run, all or nothing; returns its id.
  int64_t add_run(const Values& values, const Fields& fields = {},
                  const std::optional<Geometry>& geometry = std::nullopt) {
    gamut_error e{};
    detail::check(gamut_batch_begin(need_writer(), 1, &e), e);
    std::optional<std::string> member;
    for (const auto& [name, value] : values) {
      if (const double* number = std::get_if<double>(&value)) {
        detail::check(gamut_batch_values(f_, name.c_str(), GAMUT_FLOAT64, number, 0, 1, &e), e);
      } else if (const int64_t* integer = std::get_if<int64_t>(&value)) {
        detail::check(gamut_batch_values(f_, name.c_str(), GAMUT_INT64, integer, 0, 1, &e), e);
      } else {
        const char* label = std::get<std::string>(value).c_str();
        detail::check(gamut_batch_names(f_, name.c_str(), &label, 1, &e), e);
        if (name == group_) member = std::get<std::string>(value);
      }
    }
    stage_fields(fields);
    if (geometry) {
      if (!group_.empty() && !member)
        throw Error("E2", "give " + group_ + " by name so the geometry belongs to its member");
      detail::check(gamut_geometry_begin(f_, &e), e);
      stage(geometry->points, geometry->cells ? &*geometry->cells : nullptr, geometry->labels);
      detail::check(group_.empty() ? gamut_batch_geometry_for_row(f_, &e)
                                   : gamut_batch_geometry_for_member(f_, member->c_str(), &e), e);
    }
    int64_t id = 0;
    detail::check(gamut_batch_commit(f_, &id, &e), e);
    return id;
  }

  // Adds many runs at once, all or nothing, on a mesh whose geometry is
  // fixed or set already; returns their ids.
  std::vector<int64_t> add_runs(const Columns& columns, const Fields& fields = {}) {
    if (columns.empty()) throw Error("E5", "add_runs needs at least one column");
    int64_t n = -1;
    for (const auto& [name, column] : columns) {
      const int64_t m = std::visit([](const auto& v) { return static_cast<int64_t>(v.size()); }, column);
      if (n >= 0 && m != n) throw Error("E5", "every column needs the same number of runs; " + name + " has " +
                                              std::to_string(m) + ", not " + std::to_string(n));
      n = m;
    }
    gamut_error e{};
    detail::check(gamut_batch_begin(need_writer(), n, &e), e);
    for (const auto& [name, column] : columns) {
      if (const auto* numbers = std::get_if<std::vector<double>>(&column)) {
        detail::check(gamut_batch_values(f_, name.c_str(), GAMUT_FLOAT64, numbers->data(), 0, n, &e), e);
      } else if (const auto* integers = std::get_if<std::vector<int64_t>>(&column)) {
        detail::check(gamut_batch_values(f_, name.c_str(), GAMUT_INT64, integers->data(), 0, n, &e), e);
      } else {
        const std::vector<const char*> names = detail::pointers(std::get<std::vector<std::string>>(column));
        detail::check(gamut_batch_names(f_, name.c_str(), names.data(), n, &e), e);
      }
    }
    stage_fields(fields);
    std::vector<int64_t> ids(static_cast<size_t>(n));   // before the commit: nothing can fail after it
    int64_t first = 0;
    detail::check(gamut_batch_commit(f_, &first, &e), e);
    for (int64_t i = 0; i < n; ++i) ids[static_cast<size_t>(i)] = first + i;
    return ids;
  }

  // --- reading -----------------------------------------------------------

  int64_t row_count() const { return std::stoll(info("row_count")); }
  // "table", "shared" or "changing".
  std::string type() const { return info("type"); }
  // group: "parameters", "labels", "scalars", "constants", "node_fields",
  // "cell_fields", "node_labels", "cell_labels".
  std::vector<std::string> names(const std::string& group) const {
    gamut_error e{};
    detail::Strings s;
    detail::check(gamut_names(need_reader(), group.c_str(), &s.s, &e), e);
    return s.take();
  }
  // What the file says about a name, or with no name about itself.
  std::map<std::string, std::string> describe(const std::string& name = "") const {
    gamut_error e{};
    detail::Strings k, v;
    detail::check(gamut_describe(need_reader(), name.c_str(), &k.s, &v.s, &e), e);
    const std::vector<std::string> keys = k.take(), values = v.take();
    std::map<std::string, std::string> out;
    for (size_t i = 0; i < keys.size(); ++i) out[keys[i]] = values[i];
    return out;
  }
  // What describes a result: its std, quantiles, derivatives and vector.
  Related related(const std::string& name) const {
    gamut_error e{};
    detail::Strings t, k, n;
    detail::check(gamut_related(need_reader(), name.c_str(), &t.s, &k.s, &n.s, &e), e);
    const std::vector<std::string> kinds = t.take(), keys = k.take(), names = n.take();
    Related out;
    for (size_t i = 0; i < kinds.size(); ++i) {
      if (kinds[i] == "std") out.std_dev = names[i];
      else if (kinds[i] == "quantile") out.quantiles[std::stod(keys[i])] = names[i];
      else if (kinds[i] == "derivative") out.derivatives[keys[i]] = names[i];
      else if (kinds[i] == "vector") out.vector.push_back(names[i]);
    }
    return out;
  }
  // The category table of a label or mesh label: code c names entry c.
  std::vector<std::string> categories(const std::string& name) const {
    const std::map<std::string, std::string> d = describe(name);
    const auto table = d.find("category");
    if (table == d.end() || table->second.empty())
      throw Error("", name + " has no category table; its codes are its values");
    gamut_error e{};
    detail::Strings s;
    detail::check(gamut_table(f_, table->second.c_str(), &s.s, &e), e);
    return s.take();
  }
  // The positions of the rows a condition selects ("mach > 0.7 and
  // status == converged"), in increasing order.
  std::vector<int64_t> select(const std::string& where) const {
    // Room for every row up to the core's cap; past it the core refuses (E26)
    // before writing any, so no buffer is sized from the file's count.
    const int64_t rows = row_count();
    std::vector<int64_t> out(static_cast<size_t>(rows > 0 && rows <= detail::kMaxRowsSelected ? rows : 1));
    int64_t n = 0;
    gamut_error e{};
    detail::check(gamut_select(f_, where.c_str(), out.data(), static_cast<int64_t>(out.size()), &n, &e), e);
    out.resize(static_cast<size_t>(n));
    return out;
  }

  // A field as rows x nodes (or cells); a changing mesh's, one row at a time.
  Array<double> get_field(const std::string& name, const Selection& rows = all,
                          const Selection& sites = all) const {
    return read<double>(name, rows, sites);
  }
  // A parameter in the type it is stored as: get_parameter<double> for a
  // float64 one, get_parameter<int64_t> for one declared int64. Another type
  // is refused rather than converted, which would round or truncate.
  template <class T>
  std::vector<T> get_parameter(const std::string& name, const Selection& rows = all) const {
    stored_as<T>(name);
    return read<T>(name, rows, all).values;
  }
  std::vector<double> get_scalar(const std::string& name, const Selection& rows = all) const {
    return read<double>(name, rows, all).values;
  }
  std::vector<std::string> get_label(const std::string& name, const Selection& rows = all) const {
    gamut_error e{};
    detail::Strings s;
    const gamut_sel r = rows.c();
    detail::check(gamut_label_names(need_reader(), name.c_str(), &r, &s.s, &e), e);
    return s.take();
  }
  // How far each row's value of a parameter lies outside the bounds the
  // file declares for it, in its units: 0 inside or on a bound, value -
  // lower below, value - upper above, NaN where the value is missing.  A
  // parameter without bounds is refused.
  std::vector<double> outside(const std::string& name, const Selection& rows = all) const {
    gamut_error e{};
    const gamut_sel r = rows.c();
    int64_t shape[4] = {0, 0, 0, 0};
    int rank = 0;
    detail::check(gamut_shape(need_reader(), name.c_str(), &r, nullptr, &rank, shape, 4, &e), e);
    std::vector<double> out(rank == 1 ? static_cast<size_t>(shape[0]) : 0);
    detail::check(gamut_outside(f_, name.c_str(), &r, out.data(),
                                static_cast<int64_t>(out.size() * sizeof(double)), &e),
                  e);
    return out;
  }
  // A constant in its type, as get_parameter: double (float32 widens
  // exactly) or int64_t.
  template <class T>
  T get_constant(const std::string& name) const {
    stored_as<T>(name);
    return read<T>(name, all, all).values.at(0);
  }
  std::vector<int64_t> get_row_ids(const Selection& rows = all) const {
    return read<int64_t>("row", rows, all).values;
  }
  // The points a run used (nodes x axes); no row for a fixed geometry.
  Array<double> get_points(std::optional<int64_t> row = std::nullopt) const {
    if (const std::string per = info("per"); !row && per != "fixed" && !per.empty()) throw Error("", "this mesh's geometry changes; give the row");
    Array<double> a = read<double>("coordinates", one(row), all);
    if (row && a.shape.size() == 3) a.shape.erase(a.shape.begin());   // the one row asked for
    return a;
  }
  Cells get_cells(std::optional<int64_t> row = std::nullopt) const {
    return {read<uint8_t>("cells/types", one(row), all).values,
            read<int64_t>("cells/offsets", one(row), all).values,
            read<int64_t>("cells/connectivity", one(row), all).values};
  }
  std::vector<int64_t> get_mesh_label(const std::string& name,
                                      std::optional<int64_t> row = std::nullopt) const {
    return read<int64_t>(name, one(row), all).values;
  }
  // Any name, as any element type: the general read the others use.
  template <class T>
  Array<T> read(const std::string& name, const Selection& rows, const Selection& sites) const {
    gamut_error e{};
    const gamut_sel r = rows.c(), s = sites.c();
    int64_t shape[4] = {0, 0, 0, 0};
    int rank = 0;
    detail::check(gamut_shape(need_reader(), name.c_str(), &r, &s, &rank, shape, 4, &e), e);
    Array<T> a;
    a.shape.assign(shape, shape + rank);
    int64_t n = 1;
    for (int64_t d : a.shape) n *= d;
    const int64_t bytes = n * static_cast<int64_t>(sizeof(T));
    a.values.resize(static_cast<size_t>(n));
    detail::check(gamut_read(f_, name.c_str(), &r, &s, detail::dtype<T>(), a.values.data(), bytes, &e), e);
    return a;
  }
  // Decompresses field reads in that many threads.
  void set_threads(int threads) {
    gamut_error e{};
    detail::check(gamut_set_threads(need_reader(), threads, &e), e);
  }

 private:
  friend Study create(const std::string&, const std::string&, const std::string&, const std::string&);
  friend Study open(const std::string&, const std::string&, int);
  Study(gamut_file* f, bool writing) : f_(f), writing_(writing) {}

  void finish() noexcept {
    if (!f_) return;
    gamut_error e{};
    if (gamut_close(f_, &e) != 0) gamut_abandon(f_, 1);
    f_ = nullptr;
  }
  gamut_file* need_writer() const {
    if (!f_) throw Error("", "the file is closed");
    if (!writing_) throw Error("", "the file was opened to read; add runs to a file from gamut::create "
                                   "or gamut::open(path, \"a\")");
    return f_;
  }
  gamut_file* need_reader() const {
    if (!f_) throw Error("", "the file is closed");
    if (writing_) throw Error("", "the file is open to write; close it and open it with gamut::open to read");
    return f_;
  }
  std::string info(const char* key) const {
    gamut_error e{};
    detail::Strings s;
    detail::check(gamut_info(need_reader(), key, &s.s, &e), e);
    const std::vector<std::string> v = s.take();
    return v.empty() ? std::string() : v[0];
  }
  static Selection one(std::optional<int64_t> row) { return row ? Selection{*row} : Selection{}; }
  void declare_result(const std::string& name, const std::string& where, const std::string& units,
                      const Relation& r) {
    gamut_error e{};
    detail::check(gamut_declare_result(need_writer(), name.c_str(), where.c_str(), units.c_str(),
                                       GAMUT_AS_GIVEN, r.of.c_str(), r.statistic.c_str(), r.q ? 1 : 0,
                                       r.q.value_or(0.0), "", r.with_respect_to.c_str(), r.axis.c_str(), "",
                                       -1, "", "", &e), e);
  }
  // Refuses to read `name` as T unless T holds its stored type exactly.
  template <class T>
  void stored_as(const std::string& name) const {
    static_assert(std::is_same_v<T, double> || std::is_same_v<T, int64_t>,
                  "a parameter or constant is read as double or int64_t");
    const auto d = describe(name);
    const auto it = d.find("dtype");
    const std::string stored = it == d.end() ? "float64" : it->second;
    const bool fits = std::is_same_v<T, int64_t> ? stored == "int64" : stored != "int64";
    if (!fits)
      throw Error("", name + " is stored as " + stored + "; read it as " +
                          (stored == "int64" ? "int64_t" : "double"));
  }
  void stage(const std::vector<double>& points, const Cells* cells, const MeshLabels& labels) {
    gamut_error e{};
    if (!points.empty()) {
      const int64_t count = static_cast<int64_t>(points.size());
      detail::check(gamut_geometry_points(f_, GAMUT_FLOAT64, points.data(), count,
                                          axes_ > 0 ? count / axes_ : 0, axes_, &e), e);
    }
    if (cells)
      detail::check(gamut_geometry_cells(f_, cells->types.data(), static_cast<int64_t>(cells->types.size()),
                                         cells->offsets.data(), static_cast<int64_t>(cells->offsets.size()),
                                         cells->connectivity.data(),
                                         static_cast<int64_t>(cells->connectivity.size()), &e), e);
    for (const auto& [name, values] : labels)
      detail::check(gamut_geometry_label(f_, name.c_str(), values.data(), static_cast<int64_t>(values.size()),
                                         &e), e);
  }

  void stage_fields(const Fields& fields) {
    gamut_error e{};
    for (const auto& [name, field] : fields)
      detail::check(gamut_batch_values(f_, name.c_str(), GAMUT_FLOAT64, field.data(), 0,
                                       static_cast<int64_t>(field.size()), &e), e);
  }

  gamut_file* f_ = nullptr;
  bool writing_ = false;
  std::string group_;   // the label whose members own a geometry (per = "group:<label>")
  int axes_ = 3;
};

// A new data file.  mesh: "" (a table), "shared" or "changing"; per:
// "fixed", "run" or "group:<label>".  Declarations come next, then the
// mesh, then runs.
inline Study create(const std::string& path, const std::string& writer, const std::string& mesh,
                    const std::string& per) {
  gamut_error e{};
  gamut_file* f = nullptr;
  detail::check(gamut_create(path.c_str(), writer.c_str(), detail::or_null(mesh), detail::or_null(per), &f, &e),
                e);
  Study s(f, true);
  if (per.rfind("group:", 0) == 0) s.group_ = per.substr(6);
  return s;
}

// Opens a file to read (mode "r") or to add runs in place (mode "a").
inline Study open(const std::string& path, const std::string& mode, int threads) {
  gamut_error e{};
  gamut_file* f = nullptr;
  if (mode == "r") {
    detail::check(gamut_open(path.c_str(), &f, &e), e);
    Study s(f, false);
    if (threads != 1) s.set_threads(threads);
    return s;
  }
  if (mode != "a") throw Error("", "mode \"" + mode + "\" is \"r\" or \"a\"");
  std::string per;
  int axes = 3;
  {
    const Study reader = open(path, "r");
    per = reader.info("per");
    if (!reader.info("mesh_kind").empty()) {
      const std::map<std::string, std::string> c = reader.describe("coordinates");
      const auto found = c.find("axes");
      if (found != c.end()) axes = std::stoi(found->second);
    }
  }
  detail::check(gamut_open_append(path.c_str(), &f, &e), e);
  Study s(f, true);
  if (per.rfind("group:", 0) == 0) s.group_ = per.substr(6);
  s.axes_ = axes;
  return s;
}

// Adds src's runs to dst in place; returns how many.
inline int64_t append(const std::string& dst, const std::string& src) {
  gamut_error e{};
  int64_t n = 0;
  detail::check(gamut_append(dst.c_str(), src.c_str(), &n, &e), e);
  return n;
}
// Writes the chosen runs of src as a new file, their ids kept.
inline void extract(const std::string& src, const std::string& dst, const Selection& rows) {
  gamut_error e{};
  const gamut_sel r = rows.c();
  detail::check(gamut_extract(src.c_str(), dst.c_str(), &r, &e), e);
}
// Rewrites a file with the default layout, keeping its identity.
inline void write_copy(const std::string& src, const std::string& dst) {
  gamut_error e{};
  detail::check(gamut_write_copy(src.c_str(), dst.c_str(), &e), e);
}

struct Finding {
  std::string rule, severity, path, message;
};
struct Report {
  bool ok = true;
  std::vector<Finding> errors, warnings;
};
// Checks a file against the rules of the specification.
inline Report validate(const std::string& path) {
  gamut_error e{};
  gamut_report* r = nullptr;
  detail::check(gamut_validate(path.c_str(), &r, &e), e);
  struct Free {
    gamut_report* r;
    ~Free() { gamut_report_free(r); }
  } owner{r};
  Report out;
  for (int64_t i = 0; i < gamut_report_count(r); ++i) {
    const char *rule = "", *severity = "", *where = "", *message = "";
    gamut_report_get(r, i, &rule, &severity, &where, &message);
    Finding f{rule ? rule : "", severity ? severity : "", where ? where : "", message ? message : ""};
    (f.severity == "error" ? out.errors : out.warnings).push_back(std::move(f));
  }
  out.ok = out.errors.empty();
  return out;
}

inline std::string version() { return gamut_version(); }
inline std::string format() { return gamut_format(); }

}  // namespace gamut

#endif  // GAMUT_HPP
