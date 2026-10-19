// Internal helpers for names, strings and formatting.
#ifndef GAMUT_CORE_NAMES_HPP
#define GAMUT_CORE_NAMES_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace gamut_core {
namespace internal {

// Spec section 9.3: not empty, no "/" or NUL, no leading or trailing
// space, built from letters, digits, "_", "-", "." and "+", first
// character a letter, digit or underscore.
bool legal_netcdf_name(const std::string& name);

// The reserved prefix `gamut_`.
bool reserved_name(const std::string& name);

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
