// The MATLAB gateway to the core: one MEX function dispatching on a command
// name to the C interface.  It converts between MATLAB's column-major arrays
// and the core's C order, keeps a registry of live handles so a stale or
// forged handle is refused rather than dereferenced, and turns every core
// error into a MATLAB error with identifier gamut:<rule>.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "mex.h"
#include "gamut/gamut.h"

namespace {

std::set<std::uintptr_t> g_files;
// Each live evaluation, with the model file it reads: freed before that file
// closes, whatever order MATLAB clears them in.
std::map<std::uintptr_t, std::uintptr_t> g_evaluations;

void free_evaluations_of(std::uintptr_t model) {
  for (auto it = g_evaluations.begin(); it != g_evaluations.end();) {
    if (it->second == model) {
      gamut_evaluation_free(reinterpret_cast<gamut_evaluation*>(it->first));
      it = g_evaluations.erase(it);
    } else {
      ++it;
    }
  }
}

// An error for MATLAB, thrown so the stack unwinds and every guard below
// frees what it holds; mexFunction reports it once nothing is left to free
// (mexErrMsgIdAndTxt itself leaves without running destructors).
struct Refusal {
  std::string id, message;
};

[[noreturn]] void raise(const gamut_error& e) {
  std::string msg = e.message;
  if (e.path[0]) msg = std::string(e.path) + ": " + msg;
  throw Refusal{std::string("gamut:") + (e.rule[0] ? e.rule : "error"), msg};
}

[[noreturn]] void usage(const std::string& why) { throw Refusal{"gamut:usage", why}; }

// Open handles keep the gateway loaded, so clear mex cannot orphan them;
// at exit, each is finished as close would, or abandoned.
void forget(gamut_file* f) {
  g_files.erase(reinterpret_cast<std::uintptr_t>(f));
  if (g_files.empty()) mexUnlock();
}

void finish_open_files() {
  for (const auto& kv : g_evaluations) gamut_evaluation_free(reinterpret_cast<gamut_evaluation*>(kv.first));
  g_evaluations.clear();
  for (const std::uintptr_t p : g_files) {
    gamut_file* f = reinterpret_cast<gamut_file*>(p);
    gamut_error e{};
    if (gamut_close(f, &e) != 0) gamut_abandon(f, 0);
  }
  g_files.clear();
}

void check(int status, const gamut_error& e) {
  if (status != 0) raise(e);
}

// A string scalar ("x.gamut", the usual text since R2017a) as a char row.
mxArray* char_of_string(const mxArray* a, const char* what) {
  if (mxGetNumberOfElements(a) != 1) usage(std::string(what) + " must be one string");
  mxArray* in = const_cast<mxArray*>(a);
  mxArray* out = nullptr;
  if (mexCallMATLABWithTrap(1, &out, 1, &in, "char") != nullptr) usage(std::string(what) + " must be text");
  return out;
}

std::string text(const mxArray* a, const char* what) {
  if (a == nullptr) usage(std::string(what) + " is missing");
  if (mxIsClass(a, "string")) {
    mxArray* c = char_of_string(a, what);
    const std::string out = text(c, what);
    mxDestroyArray(c);
    return out;
  }
  if (mxIsEmpty(a)) return std::string();
  if (!mxIsChar(a)) usage(std::string(what) + " must be text");
  char* s = mxArrayToUTF8String(a);
  std::string out = s == nullptr ? std::string() : std::string(s);
  mxFree(s);
  return out;
}

// Integers given in any numeric class, converted by that class; a value that is
// not a whole number, or out of int64's range, is refused.
std::vector<int64_t> integers(const mxArray* a, const char* what) {
  if (a == nullptr || !mxIsNumeric(a) || mxIsComplex(a) || mxIsSparse(a)) {
    usage(std::string(what) + " must be full integer arrays");
  }
  const mwSize n = mxGetNumberOfElements(a);
  std::vector<int64_t> out(n);
  const void* d = mxGetData(a);
  for (mwSize i = 0; i < n; ++i) {
    switch (mxGetClassID(a)) {
      case mxDOUBLE_CLASS:
      case mxSINGLE_CLASS: {
        const double x = mxGetClassID(a) == mxDOUBLE_CLASS ? static_cast<const double*>(d)[i]
                                                           : static_cast<const float*>(d)[i];
        if (!(x == std::floor(x) && x >= -9.2233720368547758e18 && x < 9.2233720368547758e18)) {
          usage(std::string(what) + " must be whole numbers");
        }
        out[i] = static_cast<int64_t>(x);
        break;
      }
      case mxINT8_CLASS: out[i] = static_cast<const int8_t*>(d)[i]; break;
      case mxUINT8_CLASS: out[i] = static_cast<const uint8_t*>(d)[i]; break;
      case mxINT16_CLASS: out[i] = static_cast<const int16_t*>(d)[i]; break;
      case mxUINT16_CLASS: out[i] = static_cast<const uint16_t*>(d)[i]; break;
      case mxINT32_CLASS: out[i] = static_cast<const int32_t*>(d)[i]; break;
      case mxUINT32_CLASS: out[i] = static_cast<const uint32_t*>(d)[i]; break;
      case mxINT64_CLASS: out[i] = static_cast<const int64_t*>(d)[i]; break;
      case mxUINT64_CLASS: {
        const uint64_t u = static_cast<const uint64_t*>(d)[i];
        if (u > static_cast<uint64_t>(INT64_MAX)) usage(std::string(what) + " are out of range");
        out[i] = static_cast<int64_t>(u);
        break;
      }
      default: usage(std::string(what) + " must be integers");
    }
  }
  return out;
}

// One int64 value, read only when there is exactly one.
int64_t one_int64(const mxArray* v) {
  if (mxGetNumberOfElements(v) != 1) usage("an int64 value is one number");
  return *static_cast<const int64_t*>(mxGetData(v));
}

// One integer of any integer class as int64 (a constant or a note), where a
// double would round a uint64 or int64 past 2^53.
bool is_integer(const mxArray* v) {
  return v != nullptr && (mxIsInt8(v) || mxIsUint8(v) || mxIsInt16(v) || mxIsUint16(v) ||
                          mxIsInt32(v) || mxIsUint32(v) || mxIsInt64(v) || mxIsUint64(v));
}
int64_t one_integer(const mxArray* v) {
  if (mxIsInt64(v)) return one_int64(v);
  if (mxGetNumberOfElements(v) != 1) usage("an integer value is one number");
  if (mxIsUint64(v)) {
    const uint64_t u = *static_cast<const uint64_t*>(mxGetData(v));
    if (u > static_cast<uint64_t>(INT64_MAX))
      throw Refusal{"gamut:E4", std::to_string(u) + " is above int64's range"};
    return static_cast<int64_t>(u);
  }
  return static_cast<int64_t>(mxGetScalar(v));    // int8 to uint32: exact as a double
}

// A model tree, freed on every path out, a thrown usage error included.
struct Tree {
  gamut_tree* t = nullptr;
  Tree() = default;
  Tree(const Tree&) = delete;
  Tree& operator=(const Tree&) = delete;
  ~Tree() {
    if (t != nullptr) gamut_tree_free(t);
  }
};

double scalar(const mxArray* a, const char* what) {
  if (a == nullptr || !mxIsNumeric(a) && !mxIsLogical(a) || mxGetNumberOfElements(a) != 1) {
    usage(std::string(what) + " must be a number");
  }
  return mxGetScalar(a);
}

gamut_file* file(const mxArray* a) {
  if (a == nullptr || !mxIsUint64(a) || mxGetNumberOfElements(a) != 1) usage("not a Gamut handle");
  const std::uintptr_t p = static_cast<std::uintptr_t>(*static_cast<std::uint64_t*>(mxGetData(a)));
  if (g_files.count(p) == 0) usage("the file is closed or the handle is not one Gamut made");
  return reinterpret_cast<gamut_file*>(p);
}

std::uintptr_t evaluation_handle(const mxArray* a) {
  if (a == nullptr || !mxIsUint64(a) || mxGetNumberOfElements(a) != 1) usage("not a Gamut evaluation");
  return static_cast<std::uintptr_t>(*static_cast<std::uint64_t*>(mxGetData(a)));
}

gamut_evaluation* evaluation(const mxArray* a) {
  const std::uintptr_t p = evaluation_handle(a);
  if (g_evaluations.count(p) == 0) usage("the evaluation is over or the handle is not one Gamut made");
  return reinterpret_cast<gamut_evaluation*>(p);
}

// A handle's output is made before the file is acquired, so a MATLAB allocation
// failure (which leaves the MEX function at once) cannot strand an open file.
mxArray* new_handle() { return mxCreateNumericMatrix(1, 1, mxUINT64_CLASS, mxREAL); }

mxArray* handle_out(mxArray* out, gamut_file* f) {
  const std::uintptr_t p = reinterpret_cast<std::uintptr_t>(f);
  try {
    g_files.insert(p);
  } catch (...) {
    gamut_abandon(f, 1);   // a file this handle created is removed; one opened is only closed
    throw;
  }
  if (g_files.size() == 1) mexLock();
  *static_cast<std::uint64_t*>(mxGetData(out)) = p;
  return out;
}

std::vector<std::string> cellstr(const mxArray* a, const char* what) {
  std::vector<std::string> out;
  if (a == nullptr || mxIsEmpty(a)) return out;
  if (mxIsClass(a, "string")) {   // a string array: one name per element
    const mwSize n = mxGetNumberOfElements(a);
    mxArray* in = const_cast<mxArray*>(a);
    mxArray* cells = nullptr;
    if (mexCallMATLABWithTrap(1, &cells, 1, &in, "cellstr") != nullptr) {
      usage(std::string(what) + " must be text");
    }
    for (mwSize i = 0; i < n; ++i) out.push_back(text(mxGetCell(cells, i), what));
    mxDestroyArray(cells);
    return out;
  }
  if (mxIsChar(a)) {
    out.push_back(text(a, what));
    return out;
  }
  if (!mxIsCell(a)) usage(std::string(what) + " must be a cell array of text");
  const mwSize n = mxGetNumberOfElements(a);
  for (mwSize i = 0; i < n; ++i) out.push_back(text(mxGetCell(a, i), what));
  return out;
}

std::vector<const char*> pointers(const std::vector<std::string>& v) {
  std::vector<const char*> out;
  for (const auto& s : v) out.push_back(s.c_str());
  return out;
}

mxArray* cell_out(gamut_strings* s) {
  const int64_t n = gamut_strings_count(s);
  mxArray* out = mxCreateCellMatrix(static_cast<mwSize>(n), 1);
  for (int64_t i = 0; i < n; ++i) {
    mxSetCell(out, static_cast<mwIndex>(i), mxCreateString(gamut_strings_get(s, i)));
  }
  gamut_strings_free(s);
  return out;
}

int dtype_code(mxClassID c) {
  switch (c) {
    case mxDOUBLE_CLASS: return GAMUT_FLOAT64;
    case mxSINGLE_CLASS: return GAMUT_FLOAT32;
    case mxINT64_CLASS: return GAMUT_INT64;
    case mxINT32_CLASS: return GAMUT_INT32;
    case mxUINT8_CLASS: return GAMUT_UINT8;
    case mxINT8_CLASS: return GAMUT_INT8;
    case mxLOGICAL_CLASS: return GAMUT_INT8;
    default: return -1;
  }
}

mxClassID class_of(int code) {
  switch (code) {
    case GAMUT_FLOAT64: return mxDOUBLE_CLASS;
    case GAMUT_FLOAT32: return mxSINGLE_CLASS;
    case GAMUT_INT64: return mxINT64_CLASS;
    case GAMUT_INT32: return mxINT32_CLASS;
    case GAMUT_UINT8: return mxUINT8_CLASS;
    case GAMUT_INT8: return mxINT8_CLASS;
    default: return mxDOUBLE_CLASS;
  }
}

std::size_t size_of(int code) {
  switch (code) {
    case GAMUT_FLOAT64: case GAMUT_INT64: return 8;
    case GAMUT_FLOAT32: case GAMUT_INT32: return 4;
    default: return 1;
  }
}

// C order with logical extents `dims` to a MATLAB array of the same extents.
mxArray* from_c_order(const unsigned char* src, const std::vector<int64_t>& dims, int code) {
  std::vector<mwSize> md(dims.begin(), dims.end());
  if (md.empty()) md = {1, 1};
  if (md.size() == 1) md.push_back(1);
  mxArray* out = mxCreateNumericArray(md.size(), md.data(), class_of(code), mxREAL);
  unsigned char* dst = static_cast<unsigned char*>(mxGetData(out));
  const std::size_t item = size_of(code);
  std::size_t total = 1;
  for (const auto d : dims) total *= static_cast<std::size_t>(d);
  if (dims.size() <= 1) {
    std::memcpy(dst, src, total * item);
    return out;
  }
  // index[k] runs over dims in C order; the MATLAB offset is column-major.
  std::vector<int64_t> index(dims.size(), 0);
  for (std::size_t c = 0; c < total; ++c) {
    std::size_t m = 0, stride = 1;
    for (std::size_t k = 0; k < dims.size(); ++k) {
      m += static_cast<std::size_t>(index[k]) * stride;
      stride *= static_cast<std::size_t>(dims[k]);
    }
    std::memcpy(dst + m * item, src + c * item, item);
    for (std::size_t k = dims.size(); k-- > 0;) {
      if (++index[k] < dims[k]) break;
      index[k] = 0;
    }
  }
  return out;
}

// A MATLAB array to C order, its extents as MATLAB gives them (trailing
// singleton extents beyond `rank` dropped).
std::vector<unsigned char> to_c_order(const mxArray* a, std::size_t rank, std::vector<int64_t>* dims) {
  if (mxIsSparse(a)) usage("a sparse array is not taken; give full(...)");
  const mwSize nd = mxGetNumberOfDimensions(a);
  const mwSize* md = mxGetDimensions(a);
  dims->assign(md, md + nd);
  while (dims->size() > rank && dims->back() == 1) dims->pop_back();
  while (dims->size() < rank) dims->push_back(1);
  const std::size_t item = mxGetElementSize(a);
  const std::size_t total = mxGetNumberOfElements(a);
  std::vector<unsigned char> out(total * item);
  const unsigned char* src = static_cast<const unsigned char*>(mxGetData(a));
  if (dims->size() <= 1) {
    if (total) std::memcpy(out.data(), src, total * item);
    return out;
  }
  std::vector<int64_t> index(dims->size(), 0);
  for (std::size_t c = 0; c < total; ++c) {
    std::size_t m = 0, stride = 1;
    for (std::size_t k = 0; k < dims->size(); ++k) {
      m += static_cast<std::size_t>(index[k]) * stride;
      stride *= static_cast<std::size_t>((*dims)[k]);
    }
    std::memcpy(out.data() + c * item, src + m * item, item);
    for (std::size_t k = dims->size(); k-- > 0;) {
      if (++index[k] < (*dims)[k]) break;
      index[k] = 0;
    }
  }
  return out;
}

// A selection from MATLAB: ':' (or nothing) for everything, [] for nothing,
// or 0-based positions as doubles or integers (the M layer converts from
// 1-based). [] is no positions, so a select that matched nothing reads nothing.
struct Sel {
  gamut_sel sel{};
  std::vector<int64_t> index;
  const gamut_sel* ptr() const { return &sel; }
};

Sel selection(const mxArray* a) {
  Sel s;
  s.sel.kind = GAMUT_SEL_ALL;
  if (a == nullptr) return s;
  if (mxIsChar(a)) {
    if (text(a, "positions") != ":") usage("positions are ':' for every one, or numbers");
    return s;
  }
  if (mxIsEmpty(a)) {
    s.sel.kind = GAMUT_SEL_INDEX;
    s.sel.count = 0;
    s.sel.index = nullptr;
    return s;
  }
  if (!mxIsDouble(a) && !mxIsInt64(a)) usage("positions are double or int64");
  const mwSize n = mxGetNumberOfElements(a);
  s.index.resize(n);
  for (mwSize i = 0; i < n; ++i) {
    if (mxIsInt64(a)) {
      s.index[i] = static_cast<int64_t*>(mxGetData(a))[i];
      continue;
    }
    const double v = mxGetPr(a)[i];
    // A double outside int64's range has no int64 value (undefined to cast).
    if (!(v == std::floor(v)) || v < -9.2e18 || v > 9.2e18) {
      usage("positions are whole numbers");
    }
    s.index[i] = static_cast<int64_t>(v);
  }
  s.sel.kind = GAMUT_SEL_INDEX;
  s.sel.index = s.index.data();
  s.sel.count = static_cast<int64_t>(n);
  return s;
}

// --- trees <-> structs ---------------------------------------------------------

void tree_from(gamut_tree* t, const std::string& prefix, const mxArray* value);

void tree_set(gamut_tree* t, const std::string& key, const mxArray* v) {
  gamut_error e{};
  if (mxIsClass(v, "missing")) {
    check(gamut_tree_set_null(t, key.c_str(), &e), e);
  } else if (mxIsStruct(v)) {
    check(gamut_tree_set_dict(t, key.c_str(), &e), e);
    tree_from(t, key, v);
  } else if (mxIsChar(v) || (mxIsClass(v, "string") && mxGetNumberOfElements(v) == 1)) {
    check(gamut_tree_set_string(t, key.c_str(), text(v, key.c_str()).c_str(), &e), e);
  } else if (mxIsCell(v) || mxIsClass(v, "string")) {
    const auto items = cellstr(v, key.c_str());
    const auto p = pointers(items);
    check(gamut_tree_set_strings(t, key.c_str(), p.data(), static_cast<int64_t>(p.size()), &e), e);
  } else if (mxGetNumberOfElements(v) == 1 && (mxIsLogical(v) || mxIsDouble(v) || mxIsInt64(v))) {
    if (mxIsLogical(v)) {
      check(gamut_tree_set_bool(t, key.c_str(), mxIsLogicalScalarTrue(v) ? 1 : 0, &e), e);
    } else if (mxIsInt64(v)) {
      check(gamut_tree_set_int(t, key.c_str(), one_int64(v), &e), e);
    } else {
      check(gamut_tree_set_float(t, key.c_str(), mxGetScalar(v), &e), e);
    }
  } else {
    int code = dtype_code(mxGetClassID(v));
    if (code != GAMUT_FLOAT64 && code != GAMUT_INT64 && code != GAMUT_INT32 && code != GAMUT_INT8) {
      usage(key + ": model data arrays are logical, int32, int64 or double");
    }
    std::vector<int64_t> dims;
    const mwSize nd = mxGetNumberOfDimensions(v);
    // A row or column vector is one axis.
    const mwSize* md = mxGetDimensions(v);
    std::size_t rank = nd;
    if (nd == 2 && (md[0] == 1 || md[1] == 1)) rank = 1;
    const auto bytes = to_c_order(v, rank, &dims);
    if (rank == 1) dims = {static_cast<int64_t>(mxGetNumberOfElements(v))};
    check(gamut_tree_set_array(t, key.c_str(), code, bytes.data(),
                             static_cast<int64_t>(mxGetNumberOfElements(v)), static_cast<int>(dims.size()),
                             dims.data(), &e),
          e);
  }
}

void tree_from(gamut_tree* t, const std::string& prefix, const mxArray* value) {
  if (!mxIsStruct(value) || mxGetNumberOfElements(value) != 1) usage("model numbers are a scalar struct");
  const int n = mxGetNumberOfFields(value);
  for (int i = 0; i < n; ++i) {
    const std::string name = mxGetFieldNameByNumber(value, i);
    const mxArray* v = mxGetFieldByNumber(value, 0, i);
    tree_set(t, prefix.empty() ? name : prefix + "/" + name, v);
  }
}

// The built-in nearest model's numbers with exact ranks, which a struct
// cannot carry (MATLAB has no one-axis or one-element arrays): columns as
// strings; lower and upper one axis; x points x columns; each output
// points first, one axis when it holds one value per point.
void nearest_tree(gamut_tree* t, const mxArray* numbers) {
  if (!mxIsStruct(numbers) || mxGetNumberOfElements(numbers) != 1) {
    usage("nearest numbers are a scalar struct");
  }
  auto field = [&](const char* name) {
    const mxArray* f = mxGetField(numbers, 0, name);
    if (f == nullptr) usage(std::string("nearest numbers need ") + name);
    return f;
  };
  gamut_error e{};
  auto doubles = [&](const mxArray* a, const char* what) {
    if (!mxIsDouble(a) || mxIsComplex(a) || mxIsSparse(a)) usage(std::string(what) + " is real full double");
  };
  const auto columns = cellstr(field("columns"), "columns");
  const auto p = pointers(columns);
  check(gamut_tree_set_strings(t, "columns", p.data(), static_cast<int64_t>(p.size()), &e), e);
  const int64_t k = static_cast<int64_t>(columns.size());
  for (const char* name : {"lower", "upper"}) {
    const mxArray* a = field(name);
    doubles(a, name);
    int64_t n = static_cast<int64_t>(mxGetNumberOfElements(a));
    check(gamut_tree_set_array(t, name, GAMUT_FLOAT64, mxGetData(a), n, 1, &n, &e), e);
  }
  const mxArray* x = field("x");
  doubles(x, "x");
  const int64_t total = static_cast<int64_t>(mxGetNumberOfElements(x));
  if (k == 0 || total % k != 0) usage("x is points x columns");
  const int64_t points = total / k;
  {
    // x(i, j) in MATLAB's column order to C order.
    std::vector<double> c(static_cast<std::size_t>(total));
    const double* m = mxGetPr(x);
    for (int64_t i = 0; i < points; ++i) {
      for (int64_t j = 0; j < k; ++j) c[static_cast<std::size_t>(i * k + j)] = m[j * points + i];
    }
    const int64_t dims[2] = {points, k};
    check(gamut_tree_set_array(t, "x", GAMUT_FLOAT64, c.data(), static_cast<int64_t>(c.size()), 2, dims, &e),
          e);
  }
  check(gamut_tree_set_dict(t, "outputs", &e), e);
  const mxArray* outs = field("outputs");
  if (!mxIsStruct(outs) || mxGetNumberOfElements(outs) != 1) usage("outputs is a scalar struct");
  for (int i = 0; i < mxGetNumberOfFields(outs); ++i) {
    const std::string key = std::string("outputs/") + mxGetFieldNameByNumber(outs, i);
    const mxArray* v = mxGetFieldByNumber(outs, 0, i);
    doubles(v, key.c_str());
    const mwSize nd = mxGetNumberOfDimensions(v);
    const mwSize* md = mxGetDimensions(v);
    std::vector<int64_t> dims(md, md + nd);
    while (dims.size() > 1 && dims.back() == 1) dims.pop_back();
    if (dims.empty() || dims[0] != points) usage(key + ": one entry per point, points first");
    std::vector<int64_t> c_dims;
    const auto bytes = to_c_order(v, dims.size(), &c_dims);
    check(gamut_tree_set_array(t, key.c_str(), GAMUT_FLOAT64, bytes.data(),
                             static_cast<int64_t>(mxGetNumberOfElements(v)), static_cast<int>(dims.size()),
                             dims.data(), &e),
          e);
  }
}

mxArray* struct_from(const gamut_tree* t, const std::string& prefix);

mxArray* tree_value(const gamut_tree* t, const std::string& key) {
  gamut_error e{};
  int kind = 0;
  check(gamut_tree_kind(t, key.c_str(), &kind, &e), e);
  switch (kind) {
    case GAMUT_TREE_NULL: {
      mxArray* m = nullptr;
      if (mexCallMATLABWithTrap(1, &m, 0, nullptr, "missing") != nullptr) usage("cannot make a missing value");
      return m;
    }
    case GAMUT_TREE_BOOL:
    case GAMUT_TREE_INT:
    case GAMUT_TREE_FLOAT: {
      int64_t i = 0;
      double d = 0.0;
      check(gamut_tree_scalar(t, key.c_str(), &i, &d, &e), e);
      if (kind == GAMUT_TREE_BOOL) return mxCreateLogicalScalar(i != 0);
      if (kind == GAMUT_TREE_INT) {
        mxArray* m = mxCreateNumericMatrix(1, 1, mxINT64_CLASS, mxREAL);
        *static_cast<int64_t*>(mxGetData(m)) = i;
        return m;
      }
      return mxCreateDoubleScalar(d);
    }
    case GAMUT_TREE_STRING: {
      gamut_strings* s = nullptr;
      check(gamut_tree_strings(t, key.c_str(), &s, &e), e);
      mxArray* m = mxCreateString(gamut_strings_get(s, 0));
      gamut_strings_free(s);
      return m;
    }
    case GAMUT_TREE_STRINGS: {
      gamut_strings* s = nullptr;
      check(gamut_tree_strings(t, key.c_str(), &s, &e), e);
      return cell_out(s);
    }
    case GAMUT_TREE_DICT: return struct_from(t, key);
    default: {
      int dtype = 0, rank = 0;
      int64_t shape[8];
      check(gamut_tree_array_info(t, key.c_str(), &dtype, &rank, shape, 8, &e), e);
      std::vector<int64_t> dims(shape, shape + rank);
      std::size_t total = 1;
      for (const auto d : dims) total *= static_cast<std::size_t>(d);
      std::vector<unsigned char> bytes(total * size_of(dtype));
      check(gamut_tree_array(t, key.c_str(), bytes.data(), static_cast<int64_t>(bytes.size()), &e), e);
      if (rank == 1) dims.push_back(1);   // a column
      mxArray* m = from_c_order(bytes.data(), dims, dtype);
      if (dtype == GAMUT_INT8) {
        mxArray* l = nullptr;
        if (mexCallMATLABWithTrap(1, &l, 1, &m, "logical") != nullptr) usage("cannot make a logical array");
        return l;
      }
      return m;
    }
  }
}

mxArray* struct_from(const gamut_tree* t, const std::string& prefix) {
  gamut_error e{};
  gamut_strings* keys = nullptr;
  check(gamut_tree_keys(t, prefix.c_str(), &keys, &e), e);
  const int64_t n = gamut_strings_count(keys);
  std::vector<std::string> names;
  for (int64_t i = 0; i < n; ++i) names.push_back(gamut_strings_get(keys, i));
  gamut_strings_free(keys);
  std::vector<const char*> p = pointers(names);
  mxArray* out = mxCreateStructMatrix(1, 1, static_cast<int>(p.size()), p.data());
  for (std::size_t i = 0; i < names.size(); ++i) {
    mxSetFieldByNumber(out, 0, static_cast<int>(i),
                       tree_value(t, prefix.empty() ? names[i] : prefix + "/" + names[i]));
  }
  return out;
}

}  // namespace

