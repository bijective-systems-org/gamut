// The ring of quadrilaterals around a cylinder that several examples share,
// as examples/_cylinder.py.
#pragma once

#include <cmath>
#include <cstdint>
#include <vector>

#include <gamut/gamut.hpp>

struct Ring {
  std::vector<double> points;  // nodes x 2, around each ring first
  gamut::Cells cells;          // VTK quadrilaterals
  std::vector<double> t, r;    // each node's polar coordinates
};

inline Ring ring(int n_theta = 48, int n_r = 12, double radius = 1.0, double outer = 6.0) {
  const double pi = std::acos(-1.0);
  Ring g;
  for (int j = 0; j < n_r; ++j) {
    for (int i = 0; i < n_theta; ++i) {
      g.t.push_back(2 * pi * i / n_theta);
      g.r.push_back(radius * std::pow(outer, double(j) / (n_r - 1)));
      g.points.insert(g.points.end(), {g.r.back() * std::cos(g.t.back()), g.r.back() * std::sin(g.t.back())});
    }
  }
  g.cells.offsets.push_back(0);
  for (int j = 0; j < n_r - 1; ++j) {
    for (int i = 0; i < n_theta; ++i) {
      const int64_t a = j * n_theta + i, b = j * n_theta + (i + 1) % n_theta;
      g.cells.types.push_back(9);
      g.cells.connectivity.insert(g.cells.connectivity.end(), {a, b, b + n_theta, a + n_theta});
      g.cells.offsets.push_back(int64_t(g.cells.connectivity.size()));
    }
  }
  return g;
}

// Pressure coefficient of potential flow past a cylinder with circulation
// gamma, free stream speed 1, at the points with polar coordinates t, r.
inline std::vector<double> pressure(const std::vector<double>& t, const std::vector<double>& r,
                                    double radius = 1.0, double gamma = 0.0) {
  const double pi = std::acos(-1.0);
  std::vector<double> cp(t.size());
  for (size_t k = 0; k < t.size(); ++k) {
    const double u_r = std::cos(t[k]) * (1 - radius * radius / (r[k] * r[k]));
    const double u_t = -std::sin(t[k]) * (1 + radius * radius / (r[k] * r[k])) + gamma / (2 * pi * r[k]);
    cp[k] = 1 - (u_r * u_r + u_t * u_t);
  }
  return cp;
}
