#include "h5.hpp"

#include <hdf5_hl.h>

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "names.hpp"

namespace mestra {
namespace internal {
namespace {

// HDF5 prints its own error stack on any failure; the core reports
// failures through mestra::Error instead.
struct SilenceHdf5 {
  SilenceHdf5() { H5Eset_auto2(H5E_DEFAULT, nullptr, nullptr); }
};
const SilenceHdf5 kSilence;

void need(bool ok, const std::string& message) {
  if (!ok) throw Error("", message);
}

std::string parent_of(const std::string& path) {
  const std::size_t at = path.find_last_of('/');
  if (at == std::string::npos || at == 0) return "/";
  return path.substr(0, at);
}

Id open_object(hid_t file, const std::string& path) {
  Id id(H5Oopen(file, path.c_str(), H5P_DEFAULT));
  need(id.valid(), "cannot open \"" + path + "\"");
  return id;
}

std::string token_key(hid_t where, const H5O_token_t& token) {
  char* text = nullptr;
  if (H5Otoken_to_str(where, &token, &text) < 0 || text == nullptr) {
    return std::string();
  }
  std::string out(text);
  H5free_memory(text);
  return out;
}

struct ScaleVisit {
  std::vector<std::string>* names;
  const File* file;
};

herr_t collect_scale(hid_t /*did*/, unsigned /*dim*/, hid_t dsid, void* data) {
  ScaleVisit* visit = static_cast<ScaleVisit*>(data);
  // A dimension's name is the scale's link name, never its NAME
  // attribute, and it is found through the object index, never by
  // asking HDF5 for a path (spec section 9.4).
  visit->names->push_back(visit->file->dataset_link_name(dsid));
  return 0;
}

herr_t collect_member(hid_t group, const char* name, const H5L_info2_t* linfo,
                      void* data) {
  std::vector<Member>* out = static_cast<std::vector<Member>*>(data);
  Member m;
  m.name = name == nullptr ? std::string() : std::string(name);
  if (linfo == nullptr) {
    out->push_back(m);
    return 0;
  }
  switch (linfo->type) {
    case H5L_TYPE_HARD: m.kind = LinkKind::Hard; break;
    case H5L_TYPE_SOFT: m.kind = LinkKind::Soft; break;
    case H5L_TYPE_EXTERNAL: m.kind = LinkKind::External; break;
    default: m.kind = LinkKind::Other; break;
  }
  if (m.kind == LinkKind::Hard) {
    H5O_info2_t oinfo;
    if (H5Oget_info_by_name3(group, m.name.c_str(), &oinfo, H5O_INFO_BASIC,
                             H5P_DEFAULT) >= 0) {
      m.is_group = oinfo.type == H5O_TYPE_GROUP;
      m.is_dataset = oinfo.type == H5O_TYPE_DATASET;
    }
  }
  out->push_back(m);
  return 0;
}

herr_t collect_attr_name(hid_t /*object*/, const char* name,
                         const H5A_info_t* /*info*/, void* data) {
  std::vector<std::string>* out = static_cast<std::vector<std::string>*>(data);
  if (name != nullptr) out->push_back(name);
  return 0;
}

AttrType type_of(hid_t type_id, hid_t space_id) {
  AttrType t;
  t.klass = H5Tget_class(type_id);
  t.size = H5Tget_size(type_id);
  if (t.klass == H5T_STRING) {
    t.variable_length = H5Tis_variable_str(type_id) > 0;
    t.cset = H5Tget_cset(type_id);
    t.strpad = H5Tget_strpad(type_id);
  } else if (t.klass == H5T_INTEGER) {
    t.is_signed = H5Tget_sign(type_id) == H5T_SGN_2;
    t.order = H5Tget_order(type_id);
  } else if (t.klass == H5T_FLOAT) {
    t.order = H5Tget_order(type_id);
  }
  if (space_id >= 0) {
    t.scalar_dataspace = H5Sget_simple_extent_type(space_id) == H5S_SCALAR;
    const hssize_t points = H5Sget_simple_extent_npoints(space_id);
    t.points = points > 0 ? static_cast<std::size_t>(points) : 0;
  }
  return t;
}

std::size_t checked_product(const std::string& path,
                            const std::vector<hsize_t>& shape,
                            std::size_t limit) {
  std::size_t n = 1;
  for (const hsize_t raw : shape) {
    const std::size_t e = static_cast<std::size_t>(raw);
    if (e != 0 && n > limit / e) {
      throw Error("E23", "\"" + path + "\" declares more elements than this "
                                        "reader will read");
    }
    n *= e;
  }
  if (n > limit) {
    throw Error("E23", "\"" + path + "\" declares more elements than this "
                                      "reader will read");
  }
  return n;
}

hid_t file_type(DType t) {
  switch (t) {
    case DType::UInt8: return H5T_STD_U8LE;
    case DType::Int8: return H5T_STD_I8LE;
    case DType::Int32: return H5T_STD_I32LE;
    case DType::Int64: return H5T_STD_I64LE;
    case DType::Float32: return H5T_IEEE_F32LE;
    case DType::Float64: return H5T_IEEE_F64LE;
    case DType::String: break;
  }
  return H5I_INVALID_HID;
}

Id make_space(const std::vector<hsize_t>& shape,
              const std::vector<hsize_t>& maxshape) {
  if (shape.empty()) return Id(H5Screate(H5S_SCALAR));
  const hsize_t* max = maxshape.empty() ? nullptr : maxshape.data();
  return Id(H5Screate_simple(static_cast<int>(shape.size()), shape.data(),
                             max));
}

Id make_dcpl(const std::vector<hsize_t>& chunk, const FilterPipeline& filters) {
  Id dcpl(H5Pcreate(H5P_DATASET_CREATE));
  // Object time tracking off, so that the same content gives the same
  // bytes.
  H5Pset_obj_track_times(dcpl.get(), 0);
  if (!chunk.empty()) {
    H5Pset_chunk(dcpl.get(), static_cast<int>(chunk.size()), chunk.data());
    for (const FilterStep& step : filters) {
      if (step.kind == FilterStep::Shuffle) {
        need(H5Pset_shuffle(dcpl.get()) >= 0, "cannot set the shuffle filter");
      } else {
        need(step.level >= 1 && step.level <= 9,
             "gzip level " + std::to_string(step.level) +
                 " is outside 1 to 9 (spec section 11.2)");
        need(H5Pset_deflate(dcpl.get(), static_cast<unsigned>(step.level)) >= 0,
             "cannot set the gzip filter");
      }
    }
    H5Pset_fill_time(dcpl.get(), H5D_FILL_TIME_ALLOC);
  } else {
    need(filters.empty(), "a filter needs a chunked dataset");
  }
  return dcpl;
}

}  // namespace

void Id::close() {
  if (id_ >= 0) {
    H5Idec_ref(id_);
    id_ = H5I_INVALID_HID;
  }
}

const char* link_kind_name(LinkKind kind) {
  switch (kind) {
    case LinkKind::Missing: return "missing";
    case LinkKind::Hard: return "a hard link";
    case LinkKind::Soft: return "a soft link";
    case LinkKind::External: return "an external link";
    case LinkKind::Other: return "a link of a kind this reader does not know";
  }
  return "a link";
}

std::string scale_name_attribute(hsize_t length) {
  char buffer[128];
  std::snprintf(buffer, sizeof(buffer), "%s%10lld",
                "This is a netCDF dimension but not a netCDF variable.",
                static_cast<long long>(length));
  return std::string(buffer);
}

FilterPipeline pipeline_of(const DsetInfo& info) {
  FilterPipeline out;
  for (const auto& filter : info.filters) {
    if (filter.first == H5Z_FILTER_SHUFFLE) {
      out.push_back(FilterStep::shuffle());
    } else if (filter.first == H5Z_FILTER_DEFLATE) {
      const unsigned level = filter.second.empty() ? 0 : filter.second[0];
      if (level >= 1 && level <= 9) {
        out.push_back(FilterStep::gzip(static_cast<int>(level)));
      }
    }
  }
  return out;
}

Id string_type(std::size_t size) {
  Id t(H5Tcopy(H5T_C_S1));
  need(t.valid(), "cannot make a string type");
  H5Tset_size(t.get(), size == 0 ? 1 : size);
  H5Tset_strpad(t.get(), H5T_STR_NULLPAD);
  H5Tset_cset(t.get(), H5T_CSET_UTF8);
  return t;
}

hid_t memory_type(DType t) {
  switch (t) {
    case DType::UInt8: return H5T_NATIVE_UINT8;
    case DType::Int8: return H5T_NATIVE_INT8;
    case DType::Int32: return H5T_NATIVE_INT32;
    case DType::Int64: return H5T_NATIVE_INT64;
    case DType::Float32: return H5T_NATIVE_FLOAT;
    case DType::Float64: return H5T_NATIVE_DOUBLE;
    case DType::String: break;
  }
  return H5I_INVALID_HID;
}

bool is_spec_string(const AttrType& t) {
  return t.klass == H5T_STRING && !t.variable_length &&
         t.cset == H5T_CSET_UTF8 && t.strpad == H5T_STR_NULLPAD &&
         t.scalar_dataspace;
}

bool is_spec_int64(const AttrType& t) {
  return t.klass == H5T_INTEGER && t.size == 8 && t.is_signed &&
         t.order == H5T_ORDER_LE && t.scalar_dataspace;
}

bool is_spec_int32(const AttrType& t) {
  return t.klass == H5T_INTEGER && t.size == 4 && t.is_signed &&
         t.order == H5T_ORDER_LE && t.scalar_dataspace;
}

bool is_spec_float64(const AttrType& t) {
  return t.klass == H5T_FLOAT && t.size == 8 && t.order == H5T_ORDER_LE &&
         t.scalar_dataspace;
}

bool dtype_of(const AttrType& t, DType* out) {
  if (t.klass == H5T_STRING) {
    if (t.variable_length) return false;
    *out = DType::String;
    return true;
  }
  if (t.klass == H5T_FLOAT) {
    if (t.order != H5T_ORDER_LE) return false;
    if (t.size == 8) {
      *out = DType::Float64;
      return true;
    }
    if (t.size == 4) {
      *out = DType::Float32;
      return true;
    }
    return false;
  }
  if (t.klass == H5T_INTEGER) {
    if (t.size == 1) {
      *out = t.is_signed ? DType::Int8 : DType::UInt8;
      return true;
    }
    if (t.order != H5T_ORDER_LE || !t.is_signed) return false;
    if (t.size == 4) {
      *out = DType::Int32;
      return true;
    }
    if (t.size == 8) {
      *out = DType::Int64;
      return true;
    }
  }
  return false;
}

// --- File ------------------------------------------------------------

File File::open_read(const std::string& path) {
  File f;
  f.id_ = Id(H5Fopen(path.c_str(), H5F_ACC_RDONLY, H5P_DEFAULT));
  if (!f.id_.valid()) {
    throw Error("E1", "cannot open \"" + path + "\" as an HDF5 file");
  }
  return f;
}

File File::open_write(const std::string& path) {
  File f;
  f.id_ = Id(H5Fopen(path.c_str(), H5F_ACC_RDWR, H5P_DEFAULT));
  if (!f.id_.valid()) {
    throw Error("", "cannot open \"" + path + "\" for writing");
  }
  return f;
}

File File::create(const std::string& path) {
  File f;
  Id fcpl(H5Pcreate(H5P_FILE_CREATE));
  H5Pset_obj_track_times(fcpl.get(), 0);
  // Spec section 11.4: persistent free-space management, so the space a
  // rewritten compressed chunk leaves is reused, also after the file is
  // closed and reopened; it needs the 1.10 file format.
  need(H5Pset_file_space_strategy(fcpl.get(), H5F_FSPACE_STRATEGY_FSM_AGGR, 1,
                                  1) >= 0,
       "cannot set the file-space strategy");
  Id fapl(H5Pcreate(H5P_FILE_ACCESS));
  need(H5Pset_libver_bounds(fapl.get(), H5F_LIBVER_EARLIEST, H5F_LIBVER_V110) >= 0,
       "cannot set the library version bounds");
  f.id_ = Id(H5Fcreate(path.c_str(), H5F_ACC_TRUNC, fcpl.get(), fapl.get()));
  if (!f.id_.valid()) throw Error("", "cannot create \"" + path + "\"");
  return f;
}

void File::flush() {
  need(H5Fflush(id_.get(), H5F_SCOPE_GLOBAL) >= 0, "cannot flush the file");
}

LinkKind File::link_kind(const std::string& path) const {
  if (path == "/") return LinkKind::Hard;
  std::size_t at = 1;
  LinkKind last = LinkKind::Hard;
  while (at <= path.size()) {
    const std::size_t next = path.find('/', at);
    const std::string prefix =
        next == std::string::npos ? path : path.substr(0, next);
    H5L_info2_t info;
    if (H5Lget_info2(id_.get(), prefix.c_str(), &info, H5P_DEFAULT) < 0) {
      return LinkKind::Missing;
    }
    switch (info.type) {
      case H5L_TYPE_HARD: last = LinkKind::Hard; break;
      case H5L_TYPE_SOFT: last = LinkKind::Soft; break;
      case H5L_TYPE_EXTERNAL: last = LinkKind::External; break;
      default: last = LinkKind::Other; break;
    }
    if (next == std::string::npos) break;
    if (last != LinkKind::Hard) return last;
    at = next + 1;
  }
  return last;
}

bool File::exists(const std::string& path) const {
  return link_kind(path) != LinkKind::Missing;
}

bool File::is_group(const std::string& path) const {
  if (link_kind(path) != LinkKind::Hard) return false;
  H5O_info2_t info;
  if (H5Oget_info_by_name3(id_.get(), path.c_str(), &info, H5O_INFO_BASIC,
                           H5P_DEFAULT) < 0) {
    return false;
  }
  return info.type == H5O_TYPE_GROUP;
}

bool File::is_dataset(const std::string& path) const {
  if (link_kind(path) != LinkKind::Hard) return false;
  H5O_info2_t info;
  if (H5Oget_info_by_name3(id_.get(), path.c_str(), &info, H5O_INFO_BASIC,
                           H5P_DEFAULT) < 0) {
    return false;
  }
  return info.type == H5O_TYPE_DATASET;
}

std::vector<Member> File::members(const std::string& path) const {
  std::vector<Member> out;
  if (!is_group(path)) return out;
  Id group(H5Gopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(group.valid(), "cannot open the group \"" + path + "\"");
  // One ordered iteration, never a lookup per index, which is quadratic
  // on groups in dense link storage.
  hsize_t at = 0;
  H5Literate2(group.get(), H5_INDEX_NAME, H5_ITER_INC, &at, collect_member,
              &out);
  return out;
}

std::vector<RawAttr> File::attributes(const std::string& path) const {
  std::vector<RawAttr> out;
  if (link_kind(path) != LinkKind::Hard) return out;
  Id object = open_object(id_.get(), path);
  std::vector<std::string> names;
  hsize_t at = 0;
  H5Aiterate2(object.get(), H5_INDEX_NAME, H5_ITER_INC, &at, collect_attr_name,
              &names);
  for (const std::string& attr_name : names) {
    Id attr(H5Aopen(object.get(), attr_name.c_str(), H5P_DEFAULT));
    if (!attr.valid()) continue;
    RawAttr a;
    a.name = attr_name;
    Id type(H5Aget_type(attr.get()));
    Id space(H5Aget_space(attr.get()));
    a.type = type_of(type.get(), space.get());
    // Every attribute the format defines is a scalar, so only scalars are
    // read; anything larger is marked and its contents never allocated (a
    // crafted file can declare millions of elements).
    const std::size_t points = a.type.points;
    const bool readable = points == 1;
    if (points > 1) a.too_large = true;

    if (a.type.klass == H5T_STRING && readable) {
      if (a.type.variable_length) {
        std::vector<char*> values(points, nullptr);
        Id mem(H5Tcopy(H5T_C_S1));
        H5Tset_size(mem.get(), H5T_VARIABLE);
        H5Tset_cset(mem.get(), a.type.cset);
        if (H5Aread(attr.get(), mem.get(), values.data()) >= 0) {
          if (values[0] != nullptr) a.raw_bytes = values[0];
        }
        for (char* p : values) {
          if (p != nullptr) H5free_memory(p);
        }
      } else if (a.type.size > 0 && points > kMaxAttributeBytes / a.type.size) {
        a.too_large = true;
      } else {
        std::string bytes(a.type.size * points, '\0');
        if (!bytes.empty() && H5Aread(attr.get(), type.get(), &bytes[0]) >= 0) {
          a.raw_bytes = bytes.substr(0, a.type.size);
        }
      }
      a.value = AttrValue::text(strip_nul(a.raw_bytes));
    } else if (a.type.klass == H5T_INTEGER && readable) {
      std::vector<std::int64_t> values(points, 0);
      if (H5Aread(attr.get(), H5T_NATIVE_INT64, values.data()) >= 0) {
        if (a.type.size == 1 && a.type.is_signed) {
          a.value = AttrValue::boolean(values[0] != 0);
        } else {
          a.value = AttrValue::integer(values[0]);
        }
      }
    } else if (a.type.klass == H5T_FLOAT && readable) {
      std::vector<double> values(points, 0.0);
      if (H5Aread(attr.get(), H5T_NATIVE_DOUBLE, values.data()) >= 0) {
        a.value = AttrValue::real(values[0]);
      }
    }
    out.push_back(a);
  }
  return out;
}

DsetInfo File::dataset_info(const std::string& path, bool scales) const {
  DsetInfo info;
  if (!is_dataset(path)) return info;
  info.is_dataset = true;
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open the dataset \"" + path + "\"");
  Id type(H5Dget_type(dset.get()));
  Id space(H5Dget_space(dset.get()));
  info.type = type_of(type.get(), space.get());
  const int rank = H5Sget_simple_extent_ndims(space.get());
  if (rank > 0) {
    info.shape.resize(static_cast<std::size_t>(rank));
    info.maxshape.resize(static_cast<std::size_t>(rank));
    H5Sget_simple_extent_dims(space.get(), info.shape.data(),
                              info.maxshape.data());
  }
  Id dcpl(H5Dget_create_plist(dset.get()));
  info.chunked = H5Pget_layout(dcpl.get()) == H5D_CHUNKED;
  if (info.chunked && rank > 0) {
    info.chunk.resize(static_cast<std::size_t>(rank));
    H5Pget_chunk(dcpl.get(), rank, info.chunk.data());
  }
  const int filters = H5Pget_nfilters(dcpl.get());
  for (int i = 0; i < filters; ++i) {
    unsigned flags = 0;
    unsigned config = 0;
    std::size_t count = 0;
    if (H5Pget_filter2(dcpl.get(), static_cast<unsigned>(i), &flags, &count,
                       nullptr, 0, nullptr, &config) < 0) {
      continue;
    }
    if (count > kMaxFilterParameters) count = kMaxFilterParameters;
    std::vector<unsigned> params(count, 0u);
    std::size_t given = count;
    const H5Z_filter_t id = H5Pget_filter2(
        dcpl.get(), static_cast<unsigned>(i), &flags, &given,
        params.empty() ? nullptr : params.data(), 0, nullptr, &config);
    if (id < 0) continue;
    if (given < params.size()) params.resize(given);
    info.filters.emplace_back(static_cast<int>(id), params);
  }
  H5D_fill_value_t fill = H5D_FILL_VALUE_DEFAULT;
  if (H5Pfill_value_defined(dcpl.get(), &fill) >= 0) {
    info.has_fill_value_set = fill == H5D_FILL_VALUE_USER_DEFINED;
  }
  unsigned crt_order = 0;
  if (H5Pget_attr_creation_order(dcpl.get(), &crt_order) >= 0) {
    info.attr_order_tracked = (crt_order & H5P_CRT_ORDER_TRACKED) != 0;
    info.attr_order_indexed = (crt_order & H5P_CRT_ORDER_INDEXED) != 0;
  }
  if (!scales) return info;
  info.is_scale = H5DSis_scale(dset.get()) > 0;
  info.scales.resize(static_cast<std::size_t>(rank > 0 ? rank : 0));
  if (!info.is_scale) {
    for (int axis = 0; axis < rank; ++axis) {
      ScaleVisit visit{&info.scales[static_cast<std::size_t>(axis)], this};
      int index = 0;
      H5DSiterate_scales(dset.get(), static_cast<unsigned>(axis), &index,
                         collect_scale, &visit);
    }
  } else if (rank == 1) {
    // A coordinate variable carries itself as its own scale.
    info.scales[0].push_back(dataset_link_name(dset.get()));
  }
  return info;
}

namespace {

// The file-space selection and per-axis counts for `sel` over `shape`.
// The selection is the cartesian product of each axis's runs; axes
// beyond `sel` are whole.
std::vector<hsize_t> select(hid_t space, const std::string& path,
                            const std::vector<hsize_t>& shape,
                            const std::vector<Selection>& sel) {
  const std::size_t rank = shape.size();
  need(sel.size() <= rank, "\"" + path + "\" has " + std::to_string(rank) +
                               " axes and was given " +
                               std::to_string(sel.size()) + " selections");
  std::vector<std::vector<std::pair<std::int64_t, std::int64_t>>> runs(rank);
  std::vector<hsize_t> count(rank, 0);
  for (std::size_t a = 0; a < rank; ++a) {
    const std::int64_t length = static_cast<std::int64_t>(shape[a]);
    if (a < sel.size()) {
      count[a] = static_cast<hsize_t>(sel[a].count(length, path));
      runs[a] = sel[a].runs(length, path);
    } else {
      count[a] = shape[a];
      if (length > 0) runs[a].emplace_back(0, length);
    }
  }
  for (std::size_t a = 0; a < rank; ++a) {
    if (count[a] == 0) {
      H5Sselect_none(space);
      return count;
    }
  }
  if (rank == 0) {
    H5Sselect_all(space);
    return count;
  }
  // Odometer over the runs of every axis.
  std::vector<std::size_t> at(rank, 0);
  bool first = true;
  std::vector<hsize_t> start(rank), block(rank);
  while (true) {
    for (std::size_t a = 0; a < rank; ++a) {
      start[a] = static_cast<hsize_t>(runs[a][at[a]].first);
      block[a] = static_cast<hsize_t>(runs[a][at[a]].second);
    }
    H5Sselect_hyperslab(space, first ? H5S_SELECT_SET : H5S_SELECT_OR,
                        start.data(), nullptr, block.data(), nullptr);
    first = false;
    std::size_t a = rank;
    while (a > 0) {
      --a;
      if (++at[a] < runs[a].size()) break;
      at[a] = 0;
      if (a == 0) return count;
    }
  }
}

}  // namespace

std::vector<std::int64_t> File::selected_shape(
    const std::string& path, const std::vector<Selection>& sel) const {
  const DsetInfo info = dataset_info(path, false);
  need(info.is_dataset, "\"" + path + "\" is not a dataset");
  std::vector<std::int64_t> out;
  for (std::size_t a = 0; a < info.shape.size(); ++a) {
    const std::int64_t length = static_cast<std::int64_t>(info.shape[a]);
    out.push_back(a < sel.size() ? sel[a].count(length, path) : length);
  }
  return out;
}

bool File::read_gathered(const std::string& path, const std::vector<hsize_t>& shape, DType mem,
                         const std::vector<Selection>& sel, void* out,
                         std::size_t out_bytes) const {
  // HDF5 joins hyperslabs at a cost that grows faster than their number:
  // 400 x 400 scattered indices took 2 s against 0.02 s for the whole
  // field.  Many blocks are read as one bounding box and gathered here.
  const std::size_t rank = shape.size();
  if (rank == 0 || sel.empty()) return false;
  std::vector<std::vector<std::pair<std::int64_t, std::int64_t>>> runs(rank);
  std::vector<std::int64_t> lo(rank);
  std::vector<std::size_t> extent(rank);
  std::vector<Selection> box(rank);
  std::size_t blocks = 1, box_elems = 1, n = 1;
  const std::size_t kMaxBlocks = 64;
  for (std::size_t a = 0; a < rank; ++a) {
    const std::int64_t length = static_cast<std::int64_t>(shape[a]);
    if (a < sel.size()) {
      runs[a] = sel[a].runs(length, path);
    } else if (length > 0) {
      runs[a].emplace_back(0, length);
    }
    if (runs[a].empty()) return false;
    blocks = blocks > kMaxBlocks ? blocks : blocks * runs[a].size();
    lo[a] = runs[a].front().first;
    const std::int64_t hi = runs[a].back().first + runs[a].back().second;
    extent[a] = static_cast<std::size_t>(hi - lo[a]);
    box[a] = Selection::range(lo[a], hi);
    if (box_elems > kMaxDatasetElements / extent[a]) return false;
    box_elems *= extent[a];
    std::size_t selected = 0;
    for (const auto& r : runs[a]) selected += static_cast<std::size_t>(r.second);
    n *= selected;
  }
  if (blocks <= kMaxBlocks) return false;
  const std::size_t item = dtype_size(mem);
  if (out_bytes != n * item) return false;   // the plain path reports it
  // The box may hold much that is not selected; it is used while it stays
  // within a few times the result (or 64 MiB).
  const std::size_t cap = std::max<std::size_t>(std::size_t(64) << 20, 4 * out_bytes);
  if (box_elems > cap / item) return false;
  std::vector<unsigned char> tmp(box_elems * item);
  read(path, mem, box, tmp.data(), tmp.size());
  std::vector<std::size_t> stride(rank, 1);
  for (std::size_t a = rank - 1; a > 0; --a) stride[a - 1] = stride[a] * extent[a];
  // Positions selected on every axis but the last, relative to the box; the
  // last axis is copied a run at a time.
  std::vector<std::vector<std::size_t>> at_axis(rank - 1);
  for (std::size_t a = 0; a + 1 < rank; ++a) {
    for (const auto& r : runs[a]) {
      for (std::int64_t j = 0; j < r.second; ++j) {
        at_axis[a].push_back(static_cast<std::size_t>(r.first + j - lo[a]));
      }
    }
  }
  unsigned char* dst = static_cast<unsigned char*>(out);
  std::vector<std::size_t> at(rank - 1, 0);
  while (true) {
    std::size_t base = 0;
    for (std::size_t a = 0; a + 1 < rank; ++a) base += at_axis[a][at[a]] * stride[a];
    for (const auto& r : runs[rank - 1]) {
      const std::size_t bytes = static_cast<std::size_t>(r.second) * item;
      std::memcpy(dst, tmp.data() + (base + static_cast<std::size_t>(r.first - lo[rank - 1])) * item,
                  bytes);
      dst += bytes;
    }
    std::size_t a = rank - 1;
    bool done = true;
    while (a > 0) {
      --a;
      if (++at[a] < at_axis[a].size()) {
        done = false;
        break;
      }
      at[a] = 0;
    }
    if (done) break;
  }
  return true;
}

void File::read(const std::string& path, DType mem,
                const std::vector<Selection>& sel, void* out,
                std::size_t out_bytes) const {
  need(mem != DType::String, "strings are read with read_strings");
  const DsetInfo info = dataset_info(path, false);
  need(info.is_dataset, "\"" + path + "\" is not a dataset");
  if (read_gathered(path, info.shape, mem, sel, out, out_bytes)) return;
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open \"" + path + "\"");
  Id space(H5Dget_space(dset.get()));
  const std::vector<hsize_t> count = select(space.get(), path, info.shape, sel);
  const std::size_t n = checked_product(path, count, kMaxDatasetElements);
  need(out_bytes == n * dtype_size(mem),
       "\"" + path + "\": the buffer holds " + std::to_string(out_bytes) +
           " bytes and the selection needs " +
           std::to_string(n * dtype_size(mem)));
  if (n == 0) return;
  Id memspace = count.empty() ? Id(H5Screate(H5S_SCALAR))
                              : Id(H5Screate_simple(static_cast<int>(count.size()),
                                                    count.data(), nullptr));
  need(H5Dread(dset.get(), memory_type(mem), memspace.get(), space.get(),
               H5P_DEFAULT, out) >= 0,
       "cannot read \"" + path + "\"");
}

std::vector<double> File::read_f64(const std::string& path) const {
  const DsetInfo info = dataset_info(path, false);
  std::vector<double> out(checked_product(path, info.shape, kMaxDatasetElements));
  read(path, DType::Float64, {}, out.data(), out.size() * sizeof(double));
  return out;
}

std::vector<std::int64_t> File::read_i64(const std::string& path) const {
  const DsetInfo info = dataset_info(path, false);
  std::vector<std::int64_t> out(
      checked_product(path, info.shape, kMaxDatasetElements));
  read(path, DType::Int64, {}, out.data(), out.size() * sizeof(std::int64_t));
  return out;
}

std::vector<std::string> File::read_strings(const std::string& path, std::size_t max_entries,
                                            std::size_t max_bytes) const {
  const DsetInfo info = dataset_info(path, false);
  need(info.is_dataset && info.type.klass == H5T_STRING,
       "\"" + path + "\" is not a string dataset");
  need(!info.type.variable_length,
       "\"" + path + "\" holds variable-length strings");
  const std::size_t count = checked_product(path, info.shape, max_entries);
  std::vector<std::string> out;
  if (count == 0) return out;
  const std::size_t item = info.type.size;
  if (item != 0 && count > max_bytes / item) {
    throw Error("E23", "\"" + path + "\" declares more bytes than this reader "
                                     "will read");
  }
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  Id type(H5Dget_type(dset.get()));
  std::string buffer(item * count, '\0');
  need(H5Dread(dset.get(), type.get(), H5S_ALL, H5S_ALL, H5P_DEFAULT,
               &buffer[0]) >= 0,
       "cannot read \"" + path + "\"");
  out.reserve(count);
  for (std::size_t i = 0; i < count; ++i) {
    out.push_back(strip_nul(buffer.substr(i * item, item)));
  }
  return out;
}

// --- writing ---------------------------------------------------------

void File::make_group(const std::string& path) {
  if (path == "/" || exists(path)) return;
  make_group(parent_of(path));
  Id gcpl(H5Pcreate(H5P_GROUP_CREATE));
  H5Pset_obj_track_times(gcpl.get(), 0);
  Id group(H5Gcreate2(id_.get(), path.c_str(), H5P_DEFAULT, gcpl.get(),
                      H5P_DEFAULT));
  need(group.valid(), "cannot create the group \"" + path + "\"");
}

void File::write_raw_string_attr(const std::string& path,
                                 const std::string& name,
                                 const std::string& bytes) {
  Id object = open_object(id_.get(), path);
  const std::size_t size = bytes.empty() ? 1 : bytes.size();
  Id type = string_type(size);
  Id space(H5Screate(H5S_SCALAR));
  Id attr(H5Acreate2(object.get(), name.c_str(), type.get(), space.get(),
                     H5P_DEFAULT, H5P_DEFAULT));
  need(attr.valid(), "cannot create the attribute \"" + name + "\"");
  std::string padded = bytes;
  padded.resize(size, '\0');
  need(H5Awrite(attr.get(), type.get(), padded.data()) >= 0,
       "cannot write the attribute \"" + name + "\"");
}

void File::write_attr(const std::string& path, const std::string& name,
                      const AttrValue& value) {
  if (value.kind() == AttrValue::Kind::Str) {
    write_raw_string_attr(path, name, value.as_text());
    return;
  }
  Id object = open_object(id_.get(), path);
  Id space(H5Screate(H5S_SCALAR));
  hid_t ftype = H5T_STD_I64LE;
  hid_t mtype = H5T_NATIVE_INT64;
  std::int64_t i = 0;
  signed char b = 0;
  double d = 0.0;
  const void* data = &i;
  switch (value.kind()) {
    case AttrValue::Kind::Bool:
      ftype = H5T_STD_I8LE;
      mtype = H5T_NATIVE_SCHAR;
      b = value.as_bool() ? 1 : 0;
      data = &b;
      break;
    case AttrValue::Kind::Int:
      i = value.as_int();
      break;
    case AttrValue::Kind::Float:
      ftype = H5T_IEEE_F64LE;
      mtype = H5T_NATIVE_DOUBLE;
      d = value.as_float();
      data = &d;
      break;
    case AttrValue::Kind::Str: break;
  }
  Id attr(H5Acreate2(object.get(), name.c_str(), ftype, space.get(),
                     H5P_DEFAULT, H5P_DEFAULT));
  need(attr.valid(), "cannot create the attribute \"" + name + "\"");
  need(H5Awrite(attr.get(), mtype, data) >= 0,
       "cannot write the attribute \"" + name + "\"");
}

void File::replace_attr(const std::string& path, const std::string& name,
                        const AttrValue& value) {
  {
    Id object = open_object(id_.get(), path);
    if (H5Aexists(object.get(), name.c_str()) > 0) {
      need(H5Adelete(object.get(), name.c_str()) >= 0,
           "cannot replace the attribute \"" + name + "\"");
    }
  }
  write_attr(path, name, value);
}

void File::create_dataset(const std::string& path, DType dtype,
                          std::size_t string_size,
                          const std::vector<hsize_t>& shape,
                          const std::vector<hsize_t>& maxshape,
                          const std::vector<hsize_t>& chunk,
                          const FilterPipeline& filters,
                          bool scale_properties) {
  make_group(parent_of(path));
  Id space = make_space(shape, maxshape);
  // A chunk may not exceed a fixed extent: clamp it, keeping at least 1.
  std::vector<hsize_t> fitted = chunk;
  for (std::size_t i = 0; i < fitted.size() && i < shape.size(); ++i) {
    const hsize_t limit = maxshape.empty() ? shape[i] : maxshape[i];
    if (limit != H5S_UNLIMITED && fitted[i] > limit) fitted[i] = limit == 0 ? 1 : limit;
  }
  Id dcpl = make_dcpl(fitted, filters);
  if (scale_properties) {
    // A dataset that will be a dimension scale (the `row` coordinate
    // variable) gets the creation order every scale has (section 9.4).
    H5Pset_attr_creation_order(dcpl.get(),
                               H5P_CRT_ORDER_TRACKED | H5P_CRT_ORDER_INDEXED);
  }
  Id strtype;
  hid_t ftype;
  if (dtype == DType::String) {
    strtype = string_type(string_size);
    ftype = strtype.get();
  } else {
    ftype = file_type(dtype);
  }
  Id dset(H5Dcreate2(id_.get(), path.c_str(), ftype, space.get(), H5P_DEFAULT,
                     dcpl.get(), H5P_DEFAULT));
  need(dset.valid(), "cannot create the dataset \"" + path + "\"");
}

void File::write(const std::string& path, DType mem,
                 const std::vector<hsize_t>& start,
                 const std::vector<hsize_t>& count, const void* data) {
  need(mem != DType::String, "strings are written with write_strings");
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open \"" + path + "\"");
  Id space(H5Dget_space(dset.get()));
  const int rank = H5Sget_simple_extent_ndims(space.get());
  need(static_cast<std::size_t>(rank) == start.size() &&
           start.size() == count.size(),
       "\"" + path + "\": a write needs a start and count per axis");
  for (const hsize_t c : count) {
    if (c == 0) return;
  }
  Id memspace;
  if (rank == 0) {
    memspace = Id(H5Screate(H5S_SCALAR));
  } else {
    need(H5Sselect_hyperslab(space.get(), H5S_SELECT_SET, start.data(),
                             nullptr, count.data(), nullptr) >= 0,
         "\"" + path + "\": the block is outside the dataset");
    memspace = Id(H5Screate_simple(rank, count.data(), nullptr));
  }
  need(H5Dwrite(dset.get(), memory_type(mem), memspace.get(), space.get(),
                H5P_DEFAULT, data) >= 0,
       "cannot write \"" + path + "\"");
}

