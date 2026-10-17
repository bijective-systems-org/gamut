// The units grammar of spec section 13: whether a string parses,
// whatever names it uses.  A grammar, deliberately not a units database.
#ifndef MESTRA_CORE_UNITS_HPP
#define MESTRA_CORE_UNITS_HPP

#include <string>

namespace mestra {

bool units_parse(const std::string& units);

}  // namespace mestra

#endif  // MESTRA_CORE_UNITS_HPP
