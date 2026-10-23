// A sweep of a wing's angle of attack: six runs written, a seventh added,
// then read. examples/00_readme.py and the MATLAB and Julia examples are the
// same program and print the same line.
//
//   c++ -std=c++17 sweep.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o sweep
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

// Stands for the solver: the lift coefficient at one angle of attack.
double solve(double alpha) { return 0.11 * alpha; }

int main() {
  auto study = gamut::create("sweep.gamut", "example sweep");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_label("status", "status", {"converged", "failed"});
  study.declare_scalar("cl", "1");
  for (double alpha = 0.0; alpha <= 10.0; alpha += 2.0)
    study.add_run({{"alpha", alpha}, {"status", "converged"}, {"cl", solve(alpha)}});
  study.close();

  study = gamut::open("sweep.gamut", "a");
  study.add_run({{"alpha", 12.0}, {"status", "failed"}});
  study.close();

  study = gamut::open("sweep.gamut");
  const std::vector<double> cl = study.get_scalar("cl", study.select("status == converged"));
  std::printf("lift of the runs that converged:");
  for (const double v : cl) std::printf(" %.2f", v);
  std::printf("\n");
}
