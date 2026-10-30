// A sweep of a wing's angle of attack: six runs written, a seventh added,
// then read. The six are written at once, as columns. examples/00_readme.py
// and the MATLAB and Julia examples are the same program and print the same
// line.
//
//   c++ -std=c++17 sweep.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o sweep
#include <cstdio>
#include <string>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  const std::vector<double> alpha = {0, 2, 4, 6, 8, 10};  // angles of attack, degrees
  std::vector<double> cl;  // stands for the solver's lift coefficients
  for (const double a : alpha) cl.push_back(0.11 * a);

  auto study = gamut::create("sweep.gamut", "example sweep");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_label("status", "status", {"converged", "failed"});
  study.declare_scalar("cl", "1");
  const std::vector<std::string> status(alpha.size(), "converged");
  study.add_runs({{"alpha", alpha}, {"cl", cl}, {"status", status}});
  study.close();

  study = gamut::open("sweep.gamut", "a");
  study.add_run({{"alpha", 12.0}, {"status", "failed"}});
  study.close();

  study = gamut::open("sweep.gamut");
  const std::vector<double> lift =
      study.get_scalar("cl", study.select("status == converged"));
  std::printf("lift of the runs that converged:");
  for (const double v : lift) std::printf(" %.2f", v);
  std::printf("\n");
}
