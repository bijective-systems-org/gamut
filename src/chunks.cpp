#include <zlib.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <functional>
#include <mutex>
#include <thread>

#include "h5.hpp"

namespace gamut_core {
namespace internal {

namespace {

void need(bool ok, const std::string& message) {
  if (!ok) throw Error("", message);
}

// The largest chunk this reader decodes. The format's chunks are near
// 256 KiB (spec section 11.4); HDF5's own limit is 4 GiB.
const std::size_t kMaxChunkBytes = std::size_t(1) << 30;
// The most chunks a dataset's grid may number, which keeps cell numbers
// well inside 64 bits; only stored chunks take memory.
const std::uint64_t kMaxChunkGrid = std::uint64_t(1) << 48;
// Stored chunks fetched before they are decoded, which bounds what a read
// holds in raw chunks at once.
const std::size_t kBatchChunks = 256;
const std::size_t kBatchBytes = std::size_t(256) << 20;

// A run of positions along one axis that falls in one chunk: where it
// starts in the chunk, where it goes in the result, how many it is.
struct Segment {
  std::size_t local;
  std::size_t out;
  std::size_t length;
};

// Along one axis: the chunks a selection's runs fall in, each with its
// segments. Runs are increasing, so each chunk appears once.
struct AxisPlan {
  std::vector<hsize_t> chunks;
  std::vector<std::vector<Segment>> segments;
};

AxisPlan plan_axis(const Runs& runs, hsize_t chunk) {
  AxisPlan p;
  std::size_t out = 0;
  for (const auto& r : runs) {
    hsize_t at = static_cast<hsize_t>(r.first);
    const hsize_t end = at + static_cast<hsize_t>(r.second);
    while (at < end) {
      const hsize_t g = at / chunk;
      const hsize_t stop = std::min(end, (g + 1) * chunk);
      if (p.chunks.empty() || p.chunks.back() != g) {
        p.chunks.push_back(g);
        p.segments.emplace_back();
      }
      p.segments.back().push_back({static_cast<std::size_t>(at - g * chunk), out,
                                   static_cast<std::size_t>(stop - at)});
      out += static_cast<std::size_t>(stop - at);
      at = stop;
    }
  }
  return p;
}

// Copies the selected part of one decoded chunk (`dims`, `item` bytes an
// element) into `out`, whose axes advance by `out_stride` elements: an
// odometer over the segments of every axis but the last, then each
// segment of the last axis as one copy.
void place(const unsigned char* chunk, const std::vector<hsize_t>& dims, std::size_t item,
           const std::vector<const std::vector<Segment>*>& segs,
           const std::vector<std::size_t>& out_stride, unsigned char* out) {
  const std::size_t rank = dims.size();
  std::vector<std::size_t> chunk_stride(rank, 1);
  for (std::size_t a = rank - 1; a > 0; --a) {
    chunk_stride[a - 1] = chunk_stride[a] * static_cast<std::size_t>(dims[a]);
  }
  std::vector<std::size_t> seg(rank, 0), pos(rank, 0);
  while (true) {
    std::size_t local = 0, at = 0;
    for (std::size_t a = 0; a + 1 < rank; ++a) {
      const Segment& s = (*segs[a])[seg[a]];
      local += (s.local + pos[a]) * chunk_stride[a];
      at += (s.out + pos[a]) * out_stride[a];
    }
    for (const Segment& s : *segs[rank - 1]) {
      std::memcpy(out + (at + s.out) * item, chunk + (local + s.local) * item, s.length * item);
    }
    std::size_t a = rank - 1;
    bool done = true;
    while (a > 0) {
      --a;
      if (++pos[a] < (*segs[a])[seg[a]].length) {
        done = false;
        break;
      }
      pos[a] = 0;
      if (++seg[a] < segs[a]->size()) {
        done = false;
        break;
      }
      seg[a] = 0;
    }
    if (done) break;
  }
}

// HDF5's shuffle filter, undone: byte j of element i was stored at
// j * n + i; trailing bytes that did not fill an element were left as is.
void unshuffle(const unsigned char* in, unsigned char* out, std::size_t bytes,
               std::size_t item) {
  const std::size_t n = bytes / item;
  for (std::size_t j = 0; j < item; ++j) {
    const unsigned char* src = in + j * n;
    for (std::size_t i = 0; i < n; ++i) out[i * item + j] = src[i];
  }
  const std::size_t done = n * item;
  if (done < bytes) std::memcpy(out + done, in + done, bytes - done);
}

// A dataset's filters in the order HDF5 applied them when writing. Only
// gzip and shuffle are read (spec section 11.2); shuffle must move
// elements of the stored size, which is what HDF5 records for it.
std::vector<int> filters_of(const DsetInfo& info, const std::string& path) {
  if (info.filters.size() > 32) {
    throw Error("E20", "\"" + path + "\" has more filters than HDF5 records", path);
  }
  std::vector<int> ids;
  for (const auto& flt : info.filters) {
    if (flt.first == H5Z_FILTER_SHUFFLE) {
      if (flt.second.empty() || flt.second[0] != info.type.size) {
        throw Error("E20", "\"" + path + "\" shuffles elements of another size than it holds",
                    path);
      }
    } else if (flt.first != H5Z_FILTER_DEFLATE) {
      throw Error("E20", "\"" + path + "\" uses filter " + std::to_string(flt.first) +
                             "; only gzip and shuffle are read (spec section 11.2)",
                  path);
    }
    ids.push_back(flt.first);
  }
  return ids;
}

std::string size_mismatch(std::size_t stored, std::size_t whole) {
  return "is stored in " + std::to_string(stored) + " bytes and holds " + std::to_string(whole);
}

// Undoes the filters on one stored chunk, last applied first, skipping
// those `mask` marks as skipped when it was written, alternating between
// the buffers `a` and `b`. The chunk's bytes, or null with `why` set when
// it does not decode to exactly `whole` bytes.
const unsigned char* decode(const std::vector<int>& filters, unsigned mask, std::size_t item,
                            std::size_t whole, const std::vector<unsigned char>& raw,
                            std::vector<unsigned char>& a, std::vector<unsigned char>& b,
                            std::string* why) {
  const unsigned char* at = raw.data();
  std::size_t size = raw.size();
  for (std::size_t i = filters.size(); i > 0; --i) {
    if (mask & (1u << (i - 1))) continue;
    std::vector<unsigned char>& to = at == a.data() ? b : a;
    if (filters[i - 1] == H5Z_FILTER_DEFLATE) {
      // Gzip gives back the whole chunk unless an earlier gzip, not skipped,
      // compressed it first; that one's output is at most zlib's bound.
      bool earlier = false;
      for (std::size_t j = 0; j + 1 < i; ++j) {
        earlier = earlier || (filters[j] == H5Z_FILTER_DEFLATE && !(mask & (1u << j)));
      }
      const std::size_t cap =
          earlier ? static_cast<std::size_t>(compressBound(static_cast<uLong>(whole))) : whole;
      to.resize(cap);
      uLongf got = static_cast<uLongf>(cap);
      if (uncompress(to.data(), &got, at, static_cast<uLong>(size)) != Z_OK ||
          (!earlier && got != whole)) {
        *why = "does not inflate to its " + std::to_string(whole) + " bytes";
        return nullptr;
      }
      size = static_cast<std::size_t>(got);
    } else {
      // Shuffle keeps whatever size it is given, as HDF5's does.
      to.resize(size);
      unshuffle(at, to.data(), size, item);
    }
    at = to.data();
  }
  if (size != whole) {
    *why = size_mismatch(size, whole);
    return nullptr;
  }
  return at;
}

// The chunk index pass: each stored chunk inside the extent, with the size
// the index records for it.
struct Scan {
  const std::vector<hsize_t>* chunk;
  const std::vector<hsize_t>* grid;
  std::vector<StoredChunk>* stored;
  std::size_t whole;
  bool filtered;
  std::string why;
};

int scan_chunk(const hsize_t* offset, unsigned /*mask*/, haddr_t /*address*/, hsize_t size,
               void* data) {
  Scan& s = *static_cast<Scan*>(data);
  std::uint64_t cell = 0;
  for (std::size_t a = 0; a < s.chunk->size(); ++a) {
    const hsize_t c = (*s.chunk)[a];
    if (offset[a] % c != 0) {
      s.why = "has a chunk that does not start on a chunk boundary";
      return H5_ITER_STOP;
    }
    const hsize_t g = offset[a] / c;
    if (g >= (*s.grid)[a]) return H5_ITER_CONT;   // beyond the extent, never read
    cell = cell * (*s.grid)[a] + g;
  }
  s.stored->push_back({cell, size, !s.filtered && size == s.whole});
  return H5_ITER_CONT;
}

// The chunks of the block [start, start + count) as a range per axis;
// false when the block is empty or lies beyond the grid.
bool block_chunks(const std::vector<hsize_t>& chunk, const std::vector<hsize_t>& grid,
                  const std::vector<hsize_t>& start, const std::vector<hsize_t>& count,
                  std::vector<hsize_t>* first, std::vector<hsize_t>* last) {
  const std::size_t rank = chunk.size();
  first->resize(rank);
  last->resize(rank);
  for (std::size_t a = 0; a < rank; ++a) {
    if (count[a] == 0) return false;
    (*first)[a] = start[a] / chunk[a];
    (*last)[a] = (start[a] + count[a] - 1) / chunk[a];
    if ((*last)[a] >= grid[a]) return false;
  }
  return true;
}

// Visits every chunk of the ranges [first, last] per axis, by its cell.
template <class F>
void each_chunk(const std::vector<hsize_t>& grid, const std::vector<hsize_t>& first,
                const std::vector<hsize_t>& last, F visit) {
  const std::size_t rank = grid.size();
  std::vector<hsize_t> g = first;
  while (true) {
    std::uint64_t cell = 0;
    for (std::size_t a = 0; a < rank; ++a) cell = cell * grid[a] + g[a];
    visit(cell, g);
    std::size_t a = rank;
    bool done = true;
    while (a > 0) {
      --a;
      if (++g[a] <= last[a]) {
        done = false;
        break;
      }
      g[a] = first[a];
    }
    if (done) break;
  }
}

}  // namespace

ChunkStore::Dataset& ChunkStore::state(hid_t dset, const std::string& path,
                                       const DsetInfo& info) {
  const auto known = datasets_.find(path);
  if (known != datasets_.end() && known->second.chunked && known->second.shape == info.shape &&
      known->second.chunk == info.chunk) {
    return known->second;
  }
  const std::size_t rank = info.shape.size();
  need(rank > 0 && info.chunk.size() == rank, "\"" + path + "\" is not chunked");
  Dataset d;
  d.shape = info.shape;
  d.chunk = info.chunk;
  d.item = info.type.size;
  d.whole = d.item;
  std::uint64_t cells = 1;
  for (std::size_t a = 0; a < rank; ++a) {
    const hsize_t c = info.chunk[a];
    if (c == 0 || d.whole == 0 || d.whole > kMaxChunkBytes / c) {
      throw Error("E26", "a chunk of \"" + path + "\" is larger than this reader decodes", path);
    }
    d.whole *= static_cast<std::size_t>(c);
    const hsize_t g = info.shape[a] / c + (info.shape[a] % c != 0 ? 1 : 0);
    if (g != 0 && cells > kMaxChunkGrid / g) {
      throw Error("E26", "\"" + path + "\" has more chunks than this reader indexes", path);
    }
    d.grid.push_back(g);
    cells *= g;
  }
  d.filtered = !info.filters.empty();
  d.filter_ids = filters_of(info, path);
  if (cells > 0) {
    Scan scan{&d.chunk, &d.grid, &d.stored, d.whole, d.filtered, ""};
    const herr_t done = H5Dchunk_iter(dset, H5P_DEFAULT, scan_chunk, &scan);
    if (!scan.why.empty()) throw Error("E23", "\"" + path + "\" " + scan.why, path);
    need(done >= 0, "cannot read the chunk index of \"" + path + "\"");
  }
  std::sort(d.stored.begin(), d.stored.end(),
            [](const StoredChunk& x, const StoredChunk& y) { return x.cell < y.cell; });
  for (std::size_t i = 1; i < d.stored.size(); ++i) {
    if (d.stored[i].cell == d.stored[i - 1].cell) {
      throw Error("E23", "\"" + path + "\" lists a chunk twice in its index", path);
    }
  }
  d.all_whole = !d.filtered;
  for (const StoredChunk& c : d.stored) d.all_whole = d.all_whole && c.checked;
  return datasets_[path] = std::move(d);
}

StoredChunk* ChunkStore::find(Dataset& d, std::uint64_t cell) {
  const auto it = std::lower_bound(
      d.stored.begin(), d.stored.end(), cell,
      [](const StoredChunk& c, std::uint64_t at) { return c.cell < at; });
  return it != d.stored.end() && it->cell == cell ? &*it : nullptr;
}

std::vector<unsigned char> ChunkStore::take() {
  if (spare_.empty()) return {};
  std::vector<unsigned char> v = std::move(spare_.back());
  spare_.pop_back();
  v.clear();
  return v;
}

void ChunkStore::give(std::vector<unsigned char>&& v) {
  // A few buffers are kept for the next read; never a large one.
  if (spare_.size() < 16 && v.capacity() <= (std::size_t(64) << 20)) {
    spare_.push_back(std::move(v));
  }
}

bool ChunkStore::stored_whole(hid_t dset, const std::string& path, const DsetInfo& info) {
  const Dataset& d = state(dset, path, info);
  return !d.filtered && d.all_whole;
}

void ChunkStore::fetch(hid_t dset, const std::string& path, const Dataset& d,
                       StoredChunk& c, const std::vector<hsize_t>& offset,
                       std::vector<unsigned char>& raw, unsigned* mask) {
  if (!d.filtered && !c.checked) {
    throw Error("E23", "a chunk of \"" + path + "\" is not stored whole", path);
  }
  hsize_t size = d.filtered ? c.size : d.whole;
  if (size == 0) {
    // Rewritten by HDF5 since the index pass: ask the index again.
    need(H5Dget_chunk_storage_size(dset, offset.data(), &size) >= 0,
         "cannot read the chunk index of \"" + path + "\"");
    c.size = size;
  }
  // Gzip can store a chunk in up to zlib's bound (an incompressible one is
  // stored as is, with gzip marked skipped); shuffle keeps the size.
  bool deflate = false;
  std::size_t bound = d.whole;
  for (const int id : d.filter_ids) {
    if (id != H5Z_FILTER_DEFLATE) continue;
    deflate = true;
    bound = std::max<std::size_t>(bound, compressBound(static_cast<uLong>(bound)));
  }
  if (size == 0 || size > bound || (!deflate && size != d.whole)) {
    throw Error("E23", "a chunk of \"" + path + "\" " +
                           size_mismatch(static_cast<std::size_t>(size), d.whole),
                path);
  }
  raw.resize(static_cast<std::size_t>(size));
  std::uint32_t got = 0;
  need(H5Dread_chunk(dset, H5P_DEFAULT, offset.data(), &got, raw.data()) >= 0,
       "cannot read a chunk of \"" + path + "\"");
  *mask = got;
}

void ChunkStore::read(hid_t dset, const std::string& path, const DsetInfo& info,
                      hid_t mem_type, std::size_t mem_size, const std::vector<Runs>& runs,
                      void* out, std::size_t elements, int threads) {
  Dataset& d = state(dset, path, info);
  const std::vector<int>& filters = d.filter_ids;
  const std::size_t rank = d.shape.size();
  need(runs.size() == rank, "\"" + path + "\": a selection per axis is needed");

  std::vector<AxisPlan> plans;
  std::vector<std::size_t> out_stride(rank, 1), selected(rank, 0);
  for (std::size_t a = 0; a < rank; ++a) {
    plans.push_back(plan_axis(runs[a], d.chunk[a]));
    for (const auto& r : runs[a]) selected[a] += static_cast<std::size_t>(r.second);
    if (plans[a].chunks.empty()) return;
  }
  for (std::size_t a = rank - 1; a > 0; --a) out_stride[a - 1] = out_stride[a] * selected[a];

  // Values are placed as stored and converted at the end, by HDF5's own
  // conversion, so reads give what HDF5 gave.
  Id ftype(H5Dget_type(dset));
  const htri_t same = H5Tequal(ftype.get(), mem_type);
  need(same >= 0, "cannot compare the types of \"" + path + "\"");
  H5T_cdata_t* cdata = nullptr;
  need(same > 0 || H5Tfind(ftype.get(), mem_type, &cdata) != nullptr,
       "\"" + path + "\" cannot be read as the type asked");
  unsigned char* stage = static_cast<unsigned char*>(out);
  std::vector<unsigned char> wide;
  if (same > 0) {
    need(mem_size == d.item, "\"" + path + "\": the buffer's element size is not the stored one");
  } else if (d.item > mem_size) {
    wide.resize(elements * d.item);
    stage = wide.data();
  }

  std::vector<unsigned char> fill;   // a never-written chunk, made when one is met
  auto fill_chunk = [&]() {
    if (!fill.empty()) return;
    std::vector<unsigned char> one(d.item, 0);
    Id dcpl(H5Dget_create_plist(dset));
    if (H5Pget_fill_value(dcpl.get(), ftype.get(), one.data()) < 0) {
      std::fill(one.begin(), one.end(), 0);
    }
    fill.resize(d.whole);
    for (std::size_t i = 0; i < d.whole; i += d.item) {
      std::memcpy(fill.data() + i, one.data(), d.item);
    }
  };

  struct Job {
    std::vector<std::size_t> at;   // position in each axis's plan
    std::vector<unsigned char> raw;
    unsigned mask = 0;
    bool stored = false;
  };
  // One thread reads a chunk at a time through the same buffers; more fetch
  // a batch through HDF5 and decode it together.
  const std::size_t workers = threads < 1 ? 1 : static_cast<std::size_t>(threads);
  const std::size_t limit = workers > 1 ? kBatchChunks : 1;
  std::vector<std::vector<unsigned char>> spare(2 * workers);
  for (auto& v : spare) v = take();
  std::vector<std::size_t> at(rank, 0);
  std::vector<hsize_t> offset(rank);
  bool more = true;
  while (more) {
    // Fetch a batch through HDF5, one call at a time.
    std::vector<Job> batch;
    std::size_t held = 0;
    while (more && batch.size() < limit && held < kBatchBytes) {
      Job job;
      job.at = at;
      std::uint64_t cell = 0;
      for (std::size_t a = 0; a < rank; ++a) {
        const hsize_t g = plans[a].chunks[at[a]];
        cell = cell * d.grid[a] + g;
        offset[a] = g * d.chunk[a];
      }
      StoredChunk* c = find(d, cell);
      job.stored = c != nullptr;
      if (job.stored) {
        job.raw = take();
        fetch(dset, path, d, *c, offset, job.raw, &job.mask);
        held += std::max(job.raw.size(), d.whole);
      } else {
        fill_chunk();
      }
      batch.push_back(std::move(job));
      // The next chunk: an odometer over each axis's chunks.
      std::size_t a = rank;
      more = false;
      while (a > 0) {
        --a;
        if (++at[a] < plans[a].chunks.size()) {
          more = true;
          break;
        }
        at[a] = 0;
      }
    }

    // Decode and place, in threads when asked; HDF5 is not called here.
    const std::size_t running = std::min(workers, batch.size());
    std::atomic<std::size_t> next{0};
    std::atomic<bool> failed{false};
    std::string failure;
    std::mutex failure_lock;
    auto work = [&](std::size_t w) {
      try {
        std::vector<const std::vector<Segment>*> segs(rank);
        while (!failed) {
          const std::size_t k = next.fetch_add(1);
          if (k >= batch.size()) return;
          Job& job = batch[k];
          for (std::size_t a = 0; a < rank; ++a) segs[a] = &plans[a].segments[job.at[a]];
          const unsigned char* data = fill.data();
          if (job.stored) {
            std::string why;
            data = decode(filters, job.mask, d.item, d.whole, job.raw, spare[2 * w],
                          spare[2 * w + 1], &why);
            if (data == nullptr) {
              std::lock_guard<std::mutex> guard(failure_lock);
              if (!failed) failure = "a chunk of \"" + path + "\" " + why;
              failed = true;
              return;
            }
          }
          place(data, d.chunk, d.item, segs, out_stride, stage);
        }
      } catch (const std::exception& e) {
        // An exception must not leave a thread (std::terminate); it is
        // reported after the join.
        std::lock_guard<std::mutex> guard(failure_lock);
        if (!failed) failure = e.what();
        failed = true;
      }
    };
    std::vector<std::thread> pool;
    try {
      for (std::size_t t = 1; t < running; ++t) pool.emplace_back(work, t);
    } catch (...) {
      // Fewer threads than asked: the ones running and this one finish.
    }
    work(0);
    for (auto& th : pool) th.join();
    for (auto& job : batch) {
      if (job.stored) give(std::move(job.raw));
    }
    if (failed) {
      for (auto& v : spare) give(std::move(v));
      throw Error("E23", failure, path);
    }
  }
  for (auto& v : spare) give(std::move(v));

  if (same == 0) {
    need(H5Tconvert(ftype.get(), mem_type, elements, stage, nullptr, H5P_DEFAULT) >= 0,
         "cannot convert the values of \"" + path + "\"");
    if (stage != out) std::memcpy(out, stage, elements * mem_size);
  }
}

void ChunkStore::before_write(hid_t dset, const std::string& path,
                              const std::vector<hsize_t>& shape,
                              const std::function<DsetInfo()>& describe,
                              const std::vector<hsize_t>& start,
                              const std::vector<hsize_t>& count) {
  // A dataset this already knows at this extent needs no description; a
  // writer writes chunk by chunk, so this is most writes.
  const auto known = datasets_.find(path);
  Dataset* known_d = known != datasets_.end() && known->second.shape == shape
                         ? &known->second
                         : nullptr;
  if (known_d == nullptr) {
    const DsetInfo info = describe();
    if (!info.chunked || info.shape.empty()) {
      Dataset plain;
      plain.chunked = false;
      plain.shape = info.shape;
      datasets_[path] = std::move(plain);
      return;
    }
    known_d = &state(dset, path, info);
  }
  Dataset& d = *known_d;
  if (!d.chunked || (!d.filtered && d.all_whole)) return;
  const std::vector<int>& filters = d.filter_ids;
  std::vector<hsize_t> first, last;
  // Only chunks the grid holds can be stored; a block past it has none yet.
  std::vector<hsize_t> clipped = count;
  for (std::size_t a = 0; a < count.size(); ++a) {
    const hsize_t end = std::min<hsize_t>(start[a] + count[a], d.grid[a] * d.chunk[a]);
    clipped[a] = end > start[a] ? end - start[a] : 0;
  }
  if (!block_chunks(d.chunk, d.grid, start, clipped, &first, &last)) return;
  std::vector<hsize_t> offset(d.chunk.size());
  std::vector<unsigned char> raw = take(), one = take(), two = take();
  each_chunk(d.grid, first, last, [&](std::uint64_t cell, const std::vector<hsize_t>& g) {
    // HDF5 reads a stored chunk to rewrite part of it: it is fetched and
    // decoded here first, once per open file.
    StoredChunk* c = find(d, cell);
    if (c == nullptr || c->checked) return;
    for (std::size_t a = 0; a < g.size(); ++a) offset[a] = g[a] * d.chunk[a];
    unsigned mask = 0;
    fetch(dset, path, d, *c, offset, raw, &mask);
    std::string why;
    if (decode(filters, mask, d.item, d.whole, raw, one, two, &why) == nullptr) {
      throw Error("E23", "a chunk of \"" + path + "\" " + why, path);
    }
    c->checked = true;
  });
  give(std::move(raw));
  give(std::move(one));
  give(std::move(two));
}

void ChunkStore::after_write(const std::string& path, const std::vector<hsize_t>& start,
                             const std::vector<hsize_t>& count) {
  const auto known = datasets_.find(path);
  if (known == datasets_.end()) return;
  Dataset& d = known->second;
  if (!d.chunked) return;
  std::vector<hsize_t> first, last;
  if (!block_chunks(d.chunk, d.grid, start, count, &first, &last)) {
    // Written past the extent this knows: learn it again when next used.
    datasets_.erase(known);
    return;
  }
  // Every chunk the block touches is now stored as HDF5 wrote it, whole;
  // a filtered one's size is asked for when next read.
  const hsize_t size = d.filtered ? 0 : d.whole;
  each_chunk(d.grid, first, last, [&](std::uint64_t cell, const std::vector<hsize_t>&) {
    const auto it = std::lower_bound(
        d.stored.begin(), d.stored.end(), cell,
        [](const StoredChunk& c, std::uint64_t at) { return c.cell < at; });
    if (it != d.stored.end() && it->cell == cell) {
      it->size = size;
      it->checked = true;
    } else {
      d.stored.insert(it, {cell, size, true});
    }
  });
}

void ChunkStore::resized(const std::string& path, const std::vector<hsize_t>& shape) {
  const auto known = datasets_.find(path);
  if (known == datasets_.end()) return;
  Dataset& d = known->second;
  if (!d.chunked) {
    d.shape = shape;
    return;
  }
  const std::size_t rank = d.shape.size();
  bool leading_only = shape.size() == rank;
  for (std::size_t a = 1; leading_only && a < rank; ++a) {
    leading_only = shape[a] == d.shape[a];
  }
  if (!leading_only) {
    datasets_.erase(known);
    return;
  }
  std::uint64_t slab = 1;
  for (std::size_t a = 1; a < rank; ++a) slab *= d.grid[a];
  const hsize_t g0 = shape[0] / d.chunk[0] + (shape[0] % d.chunk[0] != 0 ? 1 : 0);
  if (slab != 0 && g0 > kMaxChunkGrid / slab) {
    datasets_.erase(known);
    return;
  }
  // Cells number the leading axis first, so growing that axis keeps every
  // chunk's cell, and shrinking it drops the chunks past the end.
  d.shape = shape;
  d.grid[0] = g0;
  const std::uint64_t cells = g0 * slab;
  d.stored.erase(std::lower_bound(d.stored.begin(), d.stored.end(), cells,
                                  [](const StoredChunk& c, std::uint64_t at) {
                                    return c.cell < at;
                                  }),
                 d.stored.end());
}

void ChunkStore::forget(const std::string& path) {
  const std::string below = path == "/" ? path : path + "/";
  for (auto it = datasets_.begin(); it != datasets_.end();) {
    if (it->first == path || it->first.compare(0, below.size(), below) == 0) {
      it = datasets_.erase(it);
    } else {
      ++it;
    }
  }
}

}  // namespace internal
}  // namespace gamut_core
