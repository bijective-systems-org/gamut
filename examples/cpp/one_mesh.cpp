// A sweep on one mesh: eight runs written, a ninth added, then read.
//
// Potential flow past a cylinder at nine values of circulation, on one ring
// of quadrilaterals. examples/00_readme.py and the MATLAB, Julia and C
// examples are the same program and print the same line.
//
//   c++ -std=c++17 one_mesh.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o one_mesh
#include <cmath>
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

constexpr int n_theta = 48, n_r = 12, n_nodes = n_theta * n_r, n_cells = n_theta * (n_r - 1);
const double pi = std::acos(-1.0);
std::vector<double> t(n_nodes), r(n_nodes);

// Stands for the solver: cp at every node for one value of circulation.
std::vector<double> solve(double gamma) {
  std::vector<double> cp(n_nodes);
  for (int k = 0; k < n_nodes; ++k) {
    const double u_t = -std::sin(t[k]) * (1 + 1 / (r[k] * r[k])) + gamma / (2 * pi * r[k]);
    const double u_r = std::cos(t[k]) * (1 - 1 / (r[k] * r[k]));
    cp[k] = 1 - (u_r * u_r + u_t * u_t);
  }
  return cp;
}

int main() {
  std::vector<double> points;                       // nodes x 2, around each ring first
  for (int k = 0; k < n_nodes; ++k) {
    t[k] = 2 * pi * (k % n_theta) / n_theta;
    r[k] = std::pow(6.0, double(k / n_theta) / (n_r - 1));
    points.insert(points.end(), {r[k] * std::cos(t[k]), r[k] * std::sin(t[k])});
  }
  gamut::Cells cells;                               // VTK quadrilaterals
  cells.offsets.push_back(0);
  for (int c = 0; c < n_cells; ++c) {
    const int64_t a = c, b = c - c % n_theta + (c + 1) % n_theta;
    cells.types.push_back(9);
    cells.connectivity.insert(cells.connectivity.end(), {a, b, b + n_theta, a + n_theta});
    cells.offsets.push_back(4 * (c + 1));
  }

  {
    auto study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed");
    study.declare_coordinates("m", 2);
    study.declare_parameter("gamma", "design", "m2 s-1");
    study.declare_field("cp", "node", "1");
    study.set_mesh(points, cells);
    for (double gamma = 0.0; gamma < 3.75; gamma += 0.5)
      study.add_run({{"gamma", gamma}}, {{"cp", solve(gamma)}});
    study.close();
  }

  {
    auto study = gamut::open("cylinder.gamut", "a");
    study.add_run({{"gamma", 4.0}}, {{"cp", solve(4.0)}});
    study.close();
  }

  auto study = gamut::open("cylinder.gamut");
  auto cp = study.get_field("cp", gamut::all, {12});    // runs x nodes
  std::printf("cp at the top of the cylinder, run by run:");
  for (double v : cp) std::printf(" %.2f", v);
  std::printf("\n");
}
