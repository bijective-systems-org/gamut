// The units grammar of spec section 13: whether a string parses,
// whatever names it uses.  A grammar, deliberately not a units database.
#ifndef GAMUT_CORE_UNITS_HPP
#define GAMUT_CORE_UNITS_HPP

#include <string>

namespace gamut {

bool units_parse(const std::string& units);

}  // namespace gamut

#endif  // GAMUT_CORE_UNITS_HPP
