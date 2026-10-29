// A thin RAII layer over the HDF5 C API and its dimension-scale API, so
// that the reader, the writer and the validator see a file the same way.
// Ported from the version 0 C++ library, whose limits, link handling and
// dimension-scale index were hardened against hostile files; the reads
// and writes are generalised to typed buffers and per-axis selections.
// Internal.
#ifndef GAMUT_CORE_H5_HPP
#define GAMUT_CORE_H5_HPP

#include <hdf5.h>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <map>
#include <set>
#include <initializer_list>
#include <string>
#include <utility>
#include <vector>

#include "types.hpp"

namespace gamut_core {
namespace internal {

// An HDF5 identifier that closes itself.
class Id {
 public:
  Id() : id_(H5I_INVALID_HID) {}
  explicit Id(hid_t id) : id_(id) {}
  Id(const Id&) = delete;
  Id& operator=(const Id&) = delete;
  Id(Id&& o) noexcept : id_(o.id_) { o.id_ = H5I_INVALID_HID; }
  Id& operator=(Id&& o) noexcept {
    if (this != &o) {
      close();
      id_ = o.id_;
      o.id_ = H5I_INVALID_HID;
    }
    return *this;
  }
  ~Id() { close(); }

  hid_t get() const { return id_; }
  bool valid() const { return id_ >= 0; }
  void close();

 private:
  hid_t id_;
};

// Every count and length below comes out of the file, so each one is
// checked against a limit before it sizes a buffer (spec section 9.6).
const std::size_t kMaxAttributeBytes = std::size_t(16) << 20;
// Category tables are read when a file opens, as structure.
const std::size_t kMaxTableEntries = std::size_t(1) << 24;
const std::size_t kMaxTableBytes = std::size_t(256) << 20;
const std::size_t kMaxDatasetElements = std::size_t(1) << 31;
const std::size_t kMaxDatasetBytes = std::size_t(1) << 33;
const std::size_t kMaxFilterParameters = 1024;

// `n` elements of `item` bytes, a count taken from the file (or a product
// of such counts, given as factors), checked against the eager caps
// before it sizes a buffer: E23 above them.
std::size_t checked_count(const std::string& path, std::size_t item,
                          std::initializer_list<std::int64_t> factors);

// The element count of `shape`, a shape taken from the file: E23 above
// `limit`.
std::size_t checked_product(const std::string& path,
                            const std::vector<hsize_t>& shape,
                            std::size_t limit);

// A read touching more chunks than this is refused (E23): HDF5 keeps state
// per chunk touched, so a file of tiny chunks would make a small read cost
// gigabytes (spec section 9.6).
const std::size_t kMaxChunksRead = std::size_t(1) << 20;
// Reads over every row that the library makes on the caller's behalf: the
// where selector scans at most this many rows, and label names (a string
// per row) are read for at most kMaxNamesRead rows at once.
const std::int64_t kMaxRowsScanned = std::int64_t(1) << 27;
const std::int64_t kMaxNamesRead = std::int64_t(1) << 25;
struct DsetInfo;
// The chunks a selection of a chunked dataset touches; E23 above the cap.
void check_chunks_touched(const std::string& path, const DsetInfo& info,
                          const std::vector<Selection>& sel);
const std::size_t kMaxIndexedObjects = 1u << 20;
const int kMaxGroupDepth = 64;

// What the file says an attribute's or dataset's type is, before the
// format decides whether that is an encoding it allows.
struct AttrType {
  H5T_class_t klass = H5T_NO_CLASS;
  std::size_t size = 0;
  bool variable_length = false;
  H5T_cset_t cset = H5T_CSET_ASCII;
  H5T_str_t strpad = H5T_STR_NULLPAD;
  bool is_signed = true;
  H5T_order_t order = H5T_ORDER_LE;
  bool scalar_dataspace = true;
  std::size_t points = 1;
};

struct RawAttr {
  std::string name;
  AttrType type;
  AttrValue value;
  std::string raw_bytes;   // a string attribute's stored bytes
  bool too_large = false;  // declared more elements than this build reads
};

struct DsetInfo {
  bool is_dataset = false;
  AttrType type;
  std::vector<hsize_t> shape;
  std::vector<hsize_t> maxshape;
  bool chunked = false;
  std::vector<hsize_t> chunk;
  std::vector<std::pair<int, std::vector<unsigned>>> filters;
  bool attr_order_tracked = false;
  bool attr_order_indexed = false;
  bool is_scale = false;
  std::vector<std::vector<std::string>> scales;   // per axis, link names
  bool has_fill_value_set = false;
};

// Positions along one axis as increasing (start, count) runs.
using Runs = std::vector<std::pair<std::int64_t, std::int64_t>>;

// A stored chunk of a dataset, as its chunk index records it.
struct StoredChunk {
  std::uint64_t cell;   // its place in the dataset's grid of chunks, leading axis first
  hsize_t size;         // bytes the index records; 0 once HDF5 has rewritten it
  bool checked;         // known to decode to the whole chunk
};

// The core's own reading of chunked datasets (spec sections 9.6 and
// 11.2), one per open file. HDF5 is never handed a stored chunk this has
// not checked. On first use of a dataset, one pass over its chunk index
// records each stored chunk and its size. A filtered dataset is read here:
// each chunk a read touches is fetched raw and its filters undone, and one
// whose stored or decoded size is not the chunk's is refused (E23), where
// HDF5 would read or write past its buffer; before a write, each stored
// chunk HDF5 is about to rewrite is decoded here first. An unfiltered
// dataset whose stored chunks are all whole is left to HDF5; one that is
// not is read here too, and the chunks not stored whole are refused.
class ChunkStore {
 public:
  // True when HDF5 may read and write the chunked dataset `dset` itself.
  bool stored_whole(hid_t dset, const std::string& path, const DsetInfo& info);
  // Reads `runs` (one list per axis) of the chunked dataset `dset` into
  // `out`, `elements` values of `mem_type` (`mem_size` bytes each),
  // decoding in up to `threads` threads.
  void read(hid_t dset, const std::string& path, const DsetInfo& info, hid_t mem_type,
            std::size_t mem_size, const std::vector<Runs>& runs, void* out,
            std::size_t elements, int threads);
  // Before and after HDF5 writes the block [start, start + count) of the
  // dataset `dset`, whose extent is now `shape`; `describe` gives its
  // dataset_info when this does not yet know it.
  void before_write(hid_t dset, const std::string& path, const std::vector<hsize_t>& shape,
                    const std::function<DsetInfo()>& describe,
                    const std::vector<hsize_t>& start, const std::vector<hsize_t>& count);
  void after_write(const std::string& path, const std::vector<hsize_t>& start,
                   const std::vector<hsize_t>& count);
  // After the extent changes; after a dataset (or a group of them) is
  // created or removed.
  void resized(const std::string& path, const std::vector<hsize_t>& shape);
  void forget(const std::string& path);

