// The validator of spec section 16: every rule it can decide, from the file
// alone, reported with a concept path and a sentence saying what to do.
#ifndef GAMUT_CORE_VALIDATE_HPP
#define GAMUT_CORE_VALIDATE_HPP

#include <string>
#include <vector>

namespace gamut_core {
namespace internal {

struct Finding {
  std::string rule;       // "E7", "W2"
  std::string severity;   // "error" | "warning"
  std::string path;       // concept path: "mach", "node_fields/p", "mesh", "" for the file
  std::string message;
};

struct Report {
  std::vector<Finding> findings;
  bool ok() const;
  std::size_t errors() const;
  std::size_t warnings() const;
};

// Validates the file at `path`.  Never throws for a property of the file:
// a file that cannot be opened at all is one E1 finding.
Report validate_file(const std::string& path);

// The most elements the validator reads to decide a rule that needs values;
// a dataset above it is left unchecked for that rule, which is reported
// once per object as W11.
const std::size_t kMaxCheckElements = std::size_t(1) << 26;

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_VALIDATE_HPP
