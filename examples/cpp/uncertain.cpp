// Uncertainty and gradients beside the values they describe.
//
// Each run stores a lift coefficient with its standard deviation and two
// quantiles, and its derivative with respect to angle of attack. Each names
// the result it describes, so a reader finds them by their declarations.
// examples/06_uncertainty_gradients.py and the MATLAB and Julia examples are
// the same program and print the same lines.
//
//   c++ -std=c++17 uncertain.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o uncertain
#include <cstdio>
#include <map>
#include <string>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  std::vector<double> alpha, cl, spread, low, high;
  for (int k = 0; k <= 8; ++k) {
    alpha.push_back(k);
    cl.push_back(0.11 * k);
    spread.push_back(0.01 + 0.002 * k);
    low.push_back(cl.back() - 1.645 * spread.back());
    high.push_back(cl.back() + 1.645 * spread.back());
  }
  auto study = gamut::create("uncertain.gamut", "example ensemble");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_scalar("cl", "1");
  study.declare_scalar("cl_std", "1", gamut::std_of("cl"));
  study.declare_scalar("cl_p05", "1", gamut::quantile_of("cl", 0.05));
  study.declare_scalar("cl_p95", "1", gamut::quantile_of("cl", 0.95));
  study.declare_scalar("dcl_dalpha", "degree-1", gamut::derivative_of("cl", "alpha"));
  study.add_runs({{"alpha", alpha}, {"cl", cl}, {"cl_std", spread}, {"cl_p05", low}, {"cl_p95", high},
                  {"dcl_dalpha", std::vector<double>(9, 0.11)}});
  study.close();

  study = gamut::open("uncertain.gamut");
  std::string spread_name, derivative;
  std::map<double, std::string> quantiles;
  for (const std::string& name : study.names("scalars")) {  // what describes cl, read from each declaration
    auto d = study.describe(name);
    if (d["of"] != "cl") continue;
    if (!d["with_respect_to"].empty()) derivative = name;
    else if (d["statistic"] == "std") spread_name = name;
    else quantiles[std::stod(d["q"])] = name;
  }
  std::printf("the std of cl: %s\n", spread_name.c_str());
  std::printf("its 0.05 and 0.95 quantiles: %s %s\n", quantiles[0.05].c_str(), quantiles[0.95].c_str());
  std::printf("its derivative with respect to alpha: %s\n", derivative.c_str());
  const std::vector<double> p05 = study.get_scalar(quantiles[0.05]), p95 = study.get_scalar(quantiles[0.95]);
  std::printf("90 %% band at 8 degrees: %.3f to %.3f\n", p05.back(), p95.back());
}
