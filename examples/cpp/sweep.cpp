// Write three runs to first.gamut and read back the lift coefficients.
//
//   c++ -std=c++17 sweep.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o sweep
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  // Values at the same position belong to the same run.
  const std::vector<double> alpha = {0, 2, 4};
  const std::vector<double> cl = {0, 0.22, 0.44};

  auto study = gamut::create("first.gamut", "example sweep");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_scalar("cl", "1");
  study.add_runs({{"alpha", alpha}, {"cl", cl}});
  study.close();

  study = gamut::open("first.gamut");
  const auto lift = study.get_scalar("cl");

  std::printf("cl:");
  for (const double value : lift) std::printf(" %.2f", value);
  std::printf("\n");
}