static void dispatch(int nlhs, mxArray* plhs[], int nrhs, const mxArray* prhs[]) {
  (void)nlhs;
  if (nrhs < 1) usage("gamut_mex(command, ...)");
  const std::string cmd = text(prhs[0], "command");
  auto arg = [&](int i) -> const mxArray* { return i < nrhs ? prhs[i] : nullptr; };
  gamut_error e{};
  for (int i = 1; i < nrhs; ++i) {   // nothing Gamut takes is sparse; its storage is compressed
    if (mxIsSparse(prhs[i])) usage("a sparse array is not taken; give full(...)");
  }

  if (cmd == "version") {
    plhs[0] = mxCreateString(gamut_version());
  } else if (cmd == "open" || cmd == "open_append") {
    gamut_file* f = nullptr;
    const std::string path = text(arg(1), "path");
    mxArray* out = new_handle();
    check(cmd == "open" ? gamut_open(path.c_str(), &f, &e) : gamut_open_append(path.c_str(), &f, &e), e);
    plhs[0] = handle_out(out, f);
  } else if (cmd == "create" || cmd == "create_model") {
    gamut_file* f = nullptr;
    const std::string path = text(arg(1), "path"), writer = text(arg(2), "writer");
    const std::string kind = text(arg(3), "mesh kind"), per = text(arg(4), "per");
    mxArray* out = new_handle();
    check(cmd == "create" ? gamut_create(path.c_str(), writer.c_str(), kind.c_str(), per.c_str(), &f, &e)
                          : gamut_create_model(path.c_str(), writer.c_str(), kind.c_str(), per.c_str(), &f, &e),
          e);
    plhs[0] = handle_out(out, f);
  } else if (cmd == "close") {
    gamut_file* f = file(arg(1));
    free_evaluations_of(reinterpret_cast<std::uintptr_t>(f));
    const int status = gamut_close(f, &e);
    // A refused close keeps the handle open (fix and close again, or abandon).
    if (status == 0) forget(f);
    check(status, e);
  } else if (cmd == "abandon") {
    gamut_file* f = file(arg(1));
    free_evaluations_of(reinterpret_cast<std::uintptr_t>(f));
    forget(f);
    gamut_abandon(f, nrhs > 2 && mxIsLogicalScalarTrue(prhs[2]) ? 1 : 0);
  } else if (cmd == "info" || cmd == "names" || cmd == "table") {
    gamut_strings* s = nullptr;
    const std::string key = text(arg(2), "key");
    if (cmd == "info") check(gamut_info(file(arg(1)), key.c_str(), &s, &e), e);
    if (cmd == "names") check(gamut_names(file(arg(1)), key.c_str(), &s, &e), e);
    if (cmd == "table") check(gamut_table(file(arg(1)), key.c_str(), &s, &e), e);
    plhs[0] = cell_out(s);
  } else if (cmd == "describe") {
    gamut_strings *k = nullptr, *v = nullptr;
    check(gamut_describe(file(arg(1)), text(arg(2), "name").c_str(), &k, &v, &e), e);
    plhs[0] = cell_out(k);
    plhs[1] = cell_out(v);
  } else if (cmd == "related") {
    gamut_strings *t = nullptr, *k = nullptr, *n = nullptr;
    check(gamut_related(file(arg(1)), text(arg(2), "name").c_str(), &t, &k, &n, &e), e);
    plhs[0] = cell_out(t);
    plhs[1] = cell_out(k);
    plhs[2] = cell_out(n);
  } else if (cmd == "read") {
    gamut_file* f = file(arg(1));
    const std::string name = text(arg(2), "name");
    const Sel rows = selection(arg(3)), sites = selection(arg(4));
    const int code = static_cast<int>(scalar(arg(5), "dtype"));
    int64_t shape[4];
    int rank = 0;
    check(gamut_shape(f, name.c_str(), rows.ptr(), sites.ptr(), &rank, shape, 4, &e), e);
    std::vector<int64_t> dims(shape, shape + rank);
    std::size_t total = 1;
    for (const auto d : dims) total *= static_cast<std::size_t>(d);
    std::vector<unsigned char> buf(total * size_of(code));
    check(gamut_read(f, name.c_str(), rows.ptr(), sites.ptr(), code, buf.data(),
                   static_cast<int64_t>(buf.size()), &e),
          e);
    if (dims.size() == 1) dims.push_back(1);   // a column per run
    plhs[0] = from_c_order(buf.data(), dims, code);
  } else if (cmd == "outside") {
    gamut_file* f = file(arg(1));
    const std::string name = text(arg(2), "name");
    const Sel rows = selection(arg(3));
    int64_t shape[4];
    int rank = 0;
    check(gamut_shape(f, name.c_str(), rows.ptr(), nullptr, &rank, shape, 4, &e), e);
    // Sized as a read of the parameter; for any other name the core refuses.
    const mwSize n = rank == 1 ? static_cast<mwSize>(shape[0]) : 0;
    plhs[0] = mxCreateDoubleMatrix(n, 1, mxREAL);
    check(gamut_outside(f, name.c_str(), rows.ptr(), mxGetPr(plhs[0]),
                        static_cast<int64_t>(n * sizeof(double)), &e),
          e);
  } else if (cmd == "label_names") {
    gamut_strings* s = nullptr;
    const Sel rows = selection(arg(3));
    check(gamut_label_names(file(arg(1)), text(arg(2), "label").c_str(), rows.ptr(), &s, &e), e);
    plhs[0] = cell_out(s);
  } else if (cmd == "select") {
    gamut_file* f = file(arg(1));
    gamut_strings* s = nullptr;
    check(gamut_info(f, "row_count", &s, &e), e);
    const int64_t rows = std::stoll(gamut_strings_get(s, 0));
    gamut_strings_free(s);
    // The core refuses a file of more rows than a selection scans (2^27,
    // docs/security.md) before it fills a buffer, so none larger is made.
    const bool scanned = rows > 0 && rows <= (int64_t(1) << 27);
    std::vector<int64_t> out(static_cast<std::size_t>(scanned ? rows : 1));
    int64_t n = 0;
    check(gamut_select(f, text(arg(2), "where").c_str(), out.data(), static_cast<int64_t>(out.size()), &n, &e), e);
    plhs[0] = mxCreateNumericMatrix(static_cast<mwSize>(n), 1, mxINT64_CLASS, mxREAL);
    if (n) std::memcpy(mxGetData(plhs[0]), out.data(), static_cast<std::size_t>(n) * 8);
  } else if (cmd == "set_compression") {
    check(gamut_set_compression(file(arg(1)), static_cast<int>(scalar(arg(2), "gzip level")),
                                static_cast<int>(scalar(arg(3), "shuffle")), &e),
          e);
  } else if (cmd == "set_threads") {
    check(gamut_set_threads(file(arg(1)), static_cast<int>(scalar(arg(2), "threads")), &e), e);
  } else if (cmd == "validate") {
    gamut_report* r = nullptr;
    check(gamut_validate(text(arg(1), "path").c_str(), &r, &e), e);
    const int64_t n = gamut_report_count(r);
    const char* fields[] = {"rule", "severity", "path", "message"};
    plhs[0] = mxCreateStructMatrix(static_cast<mwSize>(n), 1, 4, fields);
    for (int64_t i = 0; i < n; ++i) {
      const char *rule, *sev, *path, *msg;
      gamut_report_get(r, i, &rule, &sev, &path, &msg);
      mxSetField(plhs[0], static_cast<mwIndex>(i), "rule", mxCreateString(rule));
      mxSetField(plhs[0], static_cast<mwIndex>(i), "severity", mxCreateString(sev));
      mxSetField(plhs[0], static_cast<mwIndex>(i), "path", mxCreateString(path));
      mxSetField(plhs[0], static_cast<mwIndex>(i), "message", mxCreateString(msg));
    }
    gamut_report_free(r);
  } else if (cmd == "set_attribute") {
    check(gamut_set_attribute(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "value").c_str(), &e), e);
  } else if (cmd == "declare_parameter") {
    // f, name, role, units, dtype, hasBounds, lower, upper, runGroup
    check(gamut_declare_parameter(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "role").c_str(),
                                text(arg(4), "units").c_str(), static_cast<int>(scalar(arg(5), "dtype")),
                                static_cast<int>(scalar(arg(6), "hasBounds")), scalar(arg(7), "lower"),
                                scalar(arg(8), "upper"), text(arg(9), "run_group").c_str(), &e),
          e);
  } else if (cmd == "declare_label" || cmd == "declare_mesh_label") {
    const auto cats = cellstr(arg(4), "categories");
    const auto p = pointers(cats);
    const std::string name = text(arg(2), "name"), roleOrAt = text(arg(3), "role");
    if (cmd == "declare_label") {
      check(gamut_declare_label(file(arg(1)), name.c_str(), roleOrAt.c_str(), p.data(),
                              static_cast<int64_t>(p.size()), &e), e);
    } else {
      check(gamut_declare_mesh_label(file(arg(1)), name.c_str(), roleOrAt.c_str(), p.data(),
                                   static_cast<int64_t>(p.size()), &e), e);
    }
  } else if (cmd == "declare_result") {
    // f, name, where, units, dtype, of, statistic, hasQ, q, method, wrt, axis, vector, roundBits, model, output
    check(gamut_declare_result(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "where").c_str(),
                             text(arg(4), "units").c_str(), static_cast<int>(scalar(arg(5), "dtype")),
                             text(arg(6), "of").c_str(), text(arg(7), "statistic").c_str(),
                             static_cast<int>(scalar(arg(8), "hasQ")), scalar(arg(9), "q"),
                             text(arg(10), "method").c_str(), text(arg(11), "with_respect_to").c_str(),
                             text(arg(12), "axis").c_str(), text(arg(13), "vector").c_str(),
                             static_cast<int>(scalar(arg(14), "round_bits")), text(arg(15), "model").c_str(),
                             text(arg(16), "output").c_str(), &e),
          e);
  } else if (cmd == "declare_coordinates") {
    check(gamut_declare_coordinates(file(arg(1)), text(arg(2), "units").c_str(),
                                  static_cast<int>(scalar(arg(3), "dtype")), static_cast<int>(scalar(arg(4), "axes")),
                                  text(arg(5), "model").c_str(), text(arg(6), "output").c_str(), &e),
          e);
  } else if (cmd == "set_constant") {
    const mxArray* v = arg(4);
    if (is_integer(v)) {
      check(gamut_set_constant(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "units").c_str(),
                             GAMUT_INT64, 0.0, one_integer(v), &e), e);
    } else {
      check(gamut_set_constant(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "units").c_str(),
                             GAMUT_FLOAT64, scalar(v, "value"), 0, &e), e);
    }
  } else if (cmd == "set_generalisation_group") {
    check(gamut_set_generalisation_group(file(arg(1)), text(arg(2), "label").c_str(), &e), e);
  } else if (cmd == "geometry_begin") {
    check(gamut_geometry_begin(file(arg(1)), &e), e);
  } else if (cmd == "geometry_points") {
    // points: nodes x axes (MATLAB), or [] with n_nodes and axes
    gamut_file* f = file(arg(1));
    const mxArray* p = arg(2);
    if (p == nullptr || mxIsEmpty(p)) {
      check(gamut_geometry_points(f, GAMUT_FLOAT64, nullptr, 0, static_cast<int64_t>(scalar(arg(3), "n_nodes")),
                                static_cast<int>(scalar(arg(4), "axes")), &e), e);
    } else {
      const int code = dtype_code(mxGetClassID(p));
      if (code != GAMUT_FLOAT64 && code != GAMUT_FLOAT32) usage("points are double or single");
      std::vector<int64_t> dims;
      const auto bytes = to_c_order(p, 2, &dims);
      // The count is the array's own, so an array of more axes than two is refused.
      check(gamut_geometry_points(f, code, bytes.data(), static_cast<int64_t>(mxGetNumberOfElements(p)),
                                dims[0], static_cast<int>(dims[1]), &e), e);
    }
  } else if (cmd == "geometry_cells") {
    // types (uint8), offsets (int64), connectivity (int64, 0-based as VTK)
    std::vector<uint8_t> types;
    for (const auto v : integers(arg(2), "cell types")) {
      if (v < 0 || v > 255) usage("cell types are 0 to 255");
      types.push_back(static_cast<uint8_t>(v));
    }
    const std::vector<int64_t> offsets = integers(arg(3), "cell offsets");
    const std::vector<int64_t> conn = integers(arg(4), "connectivity");
    check(gamut_geometry_cells(file(arg(1)), types.data(), static_cast<int64_t>(types.size()), offsets.data(),
                             static_cast<int64_t>(offsets.size()), conn.data(),
                             static_cast<int64_t>(conn.size()), &e),
          e);
  } else if (cmd == "geometry_label") {
    const std::vector<int64_t> v = integers(arg(3), "mesh-label codes");
    check(gamut_geometry_label(file(arg(1)), text(arg(2), "name").c_str(), v.data(), static_cast<int64_t>(v.size()), &e), e);
  } else if (cmd == "set_mesh") {
    check(gamut_set_mesh(file(arg(1)), &e), e);
  } else if (cmd == "batch_begin") {
    check(gamut_batch_begin(file(arg(1)), static_cast<int64_t>(scalar(arg(2), "rows")), &e), e);
  } else if (cmd == "batch_values") {
    // values: a column per run, or rows x sites for a field
    const mxArray* v = arg(3);
    const int code = dtype_code(mxGetClassID(v));
    if (code < 0 || mxIsLogical(v)) usage("values are numeric");
    std::vector<int64_t> dims;
    const auto bytes = to_c_order(v, mxGetNumberOfDimensions(v), &dims);
    // A vector, row or column, is flat; anything else has a first axis.
    const mwSize* md = mxGetDimensions(v);
    const bool vector = mxGetNumberOfDimensions(v) == 2 && (md[0] == 1 || md[1] == 1);
    const int64_t first = vector ? 0 : static_cast<int64_t>(md[0]);
    check(gamut_batch_values(file(arg(1)), text(arg(2), "name").c_str(), code, bytes.data(), first,
                           static_cast<int64_t>(mxGetNumberOfElements(v)), &e),
          e);
  } else if (cmd == "batch_names") {
    const auto names = cellstr(arg(3), "names");
    const auto p = pointers(names);
    check(gamut_batch_names(file(arg(1)), text(arg(2), "label").c_str(), p.data(), static_cast<int64_t>(p.size()), &e), e);
  } else if (cmd == "batch_geometry_for_row") {
    check(gamut_batch_geometry_for_row(file(arg(1)), &e), e);
  } else if (cmd == "batch_geometry_for_member") {
    check(gamut_batch_geometry_for_member(file(arg(1)), text(arg(2), "member").c_str(), &e), e);
  } else if (cmd == "batch_commit") {
    int64_t first = 0;
    check(gamut_batch_commit(file(arg(1)), &first, &e), e);
    plhs[0] = mxCreateDoubleScalar(static_cast<double>(first));
  } else if (cmd == "flush") {
    check(gamut_flush(file(arg(1)), &e), e);
  } else if (cmd == "set_note") {
    gamut_file* f = file(arg(1));
    const std::string key = text(arg(2), "key");
    const mxArray* v = arg(3);
    if (v != nullptr && (mxIsChar(v) || mxIsClass(v, "string"))) {
      check(gamut_set_note_text(f, key.c_str(), text(v, "value").c_str(), &e), e);
    } else if (is_integer(v)) {
      check(gamut_set_note_int(f, key.c_str(), one_integer(v), &e), e);
    } else {
      check(gamut_set_note_float(f, key.c_str(), scalar(v, "value"), &e), e);
    }
  } else if (cmd == "model_numbers") {
    Tree t;
    check(gamut_model_numbers(file(arg(1)), text(arg(2), "id").c_str(), &t.t, &e), e);
    plhs[0] = struct_from(t.t, "");
  } else if (cmd == "add_model") {
    // f, id, type, inputs, numbers (struct), repr
    Tree t;
    check(gamut_tree_new(&t.t, &e), e);
    if (text(arg(3), "type") == "nearest") {
      nearest_tree(t.t, arg(5));
    } else {
      tree_from(t.t, "", arg(5));
    }
    const auto inputs = cellstr(arg(4), "inputs");
    const auto p = pointers(inputs);
    check(gamut_add_model(file(arg(1)), text(arg(2), "id").c_str(), text(arg(3), "type").c_str(),
                          p.data(), static_cast<int64_t>(p.size()), t.t, text(arg(6), "repr").c_str(), &e),
          e);
  } else if (cmd == "nearest_check") {
    Tree t;
    check(gamut_tree_new(&t.t, &e), e);
    nearest_tree(t.t, arg(1));
    check(gamut_nearest_check(t.t, &e), e);
  } else if (cmd == "nearest_call") {
    // numbers (struct), inputNames (cell), columns (cell of double vectors), output
    Tree t;
    check(gamut_tree_new(&t.t, &e), e);
    nearest_tree(t.t, arg(1));
    const std::vector<std::string> names = cellstr(arg(2), "input names");
    std::vector<std::vector<double>> data;
    int64_t rows = 0;
    const mxArray* cols = arg(3);
    if (!mxIsCell(cols) || mxGetNumberOfElements(cols) != names.size()) {
      usage("one column per input name");
    }
    for (std::size_t j = 0; j < names.size(); ++j) {
      const mxArray* c = mxGetCell(cols, static_cast<mwIndex>(j));
      if (c == nullptr || !mxIsDouble(c) || mxIsComplex(c) || mxIsSparse(c)) {
        usage("input columns are real full double");
      }
      data.emplace_back(mxGetPr(c), mxGetPr(c) + mxGetNumberOfElements(c));
    }
    if (!data.empty()) rows = static_cast<int64_t>(data.front().size());
    std::vector<const double*> ptrs;
    std::vector<int64_t> lengths;
    for (const auto& d : data) {
      ptrs.push_back(d.data());
      lengths.push_back(static_cast<int64_t>(d.size()));
    }
    const auto np = pointers(names);
    const std::string output = text(arg(4), "output");
    int64_t per = 0;
    check(gamut_nearest_output_size(t.t, output.c_str(), &per, &e), e);
    std::vector<double> out(static_cast<std::size_t>(rows * per));
    check(gamut_nearest_call(t.t, np.data(), ptrs.data(), lengths.data(), static_cast<int>(names.size()), rows,
                             output.c_str(), out.data(), static_cast<int64_t>(out.size()), &e),
          e);
    std::vector<int64_t> dims = {rows, per};
    plhs[0] = from_c_order(reinterpret_cast<const unsigned char*>(out.data()), dims, GAMUT_FLOAT64);
  } else if (cmd == "append") {
    int64_t n = 0;
    check(gamut_append(text(arg(1), "dst").c_str(), text(arg(2), "src").c_str(), &n, &e), e);
    plhs[0] = mxCreateDoubleScalar(static_cast<double>(n));
  } else if (cmd == "extract") {
    const Sel rows = selection(arg(3));   // ':' every row, [] none
    check(gamut_extract(text(arg(1), "src").c_str(), text(arg(2), "dst").c_str(), rows.ptr(), &e), e);
  } else if (cmd == "write_copy") {
    check(gamut_write_copy(text(arg(1), "src").c_str(), text(arg(2), "dst").c_str(), &e), e);
  } else if (cmd == "evaluation_begin") {
    gamut_file* m = file(arg(1));
    const std::string path = text(arg(3), "path");
    mxArray* out = new_handle();
    gamut_evaluation* ev = nullptr;
    check(gamut_evaluation_begin(m, one_integer(arg(2)), path.c_str(), &ev, &e), e);
    const std::uintptr_t p = reinterpret_cast<std::uintptr_t>(ev);
    try {
      g_evaluations[p] = reinterpret_cast<std::uintptr_t>(m);
    } catch (...) {
      gamut_evaluation_free(ev);
      throw;
    }
    *static_cast<std::uint64_t*>(mxGetData(out)) = p;
    plhs[0] = out;
  } else if (cmd == "evaluation_free") {
    const std::uintptr_t p = evaluation_handle(arg(1));
    if (g_evaluations.erase(p) != 0) gamut_evaluation_free(reinterpret_cast<gamut_evaluation*>(p));
  } else if (cmd == "evaluation_values" || cmd == "evaluation_coordinates") {
    const mxArray* v = arg(cmd == "evaluation_values" ? 3 : 2);
    const int code = dtype_code(mxGetClassID(v));
    if (code < 0 || mxIsLogical(v) || mxIsComplex(v) || mxIsSparse(v)) usage("values are real full numeric");
    std::vector<int64_t> dims;
    const auto bytes = to_c_order(v, mxGetNumberOfDimensions(v), &dims);
    const auto count = static_cast<int64_t>(mxGetNumberOfElements(v));
    gamut_evaluation* ev = evaluation(arg(1));
    check(cmd == "evaluation_values"
              ? gamut_evaluation_values(ev, text(arg(2), "name").c_str(), code, bytes.data(), count, &e)
              : gamut_evaluation_coordinates(ev, code, bytes.data(), count, &e),
          e);
  } else if (cmd == "evaluation_names") {
    const auto names = cellstr(arg(3), "names");
    const auto p = pointers(names);
    check(gamut_evaluation_names(evaluation(arg(1)), text(arg(2), "name").c_str(), p.data(),
                                 static_cast<int64_t>(p.size()), &e),
          e);
  } else if (cmd == "evaluation_ready") {
    gamut_strings *w = nullptr, *m = nullptr;
    check(gamut_evaluation_ready(evaluation(arg(1)), &w, &m, &e), e);
    plhs[0] = cell_out(w);
    plhs[1] = cell_out(m);
  } else if (cmd == "evaluation_requests") {
    gamut_strings *o = nullptr, *k = nullptr, *y = nullptr;
    check(gamut_evaluation_requests(evaluation(arg(1)), text(arg(2), "model").c_str(), &o, &k, &y, &e), e);
    plhs[0] = cell_out(o);
    plhs[1] = cell_out(k);
    plhs[2] = cell_out(y);
  } else if (cmd == "evaluation_input") {
    gamut_evaluation* ev = evaluation(arg(1));
    const std::string name = text(arg(2), "name");
    int code = 0, rank = 0;
    int64_t shape[3];
    check(gamut_evaluation_input_info(ev, name.c_str(), &code, &rank, shape, 3, &e), e);
    std::vector<int64_t> dims(shape, shape + rank);
    std::size_t total = 1;
    for (const auto d : dims) total *= static_cast<std::size_t>(d);
    std::vector<unsigned char> bytes(total * size_of(code));
    check(gamut_evaluation_input(ev, name.c_str(), bytes.data(), static_cast<int64_t>(bytes.size()), &e), e);
    plhs[0] = from_c_order(bytes.data(), dims, code);
  } else if (cmd == "evaluation_answer") {
    // values: a column per row, rows x sites for a field, rows x nodes x axes for coordinates
    const mxArray* v = arg(6);
    if (!mxIsDouble(v) || mxIsComplex(v)) usage("an answer is real double values");
    std::vector<int64_t> dims;
    const auto bytes = to_c_order(v, mxGetNumberOfDimensions(v), &dims);
    check(gamut_evaluation_answer(evaluation(arg(1)), text(arg(2), "model").c_str(),
                                  text(arg(3), "output").c_str(), text(arg(4), "kind").c_str(),
                                  text(arg(5), "key").c_str(), reinterpret_cast<const double*>(bytes.data()),
                                  static_cast<int64_t>(mxGetNumberOfElements(v)), &e),
          e);
  } else if (cmd == "evaluation_finish") {
    check(gamut_evaluation_finish(evaluation(arg(1)), &e), e);
  } else {
    usage("unknown command \"" + cmd + "\"");
  }
}

void mexFunction(int nlhs, mxArray* plhs[], int nrhs, const mxArray* prhs[]) {
  static const bool at_exit = (mexAtExit(finish_open_files), true);
  (void)at_exit;
  // The error is copied to fixed storage and every C++ object is gone before
  // mexErrMsgIdAndTxt, which leaves without running destructors.
  static char id[64];
  static char message[4096];
  {
    std::string i, m;
    try {
      dispatch(nlhs, plhs, nrhs, prhs);
      return;
    } catch (const Refusal& x) {
      i = x.id;
      m = x.message;
    } catch (const std::exception& x) {
      i = "gamut:error";
      m = x.what();
    }
    std::snprintf(id, sizeof id, "%s", i.c_str());
    std::snprintf(message, sizeof message, "%s", m.c_str());
  }
  mexErrMsgIdAndTxt(id, "%s", message);
}