void File::write_strings(const std::string& path, hsize_t start,
                         const std::vector<std::string>& values) {
  if (values.empty()) return;
  const DsetInfo info = dataset_info(path, false);
  need(info.is_dataset && info.type.klass == H5T_STRING &&
           !info.type.variable_length && info.shape.size() == 1,
       "\"" + path + "\" is not a one-dimensional fixed-length string dataset");
  const std::size_t item = info.type.size;
  std::string buffer(item * values.size(), '\0');
  for (std::size_t i = 0; i < values.size(); ++i) {
    need(values[i].size() <= item,
         "\"" + path + "\" holds strings of " + std::to_string(item) +
             " bytes and \"" + values[i] + "\" is longer");
    std::memcpy(&buffer[i * item], values[i].data(), values[i].size());
  }
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  Id type(H5Dget_type(dset.get()));
  Id space(H5Dget_space(dset.get()));
  const hsize_t count = values.size();
  need(H5Sselect_hyperslab(space.get(), H5S_SELECT_SET, &start, nullptr,
                           &count, nullptr) >= 0,
       "\"" + path + "\": the strings lie outside the dataset");
  Id memspace(H5Screate_simple(1, &count, nullptr));
  need(H5Dwrite(dset.get(), type.get(), memspace.get(), space.get(),
                H5P_DEFAULT, buffer.data()) >= 0,
       "cannot write \"" + path + "\"");
}

