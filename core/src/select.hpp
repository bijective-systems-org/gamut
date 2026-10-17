// The `where` selector of interface section 4: rows whose parameters,
// scalars and labels satisfy an expression.
#ifndef MESTRA_CORE_SELECT_HPP
#define MESTRA_CORE_SELECT_HPP

#include <cstdint>
#include <string>
#include <vector>

#include "reader.hpp"

namespace mestra {
namespace internal {

// The positions (0-based, increasing) of the rows `where` selects.  A
// malformed expression, an unknown name or a label value not in its table
// raises Error with a message saying where in the expression.
std::vector<std::int64_t> select_rows(const Reader& reader, const std::string& where);

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_SELECT_HPP
