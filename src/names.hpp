// Internal helpers for names, strings and formatting, and the tables of
// the specification that the writer, the reader and the validator share.
#ifndef GAMUT_CORE_NAMES_HPP
#define GAMUT_CORE_NAMES_HPP

#include <cstdint>
#include <set>
#include <string>
#include <vector>

namespace gamut_core {
namespace internal {

// Spec section 9.3: not empty, no "/" or NUL, no leading or trailing
// space, built from letters, digits, "_", "-", "." and "+", first
// character a letter, digit or underscore.
bool legal_netcdf_name(const std::string& name);

// What a legal name is, for messages that refuse one.
const char kLegalName[] =
    "a name is letters, digits and _ - . +, starting with a letter, a digit or _ "
    "(spec section 9.3)";

// The reserved prefix `gamut_`.
bool reserved_name(const std::string& name);

// Section 9.3: the names the root keeps for itself, and `category_...`.
bool reserved_root_name(const std::string& name);

// Section 3: the roles of parameters and of labels.
extern const std::set<std::string> kParameterRoles;
extern const std::set<std::string> kLabelRoles;

// Section 3.9: an array's role (design or condition) and the word its
// dataset carries, the role followed by "_array" (section 10.1).
extern const std::set<std::string> kArrayRoles;
std::string array_role_word(const std::string& role);
// The role an array's word gives: "design_array" -> "design"; empty for a
// word that is not an array's.
std::string array_role_of(const std::string& word);
// The dimension scale of an array's values: "/gamut_<name>_d1".
std::string array_scale(const std::string& name);

// HDF5 and netCDF attributes that carry the layout, not the study.
extern const std::set<std::string> kMachinery;

// Section 15: the nodes a cell of a type has; -3 is three or more, 0 an
// unknown type.
int nodes_of_type(int code);

// Valid UTF-8 with no NUL anywhere.
bool valid_utf8(const std::string& s);

// Strips trailing NUL bytes, as a reader of a fixed-length string must.
std::string strip_nul(const std::string& s);

// True when `s` holds a NUL byte anywhere but in trailing padding.
bool embedded_nul(const std::string& s);

// An ISO 8601 UTC timestamp, which W8 asks `created` to be.
bool iso8601_utc(const std::string& s);

// "%.17e", and "nan", "inf", "-inf".
std::string format_f64(double v);
std::string format_i64(std::int64_t v);

std::string basename(const std::string& path);

// Splits a space-separated attribute value (spec section 9.2).
std::vector<std::string> split_spaces(const std::string& s);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_NAMES_HPP
