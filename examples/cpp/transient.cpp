// Transient runs: every saved step is a row.
//
// Two transient runs, each saved at 101 time steps. Time is a parameter with
// the role time, and a group label says which run each step belongs to.
// examples/05_time_series.py and the MATLAB and Julia examples are the same
// program and print the same lines.
//
//   c++ -std=c++17 transient.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o transient
#include <cmath>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  const double pi = std::acos(-1.0);
  std::vector<double> steps;
  for (int k = 0; k <= 100; ++k) steps.push_back(0.1 * k);

  auto study = gamut::create("transient.gamut", "example transient");
  study.declare_label("run", "group");
  study.declare_parameter("t", "time", "s", "run");
  study.declare_parameter("speed", "condition", "m s-1");
  study.declare_scalar("cl", "1");
  for (const auto& [name, speed] : std::vector<std::pair<std::string, double>>{{"slow", 20.0}, {"fast", 35.0}}) {
    const double frequency = 0.2 * speed / 10.0;    // shedding, Strouhal 0.2
    std::vector<double> cl;
    for (const double t : steps) cl.push_back(0.8 * std::sin(2 * pi * frequency * t) * (1 - std::exp(-t)));
    study.add_runs({{"run", std::vector<std::string>(steps.size(), name)}, {"t", steps},
                    {"speed", std::vector<double>(steps.size(), speed)}, {"cl", cl}});
  }
  study.close();

  study = gamut::open("transient.gamut");
  std::printf("%lld rows, %zu runs\n", (long long)study.row_count(), study.categories("run").size());
  const auto fast = study.select("run == fast");
  const std::vector<double> t = study.get_parameter<double>("t", fast), cl = study.get_scalar("cl", fast);
  size_t peak = 0;
  for (size_t k = 1; k < cl.size(); ++k)
    if (std::abs(cl[k]) > std::abs(cl[peak])) peak = k;
  std::printf("fast run: %zu steps, peak |cl| %.2f at t = %.1f s\n", fast.size(), std::abs(cl[peak]), t[peak]);
}