void File::set_extent(const std::string& path,
                      const std::vector<hsize_t>& shape) {
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open \"" + path + "\"");
  need(H5Dset_extent(dset.get(), shape.data()) >= 0,
       "cannot resize \"" + path + "\"");
}

void File::make_scale(const std::string& path, hsize_t length, bool unlimited) {
  make_group(parent_of(path));
  const hsize_t max = unlimited ? H5S_UNLIMITED : length;
  Id space(H5Screate_simple(1, &length, &max));
  Id dcpl(H5Pcreate(H5P_DATASET_CREATE));
  // Attribute creation order tracked and indexed gives the scale a
  // version 2 object header, so its REFERENCE_LIST lives in the heap and
  // a scale can carry more than 4085 attachments (spec section 9.4).
  H5Pset_attr_creation_order(dcpl.get(),
                             H5P_CRT_ORDER_TRACKED | H5P_CRT_ORDER_INDEXED);
  H5Pset_obj_track_times(dcpl.get(), 0);
  const hsize_t chunk = unlimited ? 1 : (length == 0 ? 1 : length);
  H5Pset_chunk(dcpl.get(), 1, &chunk);
  H5Pset_fill_time(dcpl.get(), H5D_FILL_TIME_ALLOC);
  Id dset(H5Dcreate2(id_.get(), path.c_str(), H5T_IEEE_F32BE, space.get(),
                     H5P_DEFAULT, dcpl.get(), H5P_DEFAULT));
  need(dset.valid(), "cannot create the dimension scale \"" + path + "\"");
  const std::string name = scale_name_attribute(length);
  need(H5DSset_scale(dset.get(), name.c_str()) >= 0,
       "cannot mark \"" + path + "\" as a dimension scale");
}

