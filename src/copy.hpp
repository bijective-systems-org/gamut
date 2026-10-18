// Copies between files (interface section 6): every row goes through the
// writer, so a copy meets every rule a writer checks.
#ifndef MESTRA_CORE_COPY_HPP
#define MESTRA_CORE_COPY_HPP

#include <cstdint>
#include <string>

#include "types.hpp"

namespace mestra {
namespace internal {

// The rows of `src` added to `dst` in place, with new ids continuing
// dst's; tables merge by name. Both need the same declarations (bounds may
// differ), the same mesh and, for members in both, the same geometry.
// Everything is checked before the first row is written. Returns the rows
// added.
std::int64_t append_file(const std::string& dst, const std::string& src);

// The selected rows of `src` as a new file `dst`: ids kept, every table
// whole, a changing mesh's instances reduced to those the rows use.
void extract_file(const std::string& src, const std::string& dst, const Selection& rows);

// `src` rewritten as `dst` with the default layout (chunks, compression);
// its identity (file_id, created) is kept.
void write_copy_file(const std::string& src, const std::string& dst);

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_COPY_HPP
