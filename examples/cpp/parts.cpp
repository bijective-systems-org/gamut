// Reading only what you need: rows by condition, nodes by zone.
//
// Runs are chosen with a small expression language and nodes by a mesh
// label. Values arrive in the units they were stored in; this program
// converts them itself, where Python's reads convert on request.
// examples/08_selecting_parts.py and the MATLAB and Julia examples are the
// same program and print the same lines.
//
//   c++ -std=c++17 parts.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o parts
#include <algorithm>
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

#include "cylinder.hpp"

int main() {
  const Ring g = ring();
  const double r_wall = *std::min_element(g.r.begin(), g.r.end());
  std::vector<int64_t> surface;                     // 1 on the wall
  for (const double r : g.r) surface.push_back(r == r_wall ? 1 : 0);

  auto study = gamut::create("parts.gamut", "example parts", "shared", "fixed");
  study.declare_coordinates("m", 2);
  study.declare_parameter("gamma", "condition", "m2 s-1");
  study.declare_parameter("speed", "condition", "m s-1");
  study.declare_label("status", "status", {"converged", "failed"});
  study.declare_mesh_label("surface", "node", {"field", "wall"});
  study.declare_field("p", "node", "Pa");
  study.set_mesh(g.points, g.cells, {{"surface", surface}});
  for (const double speed : {10.0, 20.0, 40.0}) {
    for (const double gamma : {0.0, 2.0, 4.0}) {
      const double q = 0.5 * 1.225 * speed * speed;  // dynamic pressure, air at sea level
      std::vector<double> p = pressure(g.t, g.r, 1.0, gamma);
      for (double& v : p) v *= q;
      study.add_run({{"gamma", gamma}, {"speed", speed}, {"status", "converged"}}, {{"p", p}});
    }
  }
  study.close();

  study = gamut::open("parts.gamut");
  const auto rows = study.select("speed >= 20 and gamma > 1 and status == converged");
  std::printf("chosen: %zu runs\n", rows.size());
  const auto names = study.categories("surface");
  const int64_t wall = std::find(names.begin(), names.end(), "wall") - names.begin();
  std::vector<int64_t> on_wall;
  const auto label = study.get_mesh_label("surface");
  for (int64_t k = 0; k < int64_t(label.size()); ++k)
    if (label[size_t(k)] == wall) on_wall.push_back(k);
  const auto p_wall = study.get_field("p", rows, on_wall);  // stored in Pa
  const double lowest = *std::min_element(p_wall.values.begin(), p_wall.values.end()) / 1000;
  std::printf("wall pressure: %lld runs x %lld nodes, lowest %.3f kPa\n", (long long)p_wall.shape[0],
              (long long)p_wall.shape[1], lowest);
  std::printf("speeds in km/h:");
  for (const double v : study.get_parameter<double>("speed", rows)) std::printf(" %.1f", v * 3.6);  // stored in m s-1
  std::printf("\n");
}
