// A study with no mesh: a table of runs, each with its inputs and results.
// A sweep of a wing over Mach number and angle of attack.
// examples/01_run_table.py and the MATLAB and Julia examples are the same
// program and print the same lines.
//
//   c++ -std=c++17 run_table.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o run_table
#include <cmath>
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  auto study = gamut::create("polar.gamut", "example sweep");
  study.declare_parameter("mach", "condition", "1");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_label("status", "status", {"converged", "failed"});
  study.declare_scalar("cl", "1");
  study.declare_scalar("cd", "1");
  study.set_constant("reference_area", 12.5, "m2");
  study.set_attribute("title", "Wing A polar");
  for (const double mach : {0.6, 0.7, 0.8}) {
    for (int alpha = -2; alpha <= 8; alpha += 2) {
      const double cl = 0.11 * alpha / std::sqrt(1 - mach * mach);  // stand-in for a solver
      const double cd = 0.008 + 0.04 * cl * cl;
      const bool failed = mach == 0.8 && alpha == 8;
      study.add_run({{"mach", mach}, {"alpha", double(alpha)},
                     {"status", failed ? "failed" : "converged"},
                     {"cl", failed ? NAN : cl}, {"cd", failed ? NAN : cd}});
    }
  }
  study.close();

  study = gamut::open("polar.gamut");
  std::printf("%lld runs; %s\n", (long long)study.row_count(), study.describe()["title"].c_str());
  const std::vector<double> cl = study.get_scalar("cl", study.select("mach == 0.7"));
  std::printf("lift at Mach 0.7:");
  for (const double v : cl) std::printf(" %.3f", v);
  std::printf("\n");
  const auto failed = study.select("status == failed");
  const double mach = study.get_parameter<double>("mach", failed)[0];
  const double alpha = study.get_parameter<double>("alpha", failed)[0];
  std::printf("failed: Mach %.1f, alpha %g degree\n", mach, alpha);
  std::printf("reference area: %g %s\n", study.get_constant<double>("reference_area"),
              study.describe("reference_area")["units"].c_str());
}
