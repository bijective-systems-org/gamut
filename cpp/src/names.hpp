// Internal helpers for names, strings and formatting.  Not installed.
#ifndef MESTRA_SRC_NAMES_HPP
#define MESTRA_SRC_NAMES_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace mestra {
namespace internal {

// SPEC.md section 18: a legal netCDF-4 name is not empty, has no "/"
// and no NUL, does not begin or end with a space, and is built from
// letters, digits, underscore, hyphen, "." and "+".
bool legal_netcdf_name(const std::string& name);

// The reserved prefix of section 18, which a producer-chosen name must
// not begin with.
bool reserved_name(const std::string& name);

// What a reader adds when it meets a callable type nobody registered
// (section 10): how to make the type evaluable.  The reader itself
// never loads anything to find one.
inline constexpr char kRegisterHint[] =
    "To evaluate it, link the library that provides the type and run its "
    "registration, or register a factory with "
    "mestra::CallableRegistry::register_type (the file's writer attribute "
    "names the tool that wrote it)";

// Valid UTF-8, and no NUL anywhere.
bool valid_utf8(const std::string& s);

// Strips trailing NUL bytes, as a reader of a fixed-length string must
// (section 18).
std::string strip_nul(const std::string& s);

// True when `s` holds a NUL byte anywhere but in its trailing padding.
bool embedded_nul(const std::string& s);

// An ISO 8601 UTC timestamp, which is what W14 asks `created` to be.
bool iso8601_utc(const std::string& s);

// The C format "%.17e", which section 30 uses for every float, and the
// three non-finite spellings "nan", "inf" and "-inf".
std::string format_f64(double v);

// The plain decimal form, used for an integer slot's probe value.
std::string format_i64(std::int64_t v);

// Splits a path on "/" and returns the last component.
std::string basename(const std::string& path);

// "group:<k>" -> "<k>"; empty when `varies` does not name a group.
std::string group_of_varies(const std::string& varies);

// "callable:<id>" -> "<id>"; empty when `source` is not a callable.
std::string callable_of_source(const std::string& source);

// A units string raised to a power, and two of them multiplied
// together: what an integration weight and an integral are measured
// in.  The result is in the grammar the W10 parser accepts, so a
// simple identifier gains an exponent ("m" cubed is "m3") and
// anything else is bracketed first ("(m s-1)2"), and "1" stays "1".
std::string units_power(const std::string& units, int power);
std::string units_product(const std::string& a, const std::string& b);

// Splits a space-separated attribute value, which is how section 18
// spells a list of names.
std::vector<std::string> split_spaces(const std::string& s);

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_SRC_NAMES_HPP