 private:
  struct Dataset {
    std::vector<hsize_t> shape, chunk, grid;   // grid: chunks along each axis
    std::size_t item = 0, whole = 0;           // bytes of an element, of a chunk
    bool chunked = true;                       // false: known, and left to HDF5
    bool filtered = false;
    bool all_whole = false;                    // unfiltered, every stored chunk whole
    std::vector<int> filter_ids;
    std::vector<StoredChunk> stored;           // by cell
  };
  Dataset& state(hid_t dset, const std::string& path, const DsetInfo& info);
  static StoredChunk* find(Dataset& d, std::uint64_t cell);
  // Fetches a stored chunk raw into `raw`, its size checked against the
  // chunk's before anything is read.
  static void fetch(hid_t dset, const std::string& path, const Dataset& d, StoredChunk& c,
                    const std::vector<hsize_t>& offset, std::vector<unsigned char>& raw,
                    unsigned* mask);
  // Buffers kept between reads, so a read of one chunk allocates nothing.
  std::vector<unsigned char> take();
  void give(std::vector<unsigned char>&& v);
  std::map<std::string, Dataset> datasets_;
  std::vector<std::vector<unsigned char>> spare_;
};

enum class LinkKind { Missing, Hard, Soft, External, Other };
const char* link_kind_name(LinkKind kind);

struct Member {
  std::string name;
  LinkKind kind = LinkKind::Missing;
  bool is_group = false;
  bool is_dataset = false;
  unsigned links = 0;   // hard links to the object; a group with more is not a tree
};

class File {
 public:
  static File open_read(const std::string& path);
  static File open_write(const std::string& path);
  static File create(const std::string& path);

  hid_t get() const { return id_.get(); }
  void flush();

  // The kind of the last link of `path`, stopping at the first link that
  // is not hard, so nothing below a soft or external link is touched.
  LinkKind link_kind(const std::string& path) const;
  bool exists(const std::string& path) const;
  bool is_group(const std::string& path) const;
  bool is_dataset(const std::string& path) const;
  // Why the dataset at `path` keeps its values outside the file (external
  // storage, a virtual dataset), or "" when it does not; such a dataset is
  // never read (E22).
  std::string stored_outside(const std::string& path) const;
  std::vector<Member> members(const std::string& path) const;

  std::vector<RawAttr> attributes(const std::string& path) const;
  // `scales = false` skips the dimension-scale lookups, for reads.
  DsetInfo dataset_info(const std::string& path, bool scales = true) const;
  // Only the type and the shape (with maxshape): what opening a file needs,
  // without the storage settings dataset_info reads for the validator.
  DsetInfo dataset_shape(const std::string& path) const;
  // The attributes and dataset_shape together, opening the object once.
  std::pair<std::vector<RawAttr>, DsetInfo> inspect(const std::string& path) const;

