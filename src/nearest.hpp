// The built-in model `nearest` (spec section 7.5): for each input row, the
// outputs of the closest stored point.  Done once, here, so every language
// gets bit-identical answers.
#ifndef GAMUT_CORE_NEAREST_HPP
#define GAMUT_CORE_NEAREST_HPP

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "value.hpp"

namespace gamut_core {
namespace internal {

struct Nearest {
  std::vector<std::string> columns;
  std::vector<double> lower, upper;
  std::int64_t points = 0;
  std::vector<double> x;                    // points x columns, C order
  std::map<std::string, Value> outputs;     // float64 arrays, first axis points
};

// Reads and checks a nearest model's numbers (E17 for its structure, E18
// for what the codec cannot hold).
Nearest nearest_from(const Dict& numbers);

// The numbers of a nearest model, ready to store.
Dict nearest_numbers(const Nearest& m);

// The index of the nearest point for each of `rows` query rows, -1 where a
// used input is not finite.  `inputs` maps each column to `rows` values.
std::vector<std::int64_t> nearest_indices(const Nearest& m,
                                          const std::map<std::string, const double*>& inputs,
                                          std::int64_t rows);

// The values one output gives for those indices: rows x the output's
// per-point size, NaN for index -1.
std::vector<double> nearest_values(const Nearest& m, const std::string& output,
                                   const std::vector<std::int64_t>& index);

// Elements per row of an output.
std::int64_t nearest_output_size(const Nearest& m, const std::string& output);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_NEAREST_HPP
