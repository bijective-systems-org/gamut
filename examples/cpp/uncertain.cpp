// Uncertainty and gradients beside the values they describe.
//
// Each run stores a lift coefficient with its standard deviation and two
// quantiles, and its derivative with respect to angle of attack. Each names
// the result it describes, so a reader finds them without naming conventions.
// examples/06_uncertainty_gradients.py and the MATLAB and Julia examples are
// the same program and print the same lines.
//
//   c++ -std=c++17 uncertain.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o uncertain
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  std::vector<double> alpha, cl, spread, p05, p95;
  for (int k = 0; k <= 8; ++k) {
    alpha.push_back(k);
    cl.push_back(0.11 * k);
    spread.push_back(0.01 + 0.002 * k);
    p05.push_back(cl.back() - 1.645 * spread.back());
    p95.push_back(cl.back() + 1.645 * spread.back());
  }
  auto study = gamut::create("uncertain.gamut", "example ensemble");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_scalar("cl", "1");
  study.declare_scalar("cl_std", "1", gamut::std_of("cl"));
  study.declare_scalar("cl_p05", "1", gamut::quantile_of("cl", 0.05));
  study.declare_scalar("cl_p95", "1", gamut::quantile_of("cl", 0.95));
  study.declare_scalar("dcl_dalpha", "degree-1", gamut::derivative_of("cl", "alpha"));
  study.add_runs({{"alpha", alpha}, {"cl", cl}, {"cl_std", spread}, {"cl_p05", p05}, {"cl_p95", p95},
                  {"dcl_dalpha", std::vector<double>(9, 0.11)}});
  study.close();

  study = gamut::open("uncertain.gamut");
  const gamut::Related related = study.related("cl");
  std::printf("the std of cl: %s\n", related.std_dev.c_str());
  std::printf("its 0.05 and 0.95 quantiles: %s %s\n", related.quantiles.at(0.05).c_str(),
              related.quantiles.at(0.95).c_str());
  std::printf("its derivative with respect to alpha: %s\n", related.derivatives.at("alpha").c_str());
  const std::vector<double> low = study.get_scalar(related.quantiles.at(0.05));
  const std::vector<double> high = study.get_scalar(related.quantiles.at(0.95));
  std::printf("90 %% band at 8 degrees: %.3f to %.3f\n", low.back(), high.back());
}
