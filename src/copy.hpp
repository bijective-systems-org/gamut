// Copies between files: every row goes through the
// writer, so a copy meets every rule a writer checks.
#ifndef GAMUT_CORE_COPY_HPP
#define GAMUT_CORE_COPY_HPP

#include <cstdint>
#include <optional>
#include <string>

#include "types.hpp"

namespace gamut_core {
namespace internal {

// The rows of `src` added to `dst` in place, with new ids continuing
// dst's; tables merge by name. Both need the same declarations (bounds may
// differ), the same mesh and, for members in both, the same geometry.
// Everything is checked before the first row is written. Returns the rows
// added.  A marked source whose marking is not dst's is refused (E27)
// unless `marking` states the result's, which dst then carries (spec
// section 11.5).
std::int64_t append_file(const std::string& dst, const std::string& src,
                         const std::optional<std::string>& marking = std::nullopt);

// Refuses (E27) rows marked `rows_marking` (empty: none) for a file marked
// `file_marking`: the rule of append, for rows from elsewhere.
void check_marking(const std::string& file_marking, const std::string& rows_marking);

// The selected rows of `src` as a new file `dst`: ids kept, every table
// whole, a changing mesh's instances reduced to those the rows use.
void extract_file(const std::string& src, const std::string& dst, const Selection& rows);

// `src` rewritten as `dst` with the default layout (chunks, compression);
// its identity (file_id, created) is kept.
void write_copy_file(const std::string& src, const std::string& dst);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_COPY_HPP
