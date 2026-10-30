// Runs on different meshes: a refinement study.
//
// The same flow on three meshes of increasing resolution, with the pressure
// stored per cell. examples/04_changing_mesh.py and the MATLAB and Julia
// examples are the same program and print the same lines.
//
//   c++ -std=c++17 refinement.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o refinement
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

#include "cylinder.hpp"

int main() {
  auto study = gamut::create("refinement.gamut", "example refinement", "changing", "run");
  study.declare_coordinates("m", 2);
  study.declare_parameter("cells_round", "design", "1");
  study.declare_scalar("cp_min", "1");
  study.declare_field("cp", "cell", "1");
  for (const int n : {24, 48, 96}) {
    const Ring g = ring(n, n / 4);
    std::vector<double> t, r;                       // each cell's centre, in polar coordinates
    for (size_t c = 0; c + 1 < g.cells.offsets.size(); ++c) {
      double x = 0, y = 0;
      for (int64_t k = g.cells.offsets[c]; k < g.cells.offsets[c + 1]; ++k) {
        x += g.points[2 * g.cells.connectivity[k]];
        y += g.points[2 * g.cells.connectivity[k] + 1];
      }
      t.push_back(std::atan2(y / 4, x / 4));
      r.push_back(std::hypot(x / 4, y / 4));
    }
    const std::vector<double> cp = pressure(t, r);
    study.add_run({{"cells_round", double(n)}, {"cp_min", *std::min_element(cp.begin(), cp.end())}},
                  {{"cp", cp}}, gamut::Geometry{g.points, g.cells, {}});
  }
  study.close();

  study = gamut::open("refinement.gamut");
  const std::vector<double> rounds = study.get_parameter<double>("cells_round");
  for (int64_t row = 0; row < study.row_count(); ++row) {
    const gamut::Cells cells = study.get_cells(row);
    const std::vector<double> cp = study.get_field("cp", {row}).values;
    std::printf("%g cells round: %lld nodes, %zu cells, lowest cell cp %.3f\n", rounds[size_t(row)],
                (long long)study.get_points(row).shape[0], cells.types.size(),
                *std::min_element(cp.begin(), cp.end()));
  }
}
