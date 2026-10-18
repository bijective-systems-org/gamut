// The block (chunk) rule of spec section 11.4.
#ifndef MESTRA_CORE_CHUNK_HPP
#define MESTRA_CORE_CHUNK_HPP

#include <hdf5.h>

#include <cstddef>
#include <vector>

#include "types.hpp"

namespace mestra {
namespace internal {

const std::size_t kChunkBytes = 262144;   // T
// The cap on entries along a growing leading axis (spec section 11.4):
// a run table appended one row at a time, reopened each time, rewrites
// at most one small chunk per column per session.
const hsize_t kMaxLeadingEntries = 512;

// A dataset whose leading axis grows: the chunk for an entry of
// `trailing` extents.  When one entry of b bytes fits in T, the chunk
// holds min(512, max(1, floor(T / b))) entries with the trailing axes
// whole; otherwise one entry, the first trailing axis in blocks of
// m = min(n, max(1, floor(T / (size x the remaining extents)))), the rest
// whole.  `item` is the element size in bytes.
std::vector<hsize_t> leading_chunk(std::size_t item,
                                   const std::vector<hsize_t>& trailing);

// A dataset stored end to end (changing-mesh values, category tables):
// max(1, floor(T / b)) entries, b the bytes of one entry.
std::vector<hsize_t> end_to_end_chunk(std::size_t item,
                                      const std::vector<hsize_t>& trailing);

// True when `chunk` holds more than the default along any axis, which
// is W6; smaller chunks are what appends leave and draw nothing.
bool chunk_larger_than_default(const std::vector<hsize_t>& chunk,
                               const std::vector<hsize_t>& dflt);

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_CHUNK_HPP
