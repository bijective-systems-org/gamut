// The MATLAB gateway to the core: one MEX function dispatching on a command
// name to the C interface.  It converts between MATLAB's column-major arrays
// and the core's C order, keeps a registry of live handles so a stale or
// forged handle is refused rather than dereferenced, and turns every core
// error into a MATLAB error with identifier gamut:<rule>.
#include <cmath>
#include <cstdint>
#include <cstring>
#include <set>
#include <string>
#include <vector>

#include "mex.h"
#include "gamut/gamut.h"

namespace {

std::set<std::uintptr_t> g_files;

[[noreturn]] void raise(const gamut_error& e) {
  const std::string id = std::string("gamut:") + (e.rule[0] ? e.rule : "error");
  std::string msg = e.message;
  if (e.path[0]) msg = std::string(e.path) + ": " + msg;
  mexErrMsgIdAndTxt(id.c_str(), "%s", msg.c_str());
  throw 0;  // not reached
}

[[noreturn]] void usage(const std::string& why) {
  mexErrMsgIdAndTxt("gamut:usage", "%s", why.c_str());
  throw 0;
}

void check(int status, const gamut_error& e) {
  if (status != 0) raise(e);
}

std::string text(const mxArray* a, const char* what) {
  if (a == nullptr) usage(std::string(what) + " is missing");
  if (mxIsEmpty(a)) return std::string();
  if (!mxIsChar(a)) usage(std::string(what) + " must be text");
  char* s = mxArrayToUTF8String(a);
  std::string out = s == nullptr ? std::string() : std::string(s);
  mxFree(s);
  return out;
}

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

mxArray* handle_out(gamut_file* f) {
  g_files.insert(reinterpret_cast<std::uintptr_t>(f));
  mxArray* out = mxCreateNumericMatrix(1, 1, mxUINT64_CLASS, mxREAL);
  *static_cast<std::uint64_t*>(mxGetData(out)) = reinterpret_cast<std::uintptr_t>(f);
  return out;
}

std::vector<std::string> cellstr(const mxArray* a, const char* what) {
  std::vector<std::string> out;
  if (a == nullptr || mxIsEmpty(a)) return out;
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

// A selection from MATLAB: [] for everything, or 0-based positions as
// doubles or integers (the M layer converts from 1-based).
struct Sel {
  gamut_sel sel{};
  std::vector<int64_t> index;
  const gamut_sel* ptr() const { return &sel; }
};

Sel selection(const mxArray* a) {
  Sel s;
  s.sel.kind = GAMUT_SEL_ALL;
  if (a == nullptr || mxIsEmpty(a)) return s;
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
  } else if (mxIsChar(v)) {
    check(gamut_tree_set_string(t, key.c_str(), text(v, key.c_str()).c_str(), &e), e);
  } else if (mxIsCell(v)) {
    const auto items = cellstr(v, key.c_str());
    const auto p = pointers(items);
    check(gamut_tree_set_strings(t, key.c_str(), p.data(), static_cast<int64_t>(p.size()), &e), e);
  } else if (mxGetNumberOfElements(v) == 1 && (mxIsLogical(v) || mxIsDouble(v) || mxIsInt64(v))) {
    if (mxIsLogical(v)) {
      check(gamut_tree_set_bool(t, key.c_str(), mxIsLogicalScalarTrue(v) ? 1 : 0, &e), e);
    } else if (mxIsInt64(v)) {
      check(gamut_tree_set_int(t, key.c_str(), *static_cast<int64_t*>(mxGetData(v)), &e), e);
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
    check(gamut_tree_set_array(t, key.c_str(), code, bytes.data(), static_cast<int>(dims.size()),
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
    if (!mxIsDouble(a) || mxIsComplex(a)) usage(std::string(what) + " is real double");
  };
  const auto columns = cellstr(field("columns"), "columns");
  const auto p = pointers(columns);
  check(gamut_tree_set_strings(t, "columns", p.data(), static_cast<int64_t>(p.size()), &e), e);
  const int64_t k = static_cast<int64_t>(columns.size());
  for (const char* name : {"lower", "upper"}) {
    const mxArray* a = field(name);
    doubles(a, name);
    int64_t n = static_cast<int64_t>(mxGetNumberOfElements(a));
    check(gamut_tree_set_array(t, name, GAMUT_FLOAT64, mxGetData(a), 1, &n, &e), e);
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
    check(gamut_tree_set_array(t, "x", GAMUT_FLOAT64, c.data(), 2, dims, &e), e);
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
                             static_cast<int>(dims.size()), dims.data(), &e),
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
      mexCallMATLAB(1, &m, 0, nullptr, "missing");
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
      check(gamut_tree_array_info(t, key.c_str(), &dtype, &rank, shape, &e), e);
      std::vector<int64_t> dims(shape, shape + rank);
      std::size_t total = 1;
      for (const auto d : dims) total *= static_cast<std::size_t>(d);
      std::vector<unsigned char> bytes(total * size_of(dtype));
      check(gamut_tree_array(t, key.c_str(), bytes.data(), static_cast<int64_t>(bytes.size()), &e), e);
      if (rank == 1) dims.push_back(1);   // a column
      mxArray* m = from_c_order(bytes.data(), dims, dtype);
      if (dtype == GAMUT_INT8) {
        mxArray* l = nullptr;
        mexCallMATLAB(1, &l, 1, &m, "logical");
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

void mexFunction(int nlhs, mxArray* plhs[], int nrhs, const mxArray* prhs[]) {
  (void)nlhs;
  if (nrhs < 1) usage("gamut_mex(command, ...)");
  const std::string cmd = text(prhs[0], "command");
  auto arg = [&](int i) -> const mxArray* { return i < nrhs ? prhs[i] : nullptr; };
  gamut_error e{};

  if (cmd == "version") {
    plhs[0] = mxCreateString(gamut_version());
  } else if (cmd == "open" || cmd == "open_append") {
    gamut_file* f = nullptr;
    const std::string path = text(arg(1), "path");
    check(cmd == "open" ? gamut_open(path.c_str(), &f, &e) : gamut_open_append(path.c_str(), &f, &e), e);
    plhs[0] = handle_out(f);
  } else if (cmd == "create" || cmd == "create_model") {
    gamut_file* f = nullptr;
    const std::string path = text(arg(1), "path"), writer = text(arg(2), "writer");
    const std::string kind = text(arg(3), "mesh kind"), per = text(arg(4), "per");
    check(cmd == "create" ? gamut_create(path.c_str(), writer.c_str(), kind.c_str(), per.c_str(), &f, &e)
                          : gamut_create_model(path.c_str(), writer.c_str(), kind.c_str(), per.c_str(), &f, &e),
          e);
    plhs[0] = handle_out(f);
  } else if (cmd == "close") {
    gamut_file* f = file(arg(1));
    const int status = gamut_close(f, &e);
    // A refused close keeps the handle open (fix and close again, or abandon).
    if (status == 0) g_files.erase(reinterpret_cast<std::uintptr_t>(f));
    check(status, e);
  } else if (cmd == "abandon") {
    gamut_file* f = file(arg(1));
    g_files.erase(reinterpret_cast<std::uintptr_t>(f));
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
  } else if (cmd == "read") {
    gamut_file* f = file(arg(1));
    const std::string name = text(arg(2), "name");
    const Sel rows = selection(arg(3)), sites = selection(arg(4));
    const int code = static_cast<int>(scalar(arg(5), "dtype"));
    int64_t shape[4];
    int rank = 0;
    check(gamut_shape(f, name.c_str(), rows.ptr(), sites.ptr(), shape, &rank, &e), e);
    std::vector<int64_t> dims(shape, shape + rank);
    std::size_t total = 1;
    for (const auto d : dims) total *= static_cast<std::size_t>(d);
    std::vector<unsigned char> buf(total * size_of(code));
    check(gamut_read(f, name.c_str(), rows.ptr(), sites.ptr(), code, buf.data(),
                   static_cast<int64_t>(buf.size()), &e),
          e);
    if (dims.size() == 1) dims.push_back(1);   // a column per run
    plhs[0] = from_c_order(buf.data(), dims, code);
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
    std::vector<int64_t> out(static_cast<std::size_t>(rows > 0 ? rows : 1));
    int64_t n = 0;
    check(gamut_select(f, text(arg(2), "where").c_str(), out.data(), static_cast<int64_t>(out.size()), &n, &e), e);
    plhs[0] = mxCreateNumericMatrix(static_cast<mwSize>(n), 1, mxINT64_CLASS, mxREAL);
    if (n) std::memcpy(mxGetData(plhs[0]), out.data(), static_cast<std::size_t>(n) * 8);
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
    if (v != nullptr && mxIsInt64(v)) {
      check(gamut_set_constant(file(arg(1)), text(arg(2), "name").c_str(), text(arg(3), "units").c_str(),
                             GAMUT_INT64, 0.0, *static_cast<int64_t*>(mxGetData(v)), &e), e);
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
      check(gamut_geometry_points(f, GAMUT_FLOAT64, nullptr, static_cast<int64_t>(scalar(arg(3), "n_nodes")),
                                static_cast<int>(scalar(arg(4), "axes")), &e), e);
    } else {
      const int code = dtype_code(mxGetClassID(p));
      if (code != GAMUT_FLOAT64 && code != GAMUT_FLOAT32) usage("points are double or single");
      std::vector<int64_t> dims;
      const auto bytes = to_c_order(p, 2, &dims);
      check(gamut_geometry_points(f, code, bytes.data(), dims[0], static_cast<int>(dims[1]), &e), e);
    }
  } else if (cmd == "geometry_cells") {
    // types (uint8), offsets (int64), connectivity (int64, 0-based as VTK)
    std::vector<uint8_t> types;
    std::vector<int64_t> offsets, conn;
    auto ints = [&](const mxArray* a, std::vector<int64_t>* out) {
      const mwSize n = mxGetNumberOfElements(a);
      for (mwSize i = 0; i < n; ++i) {
        out->push_back(mxIsDouble(a) ? static_cast<int64_t>(mxGetPr(a)[i]) : static_cast<int64_t*>(mxGetData(a))[i]);
      }
    };
    std::vector<int64_t> t64;
    ints(arg(2), &t64);
    for (const auto v : t64) types.push_back(static_cast<uint8_t>(v));
    ints(arg(3), &offsets);
    ints(arg(4), &conn);
    check(gamut_geometry_cells(file(arg(1)), types.data(), static_cast<int64_t>(types.size()), offsets.data(),
                             conn.data(), static_cast<int64_t>(conn.size()), &e),
          e);
  } else if (cmd == "geometry_label") {
    std::vector<int64_t> v;
    const mxArray* a = arg(3);
    const mwSize n = mxGetNumberOfElements(a);
    for (mwSize i = 0; i < n; ++i) v.push_back(static_cast<int64_t>(mxGetPr(a)[i]));
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
    check(gamut_batch_values(file(arg(1)), text(arg(2), "name").c_str(), code, bytes.data(),
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
    if (v != nullptr && mxIsChar(v)) {
      check(gamut_set_note_text(f, key.c_str(), text(v, "value").c_str(), &e), e);
    } else if (v != nullptr && mxIsInt64(v)) {
      check(gamut_set_note_int(f, key.c_str(), *static_cast<int64_t*>(mxGetData(v)), &e), e);
    } else {
      check(gamut_set_note_float(f, key.c_str(), scalar(v, "value"), &e), e);
    }
  } else if (cmd == "model_numbers") {
    gamut_tree* t = nullptr;
    check(gamut_model_numbers(file(arg(1)), text(arg(2), "id").c_str(), &t, &e), e);
    plhs[0] = struct_from(t, "");
    gamut_tree_free(t);
  } else if (cmd == "add_model") {
    // f, id, type, inputs, numbers (struct), repr
    gamut_tree* t = nullptr;
    check(gamut_tree_new(&t, &e), e);
    try {
      if (text(arg(3), "type") == "nearest") {
        nearest_tree(t, arg(5));
      } else {
        tree_from(t, "", arg(5));
      }
    } catch (...) {
      gamut_tree_free(t);
      throw;
    }
    const auto inputs = cellstr(arg(4), "inputs");
    const auto p = pointers(inputs);
    const int status = gamut_add_model(file(arg(1)), text(arg(2), "id").c_str(), text(arg(3), "type").c_str(),
                                     p.data(), static_cast<int64_t>(p.size()), t, text(arg(6), "repr").c_str(), &e);
    gamut_tree_free(t);
    check(status, e);
  } else if (cmd == "nearest_check") {
    gamut_tree* t = nullptr;
    check(gamut_tree_new(&t, &e), e);
    try {
      nearest_tree(t, arg(1));
    } catch (...) {
      gamut_tree_free(t);
      throw;
    }
    const int status = gamut_nearest_check(t, &e);
    gamut_tree_free(t);
    check(status, e);
  } else if (cmd == "nearest_call") {
    // numbers (struct), inputNames (cell), columns (cell of double vectors), output
    gamut_tree* t = nullptr;
    check(gamut_tree_new(&t, &e), e);
    try {
      nearest_tree(t, arg(1));
    } catch (...) {
      gamut_tree_free(t);
      throw;
    }
    std::vector<std::string> names;
    std::vector<std::vector<double>> data;
    int64_t rows = 0;
    try {
      names = cellstr(arg(2), "input names");
      const mxArray* cols = arg(3);
      if (!mxIsCell(cols) || mxGetNumberOfElements(cols) != names.size()) {
        usage("one column per input name");
      }
      for (std::size_t j = 0; j < names.size(); ++j) {
        const mxArray* c = mxGetCell(cols, static_cast<mwIndex>(j));
        if (c == nullptr || !mxIsDouble(c) || mxIsComplex(c)) usage("input columns are real double");
        data.emplace_back(mxGetPr(c), mxGetPr(c) + mxGetNumberOfElements(c));
        if (j > 0 && static_cast<int64_t>(data.back().size()) != rows) {
          usage("input columns have one length");
        }
        rows = static_cast<int64_t>(data.back().size());
      }
    } catch (...) {
      gamut_tree_free(t);
      throw;
    }
    std::vector<const double*> ptrs;
    for (const auto& d : data) ptrs.push_back(d.data());
    const auto np = pointers(names);
    const std::string output = text(arg(4), "output");
    int64_t per = 0;
    int status = gamut_nearest_output_size(t, output.c_str(), &per, &e);
    if (status != 0) {
      gamut_tree_free(t);
      raise(e);
    }
    std::vector<double> out(static_cast<std::size_t>(rows * per));
    status = gamut_nearest_call(t, np.data(), ptrs.data(), static_cast<int>(names.size()), rows, output.c_str(),
                              out.data(), static_cast<int64_t>(out.size()), &e);
    gamut_tree_free(t);
    check(status, e);
    std::vector<int64_t> dims = {rows, per};
    plhs[0] = from_c_order(reinterpret_cast<const unsigned char*>(out.data()), dims, GAMUT_FLOAT64);
  } else if (cmd == "append") {
    int64_t n = 0;
    check(gamut_append(text(arg(1), "dst").c_str(), text(arg(2), "src").c_str(), &n, &e), e);
    plhs[0] = mxCreateDoubleScalar(static_cast<double>(n));
  } else if (cmd == "extract") {
    Sel rows = selection(arg(3));
    if (rows.sel.kind == GAMUT_SEL_ALL) {   // [] here is no rows, not every row
      rows.sel.kind = GAMUT_SEL_INDEX;
      rows.sel.count = 0;
      rows.sel.index = nullptr;
    }
    check(gamut_extract(text(arg(1), "src").c_str(), text(arg(2), "dst").c_str(), rows.ptr(), &e), e);
  } else if (cmd == "write_copy") {
    check(gamut_write_copy(text(arg(1), "src").c_str(), text(arg(2), "dst").c_str(), &e), e);
  } else if (cmd == "evaluate_begin") {
    gamut_file* w = nullptr;
    check(gamut_evaluate_begin(file(arg(1)), text(arg(2), "path").c_str(), &w, &e), e);
    plhs[0] = handle_out(w);
  } else {
    usage("unknown command \"" + cmd + "\"");
  }
}
