// Evaluation (spec section 7.4), driven by the binding: the core checks the
// inputs, says which models the binding must run and what each is asked
// for, runs the built-in nearest model itself, takes the answers and writes
// the data file.  No callbacks cross the C interface.
#ifndef GAMUT_CORE_EVALUATE_HPP
#define GAMUT_CORE_EVALUATE_HPP

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "reader.hpp"
#include "writer.hpp"

namespace gamut_core {
namespace internal {

// A new data file at `out_path` declaring what the model file declares:
// parameters (with their bounds), labels (with the model file's tables, so
// codes agree), results (stored, at the precision of the model file's
// datasets), constants, and the mesh (its stored coordinates when fixed;
// cells only when a model or the caller gives coordinates per run).  The
// file records the model file's id in `evaluated_from` and carries its
// `portion_marking` when it has one.  per_run declares a fixed mesh's
// coordinates per run, for coordinates the caller gives (spec section 7.4).
std::unique_ptr<Writer> begin_evaluation(const Reader& model, const std::string& out_path,
                                         bool per_run = false);

// What a model is asked for: an output's values, its std, a quantile (key:
// q) or a derivative (key: what it is taken with respect to).
struct Request {
  std::string output, kind, key;
  bool operator==(const Request& o) const {
    return output == o.output && kind == o.kind && key == o.key;
  }
};

// One evaluation of a model file on `rows` rows of inputs, written to
// `out_path`, which is declared at once, so a model file the data file
// cannot declare is refused before any model runs.  The model file must
// stay open while it lives; ended without finish, it removes the file.
class Evaluation {
 public:
  Evaluation(const Reader& model, std::int64_t rows, const std::string& out_path);
  ~Evaluation();
  Evaluation(const Evaluation&) = delete;
  Evaluation& operator=(const Evaluation&) = delete;

  // A parameter's values, converted by the writer's rule to the dtype it is
  // declared with (E4 for a value that is not exact there).
  void values(const std::string& name, const Column& given);
  // A label's names, each in the model file's table (E9).
  void names(const std::string& name, const std::vector<std::string>& given);
  // rows x nodes x axes, for a model that reads geometry the file does not
  // store for every row.  They are the data file's coordinates, per run.
  void coordinates(const Column& given);
  // Checks that every input is given and every model can read what it
  // reads, runs the built-in models, and lists the W4 findings.
  void ready();

  const std::vector<std::string>& warnings() const { return warnings_; }
  // The models the caller runs (those not built in), in the order asked.
  std::vector<std::string> models() const;
  const std::vector<Request>& requests(const std::string& model_id) const;
  // An input as a model reads it: a parameter in its dtype, a label as its
  // codes (int64), coordinates as float64 rows x nodes x axes.
  DType input_dtype(const std::string& name) const;
  std::vector<std::int64_t> input_shape(const std::string& name) const;
  const std::vector<unsigned char>& input(const std::string& name) const;
  // A model's answer to one of its requests: rows values for a scalar,
  // rows x sites for a field, rows x nodes x axes for coordinates.
  void answer(const std::string& model_id, const Request& r, const double* values,
              std::int64_t count);
  // Writes the rows and closes the data file.  A request left unanswered
  // is refused and can still be answered; a failure writing the rows
  // removes the file.
  void finish();

 private:
  struct Asked {
    std::string model;
    Request request;
    std::int64_t per_row = 0;            // values per row of the answer
    std::vector<double> answer;
    bool answered = false;
  };
  Asked& asked(const std::string& model_id, const Request& r);
  const Asked* asked_for(const Result& r) const;
  bool coordinates_available() const;

  const Reader& model_;
  std::int64_t rows_;
  std::string out_path_;
  std::unique_ptr<Writer> writer_;                        // the data file, until finished
  bool ready_ = false;
  std::map<std::string, Column> parameters_;              // converted
  std::map<std::string, std::vector<std::string>> label_names_;
  std::map<std::string, std::vector<std::int64_t>> label_codes_;
  std::vector<double> coordinates_;                       // given, or the stored ones per row
  bool coordinates_given_ = false;
  bool coordinates_stored_ = false;                       // a fixed mesh's, broadcast
  std::vector<Asked> asked_;
  std::map<std::string, std::vector<Request>> requests_;  // by model, in order
  std::vector<std::string> order_;                        // models, in order asked
  std::vector<std::string> warnings_;
  mutable std::map<std::string, std::vector<unsigned char>> inputs_;   // as models read them
};

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_EVALUATE_HPP