  // Reads the selection into `out`, converting to `mem`.  `sel` gives
  // one selection per leading axis; axes beyond it are read whole.
  // `out_bytes` must equal the selected element count times the size of
  // `mem`.  A chunked dataset's chunks are decoded in up to `threads`
  // threads.  Strings are read with read_strings.
  void read(const std::string& path, DType mem,
            const std::vector<Selection>& sel, void* out,
            std::size_t out_bytes, int threads = 1) const;
  // The selected element count and per-axis counts, without reading.
  std::vector<std::int64_t> selected_shape(
      const std::string& path, const std::vector<Selection>& sel) const;
  std::vector<double> read_f64(const std::string& path) const;
  std::vector<std::int64_t> read_i64(const std::string& path) const;
  // A whole one-dimensional fixed-length string dataset, NULs stripped;
  // more entries or bytes than the caps is E23, before any allocation.
  std::vector<std::string> read_strings(const std::string& path,
                                        std::size_t max_entries = kMaxDatasetElements,
                                        std::size_t max_bytes = kMaxDatasetBytes) const;

  // --- writing -------------------------------------------------------
  void make_group(const std::string& path);
  void write_attr(const std::string& path, const std::string& name,
                  const AttrValue& value);
  void replace_attr(const std::string& path, const std::string& name,
                    const AttrValue& value);
  void write_raw_string_attr(const std::string& path, const std::string& name,
                             const std::string& bytes);
  // `maxshape` empty means fixed; `chunk` empty means contiguous;
  // `string_size` is used when `dtype` is String.
  void create_dataset(const std::string& path, DType dtype,
                      std::size_t string_size,
                      const std::vector<hsize_t>& shape,
                      const std::vector<hsize_t>& maxshape,
                      const std::vector<hsize_t>& chunk,
                      const FilterPipeline& filters,
                      bool scale_properties = false);
  // Writes a block: `start` and `count` per axis (all axes given).
  void write(const std::string& path, DType mem,
             const std::vector<hsize_t>& start,
             const std::vector<hsize_t>& count, const void* data);
  // Writes strings into a one-dimensional string dataset from `start`.
  void write_strings(const std::string& path, hsize_t start,
                     const std::vector<std::string>& values);
  void set_extent(const std::string& path, const std::vector<hsize_t>& shape);

  // A dimension scale written as netCDF-C writes a dimension with no
  // coordinate variable (spec section 9.4).
  void make_scale(const std::string& path, hsize_t length, bool unlimited);
  // Grows such a scale and rewrites its NAME, which spells the length.
  void set_scale_length(const std::string& path, hsize_t length);
  // Marks an existing dataset as a coordinate variable: a dimension scale
  // whose NAME is its own name (the `row` ids).
  void mark_coordinate_scale(const std::string& path, const std::string& name);
  void attach_scale(const std::string& dataset, const std::string& scale,
                    unsigned axis);
  // Before a dataset with an attached scale is deleted, so the scale's
  // REFERENCE_LIST does not keep a reference to it.
  void detach_scale(const std::string& dataset, const std::string& scale,
                    unsigned axis);

  std::string dataset_link_name(hid_t object) const;
  void remove_link(const std::string& path);

 private:
  void build_object_index() const;
  // dataset_info of `path`, leaving the dataset open in `dset` (invalid
  // when `path` is not a dataset), so a read or write opens it once.
  DsetInfo opened(const std::string& path, Id* dset, bool scales) const;
  DsetInfo described(hid_t dset, bool scales) const;
  // Opens the dataset at `path`, refusing one whose values are stored
  // outside the file (E22) before its extent or values are touched.
  Id open_dataset(const std::string& path) const;
  // After a dataset, or a group of them, is created or removed.
  void forget(const std::string& path);
  // Reads a selection of many scattered blocks as its bounding box and
  // gathers; false (nothing read) when the plain path should read it.
  bool read_gathered(const std::string& path, const std::vector<hsize_t>& shape, DType mem,
                     const std::vector<Selection>& sel, void* out, std::size_t out_bytes) const;
  std::string dataset_path(hid_t object) const;

  Id id_;
  mutable ChunkStore chunks_;
  mutable std::set<std::string> inside_;   // datasets checked to hold their own values
  mutable std::map<std::string, std::string> object_paths_;
  mutable bool object_index_built_ = false;
};

std::string scale_name_attribute(hsize_t length);
FilterPipeline pipeline_of(const DsetInfo& info);
Id string_type(std::size_t size);
hid_t memory_type(DType t);
bool is_spec_string(const AttrType& t);
bool is_spec_int64(const AttrType& t);
bool is_spec_int32(const AttrType& t);
bool is_spec_float64(const AttrType& t);
// The format dtype of a stored type; false when the format allows it
// nowhere (big-endian, unsigned other than uint8, variable-length ...).
bool dtype_of(const AttrType& t, DType* out);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_H5_HPP