void File::set_scale_length(const std::string& path, hsize_t length) {
  set_extent(path, {length});
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open the dimension scale \"" + path + "\"");
  const std::string name = scale_name_attribute(length);
  if (H5Aexists(dset.get(), "NAME") > 0) {
    need(H5Adelete(dset.get(), "NAME") >= 0,
         "cannot replace the NAME of \"" + path + "\"");
  }
  // NAME as H5DSset_scale writes it: NUL-terminated, one byte longer.
  Id type(H5Tcopy(H5T_C_S1));
  H5Tset_size(type.get(), name.size() + 1);
  Id space(H5Screate(H5S_SCALAR));
  Id attr(H5Acreate2(dset.get(), "NAME", type.get(), space.get(), H5P_DEFAULT,
                     H5P_DEFAULT));
  need(attr.valid(), "cannot write the NAME of \"" + path + "\"");
  need(H5Awrite(attr.get(), type.get(), name.c_str()) >= 0,
       "cannot write the NAME of \"" + path + "\"");
}

void File::mark_coordinate_scale(const std::string& path,
                                 const std::string& name) {
  Id dset(H5Dopen2(id_.get(), path.c_str(), H5P_DEFAULT));
  need(dset.valid(), "cannot open \"" + path + "\"");
  need(H5DSset_scale(dset.get(), name.c_str()) >= 0,
       "cannot mark \"" + path + "\" as a dimension scale");
}

