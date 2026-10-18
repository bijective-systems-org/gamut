#include "parallel.hpp"

#include <zlib.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>

namespace gamut {
namespace internal {

namespace {

struct Plan {
  std::vector<hsize_t> shape, chunk, lo, hi;   // selection box [lo, hi)
  std::size_t item = 0;                        // bytes per stored element
  DType file = DType::Float64;
  bool shuffle = false, deflate = false;
  int shuffle_index = -1, deflate_index = -1;  // positions in the pipeline
};

template <class From, class To>
void convert_run(const unsigned char* src, unsigned char* dst, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    From v;
    std::memcpy(&v, src + i * sizeof(From), sizeof(From));
    const To w = static_cast<To>(v);
    std::memcpy(dst + i * sizeof(To), &w, sizeof(To));
  }
}

template <class From>
void convert_to(DType mem, const unsigned char* src, unsigned char* dst, std::size_t n) {
  switch (mem) {
    case DType::Float32: convert_run<From, float>(src, dst, n); break;
    case DType::Float64: convert_run<From, double>(src, dst, n); break;
    case DType::Int32: convert_run<From, std::int32_t>(src, dst, n); break;
    case DType::Int64: convert_run<From, std::int64_t>(src, dst, n); break;
    case DType::UInt8: convert_run<From, std::uint8_t>(src, dst, n); break;
    case DType::Int8: convert_run<From, std::int8_t>(src, dst, n); break;
    case DType::String: break;
  }
}

// Copies n stored elements to n elements of `mem`.
void copy_elements(DType file, DType mem, const unsigned char* src, unsigned char* dst,
                   std::size_t n) {
  if (file == mem) {
    std::memcpy(dst, src, n * dtype_size(file));
    return;
  }
  switch (file) {
    case DType::Float32: convert_to<float>(mem, src, dst, n); break;
    case DType::Float64: convert_to<double>(mem, src, dst, n); break;
    case DType::Int32: convert_to<std::int32_t>(mem, src, dst, n); break;
    case DType::Int64: convert_to<std::int64_t>(mem, src, dst, n); break;
    case DType::UInt8: convert_to<std::uint8_t>(mem, src, dst, n); break;
    case DType::Int8: convert_to<std::int8_t>(mem, src, dst, n); break;
    case DType::String: break;
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

}  // namespace

bool read_parallel(const File& f, const std::string& path, DType mem,
                   const std::vector<Selection>& sel, void* out, std::size_t out_bytes,
                   int threads) {
  if (threads < 2 || mem == DType::String) return false;
  const DsetInfo info = f.dataset_info(path, false);
  if (!info.is_dataset || !info.chunked || info.shape.empty()) return false;
  // A set fill value would show in never-written chunks, which this path
  // fills with zeros; such a dataset reads through HDF5.
  if (info.has_fill_value_set) return false;
  Plan plan;
  if (!dtype_of(info.type, &plan.file) || plan.file == DType::String) return false;
  // Conversions here are plain casts: exact for the same type and defined
  // for float to float.  Others (range checks, integer narrowing) are HDF5's.
  const bool floats = (plan.file == DType::Float32 || plan.file == DType::Float64) &&
                      (mem == DType::Float32 || mem == DType::Float64);
  if (mem != plan.file && !floats) return false;
  plan.item = dtype_size(plan.file);
  for (std::size_t i = 0; i < info.filters.size(); ++i) {
    if (info.filters[i].first == H5Z_FILTER_SHUFFLE) {
      plan.shuffle = true;
      plan.shuffle_index = static_cast<int>(i);
    } else if (info.filters[i].first == H5Z_FILTER_DEFLATE) {
      plan.deflate = true;
      plan.deflate_index = static_cast<int>(i);
    } else {
      return false;
    }
  }
  // Shuffle must run before deflate when writing, so it is undone after.
  if (plan.shuffle && plan.deflate && plan.shuffle_index > plan.deflate_index) return false;
  const std::size_t rank = info.shape.size();
  plan.shape = info.shape;
  plan.chunk = info.chunk;
  plan.lo.assign(rank, 0);
  plan.hi = info.shape;
  for (std::size_t a = 0; a < sel.size(); ++a) {
    if (sel[a].kind == Selection::All) continue;
    // A range, or an index list that is one run of consecutive positions
    // (a single row, say); anything else reads serially.
    const auto runs = sel[a].runs(static_cast<std::int64_t>(info.shape[a]), path);
    if (runs.size() > 1) return false;
    if (runs.empty()) {
      plan.lo[a] = plan.hi[a] = 0;
    } else {
      plan.lo[a] = static_cast<hsize_t>(runs[0].first);
      plan.hi[a] = static_cast<hsize_t>(runs[0].first + runs[0].second);
    }
  }
  {
    std::vector<Selection> boxes;
    for (std::size_t a = 0; a < rank; ++a) {
      boxes.push_back(Selection::range(static_cast<std::int64_t>(plan.lo[a]),
                                       static_cast<std::int64_t>(plan.hi[a])));
    }
    check_chunks_touched(path, info, boxes);
  }
  std::vector<hsize_t> box(rank);
  std::size_t total = 1;
  for (std::size_t a = 0; a < rank; ++a) {
    box[a] = plan.hi[a] - plan.lo[a];
    total *= static_cast<std::size_t>(box[a]);
  }
  if (out_bytes != total * dtype_size(mem)) return false;
  if (total == 0) return true;

  // Every chunk the box touches, in order.
  std::vector<std::vector<hsize_t>> chunks;
  std::vector<hsize_t> first(rank), last(rank), at(rank);
  for (std::size_t a = 0; a < rank; ++a) {
    first[a] = plan.lo[a] / plan.chunk[a];
    last[a] = (plan.hi[a] - 1) / plan.chunk[a];
  }
  at = first;
  while (true) {
    std::vector<hsize_t> origin(rank);
    for (std::size_t a = 0; a < rank; ++a) origin[a] = at[a] * plan.chunk[a];
    chunks.push_back(origin);
    std::size_t a = rank;
    bool done = true;
    while (a > 0) {
      --a;
      if (++at[a] <= last[a]) {
        done = false;
        break;
      }
      at[a] = first[a];
    }
    if (done) break;
  }

  // Every worker holds two chunks; a chunk beyond the format's sizes (spec
  // section 11.4 keeps them near 256 KiB) is left to HDF5.
  const std::size_t max_chunk = std::size_t(64) << 20;
  std::size_t chunk_elems = 1;
  for (const hsize_t c : plan.chunk) {
    if (c == 0 || c > max_chunk || chunk_elems > max_chunk / c) return false;
    chunk_elems *= static_cast<std::size_t>(c);
  }
  if (chunk_elems > max_chunk / plan.item) return false;
  const std::size_t chunk_bytes = chunk_elems * plan.item;
  // The largest a stored chunk can be: deflate's bound, or the plain bytes
  // when the filter was skipped for this chunk.
  const std::size_t max_stored =
      std::max<std::size_t>(chunk_bytes, plan.deflate ? compressBound(static_cast<uLong>(chunk_bytes))
                                                      : chunk_bytes);
  const std::size_t out_item = dtype_size(mem);
  unsigned char* dst = static_cast<unsigned char*>(out);

  Id dset(H5Dopen2(f.get(), path.c_str(), H5P_DEFAULT));
  if (!dset.valid()) return false;

  // Batches bound the memory held in raw chunks.
  const std::size_t batch = 256;
  std::atomic<bool> failed{false};
  std::string failure;
  std::mutex failure_lock;
  for (std::size_t b0 = 0; b0 < chunks.size(); b0 += batch) {
    const std::size_t b1 = std::min(chunks.size(), b0 + batch);
    // Raw bytes through HDF5, one call at a time.
    std::vector<std::vector<unsigned char>> raw(b1 - b0);
    std::vector<std::uint32_t> masks(b1 - b0, 0);
    for (std::size_t k = b0; k < b1; ++k) {
      hsize_t stored = 0;
      if (H5Dget_chunk_storage_size(dset.get(), chunks[k].data(), &stored) < 0) stored = 0;
      if (stored == 0) continue;   // never written: zeros, as HDF5 gives
      if (stored > max_stored) {
        throw Error("E23", "a chunk of \"" + path + "\" is larger than its contents can be",
                    path);
      }
      raw[k - b0].resize(static_cast<std::size_t>(stored));
      std::uint32_t mask = 0;
      if (H5Dread_chunk(dset.get(), H5P_DEFAULT, chunks[k].data(), &mask,
                        raw[k - b0].data()) < 0) {
        throw Error("", "cannot read a chunk of \"" + path + "\"");
      }
      masks[k - b0] = mask;
    }
    // Decompress and place in parallel.
    std::atomic<std::size_t> next{b0};
    auto fail = [&](const std::string& why) {
      std::lock_guard<std::mutex> guard(failure_lock);
      if (!failed) failure = why;
      failed = true;
    };
    auto work = [&]() {
     try {
      std::vector<unsigned char> plain(chunk_bytes), scratch(chunk_bytes);
      while (!failed) {
        const std::size_t k = next.fetch_add(1);
        if (k >= b1) return;
        const std::vector<unsigned char>& in = raw[k - b0];
        const std::uint32_t mask = masks[k - b0];
        const unsigned char* data = nullptr;
        if (in.empty()) {
          std::fill(plain.begin(), plain.end(), 0);
          data = plain.data();
        } else {
          const bool inflated = plan.deflate && !(mask & (1u << plan.deflate_index));
          const bool shuffled = plan.shuffle && !(mask & (1u << plan.shuffle_index));
          const unsigned char* src = in.data();
          if (inflated) {
            uLongf got = static_cast<uLongf>(chunk_bytes);
            if (uncompress(scratch.data(), &got, in.data(), static_cast<uLong>(in.size())) != Z_OK ||
                got != chunk_bytes) {
              fail("a chunk of \"" + path + "\" does not inflate to its size");
              return;
            }
            src = scratch.data();
          } else if (in.size() != chunk_bytes) {
            fail("an uncompressed chunk of \"" + path + "\" has the wrong size");
            return;
          }
          if (shuffled) {
            unshuffle(src, plain.data(), chunk_bytes, plan.item);
            data = plain.data();
          } else {
            data = src;
          }
        }
        // Copy the part of this chunk inside the box, a contiguous run of
        // the last axis at a time.
        const std::vector<hsize_t>& o = chunks[k];
        std::vector<hsize_t> s(rank), e(rank);
        for (std::size_t a = 0; a < rank; ++a) {
          s[a] = std::max(plan.lo[a], o[a]);
          e[a] = std::min(plan.hi[a], o[a] + plan.chunk[a]);
        }
        const std::size_t run = static_cast<std::size_t>(e[rank - 1] - s[rank - 1]);
        std::vector<hsize_t> idx(s.begin(), s.end() - 1);
        while (true) {
          std::size_t ci = 0, oi = 0;
          for (std::size_t a = 0; a + 1 < rank; ++a) {
            ci = ci * plan.chunk[a] + (idx[a] - o[a]);
            oi = oi * box[a] + (idx[a] - plan.lo[a]);
          }
          ci = ci * plan.chunk[rank - 1] + (s[rank - 1] - o[rank - 1]);
          oi = oi * box[rank - 1] + (s[rank - 1] - plan.lo[rank - 1]);
          copy_elements(plan.file, mem, data + ci * plan.item, dst + oi * out_item, run);
          std::size_t a = rank - 1;
          bool done = true;
          while (a > 0) {
            --a;
            if (++idx[a] < e[a]) {
              done = false;
              break;
            }
            idx[a] = s[a];
          }
          if (done || rank == 1) break;
        }
      }
     } catch (const std::exception& e) {
      // An exception must not leave a thread (std::terminate); the caller
      // throws it after the join.
      fail(e.what());
     } catch (...) {
      fail("a worker failed reading \"" + path + "\"");
     }
    };
    const int workers = std::min<int>(threads, static_cast<int>(b1 - b0));
    std::vector<std::thread> pool;
    try {
      for (int t = 1; t < workers; ++t) pool.emplace_back(work);
    } catch (...) {
      // Fewer threads than asked: the ones running and this one finish.
    }
    work();
    for (auto& th : pool) th.join();
    if (failed) throw Error("E23", failure, path);
  }
  return true;
}

}  // namespace internal
}  // namespace gamut
