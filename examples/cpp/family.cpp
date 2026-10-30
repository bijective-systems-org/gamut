// A family of geometries that share one mesh topology.
//
// Three cylinders of different radius, meshed with the same topology, so
// node k is the same place on every member, each run at three circulations.
// examples/03_geometry_family.py and the MATLAB and Julia examples are the
// same program and print the same lines.
//
//   c++ -std=c++17 family.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o family
#include <cstdio>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <gamut/gamut.hpp>

#include "cylinder.hpp"

int main() {
  const std::vector<std::pair<std::string, double>> members = {{"slim", 0.8}, {"base", 1.0}, {"wide", 1.2}};
  const Ring base = ring();

  auto study = gamut::create("family.gamut", "example family", "shared", "group:member");
  study.declare_coordinates("m", 2);
  study.declare_label("member", "group", {"slim", "base", "wide"});
  study.declare_label("split", "split", {"train", "test"});
  study.set_generalisation_group("member");
  study.declare_parameter("gamma", "condition", "m2 s-1");
  study.declare_field("cp", "node", "1");
  study.set_mesh(int64_t(base.t.size()), base.cells);
  for (const auto& [name, radius] : members) {
    const Ring member = ring(48, 12, radius);
    for (const double gamma : {0.0, 2.0, 4.0}) {
      study.add_run({{"member", name}, {"gamma", gamma}, {"split", name == "wide" ? "test" : "train"}},
                    {{"cp", pressure(member.t, member.r, radius, gamma)}}, gamut::Geometry{member.points, std::nullopt, {}});
    }
  }
  study.close();

  study = gamut::open("family.gamut");
  std::printf("%lld runs on %zu members of one topology\n", (long long)study.row_count(), members.size());
  for (const auto& [name, radius] : members) {
    const int64_t first = study.select("member == " + name)[0];
    std::printf("  %s: first node at x = %.2f m\n", name.c_str(), study.get_points(first)(0, 0));
  }
  std::printf("cp at the first node, run by run:");
  for (const double v : study.get_field("cp", gamut::all, {0})) std::printf(" %.2f", v);
  std::printf("\n");
  const auto test = study.select("split == test");
  const auto held = study.get_label("member", test);
  std::string names;
  for (const auto& name : std::set<std::string>(held.begin(), held.end())) names += (names.empty() ? "" : ", ") + name;
  std::printf("held out for testing: %zu runs of %s\n", test.size(), names.c_str());
}
