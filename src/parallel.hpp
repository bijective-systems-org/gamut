// Parallel reads: raw chunks are fetched through HDF5 one at a time (the
// library serialises its calls) and decompressed in worker threads outside
// it.  Possible because the format allows only gzip and shuffle (spec
// section 11.2), which this code undoes itself with zlib.
#ifndef GAMUT_CORE_PARALLEL_HPP
#define GAMUT_CORE_PARALLEL_HPP

#include <cstddef>
#include <string>
#include <vector>

#include "h5.hpp"
#include "types.hpp"

namespace gamut {
namespace internal {

// Reads `sel` (ranges or everything per axis) of a chunked dataset into
// `out` as `mem`, decompressing with `threads` workers.  Returns false,
// having read nothing, when the dataset or selection is not one this path
// handles (a filter it does not know, an index selection, strings); the
// caller then reads serially.
bool read_parallel(const File& f, const std::string& path, DType mem,
                   const std::vector<Selection>& sel, void* out,
                   std::size_t out_bytes, int threads);

}  // namespace internal
}  // namespace gamut

#endif  // GAMUT_CORE_PARALLEL_HPP