void File::attach_scale(const std::string& dataset, const std::string& scale,
                        unsigned axis) {
  Id d(H5Dopen2(id_.get(), dataset.c_str(), H5P_DEFAULT));
  need(d.valid(), "cannot open \"" + dataset + "\"");
  Id s(H5Dopen2(id_.get(), scale.c_str(), H5P_DEFAULT));
  need(s.valid(), "cannot open the dimension scale \"" + scale + "\"");
  // A failed attachment has already deleted the REFERENCE_LIST it was
  // extending; the file must be discarded, and the message says so.
  need(H5DSattach_scale(d.get(), s.get(), axis) >= 0,
       "cannot attach \"" + scale + "\" to \"" + dataset +
           "\"; the scale's REFERENCE_LIST was lost and the file must be "
           "discarded");
}

void File::detach_scale(const std::string& dataset, const std::string& scale,
                        unsigned axis) {
  Id d(H5Dopen2(id_.get(), dataset.c_str(), H5P_DEFAULT));
  need(d.valid(), "cannot open \"" + dataset + "\"");
  Id s(H5Dopen2(id_.get(), scale.c_str(), H5P_DEFAULT));
  need(s.valid(), "cannot open the dimension scale \"" + scale + "\"");
  need(H5DSdetach_scale(d.get(), s.get(), axis) >= 0,
       "cannot detach \"" + scale + "\" from \"" + dataset + "\"");
}

