// Evaluation (spec section 7.4), driven by the binding: the core makes a
// data file with a model file's declarations; the binding calls its models
// and adds the rows.  No callbacks cross the C interface.
#ifndef GAMUT_CORE_EVALUATE_HPP
#define GAMUT_CORE_EVALUATE_HPP

#include <memory>
#include <string>

#include "reader.hpp"
#include "writer.hpp"

namespace gamut {
namespace internal {

// A new data file at `out_path` declaring what the model file declares:
// parameters (with their bounds), labels (with the model file's tables, so
// codes agree), results (stored, at the precision of the model file's
// datasets), constants, and the mesh (its stored coordinates when fixed;
// cells only when a model or the caller gives coordinates per run).  The
// file records the model file's id in `evaluated_from`.
std::unique_ptr<Writer> begin_evaluation(const Reader& model, const std::string& out_path);

}  // namespace internal
}  // namespace gamut

#endif  // GAMUT_CORE_EVALUATE_HPP