void File::build_object_index() const {
  object_index_built_ = true;
  object_paths_.clear();
  std::vector<std::pair<std::string, int>> todo;
  todo.emplace_back("/", 0);
  while (!todo.empty()) {
    const std::pair<std::string, int> here = todo.back();
    todo.pop_back();
    if (here.second > kMaxGroupDepth) continue;
    if (object_paths_.size() >= kMaxIndexedObjects) return;
    for (const Member& m : members(here.first)) {
      if (m.kind != LinkKind::Hard) continue;
      const std::string child =
          (here.first == "/" ? std::string("/") : here.first + "/") + m.name;
      if (m.is_group) {
        todo.emplace_back(child, here.second + 1);
        continue;
      }
      if (!m.is_dataset) continue;
      H5O_info2_t info;
      if (H5Oget_info_by_name3(id_.get(), child.c_str(), &info, H5O_INFO_BASIC,
                               H5P_DEFAULT) < 0) {
        continue;
      }
      const std::string key = token_key(id_.get(), info.token);
      if (!key.empty()) object_paths_[key] = child;
      if (object_paths_.size() >= kMaxIndexedObjects) return;
    }
  }
}

std::string File::dataset_path(hid_t object) const {
  if (!object_index_built_) build_object_index();
  H5O_info2_t info;
  if (H5Oget_info3(object, &info, H5O_INFO_BASIC) < 0) return std::string();
  const std::string key = token_key(id_.get(), info.token);
  if (key.empty()) return std::string();
  auto it = object_paths_.find(key);
  if (it == object_paths_.end()) {
    // A dataset created after the index was built: rebuild once.
    build_object_index();
    it = object_paths_.find(key);
    if (it == object_paths_.end()) return std::string();
  }
  return it->second;
}

std::string File::dataset_link_name(hid_t object) const {
  const std::string path = dataset_path(object);
  const std::size_t at = path.find_last_of('/');
  return at == std::string::npos ? path : path.substr(at + 1);
}

void File::remove_link(const std::string& path) {
  need(H5Ldelete(id_.get(), path.c_str(), H5P_DEFAULT) >= 0,
       "cannot remove \"" + path + "\"");
  object_index_built_ = false;
}

void File::copy_from(const File& src, const std::string& src_path,
                     const std::string& dst_path) {
  make_group(parent_of(dst_path));
  need(H5Ocopy(src.get(), src_path.c_str(), id_.get(), dst_path.c_str(),
               H5P_DEFAULT, H5P_DEFAULT) >= 0,
       "cannot copy \"" + src_path + "\"");
  object_index_built_ = false;
}

}  // namespace internal
}  // namespace mestra
