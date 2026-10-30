// Growing, splitting and rewriting files.
//
// gamut::append adds one file's runs to another (the same declarations;
// category names merged); gamut::extract keeps chosen runs as a new file,
// their ids kept; gamut::write_copy rewrites a file with the default layout,
// keeping its identity. examples/09_combining_files.py and the MATLAB and
// Julia examples are the same program and print the same lines.
//
//   c++ -std=c++17 combining.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o combining
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

#include <gamut/gamut.hpp>

void sweep(const std::string& path, const std::vector<double>& machs) {
  auto study = gamut::create(path, "example sweep");
  study.declare_parameter("mach", "condition", "1");
  study.declare_label("status", "status", {"converged", "failed"});
  study.declare_scalar("cd", "1");
  for (const double mach : machs) {
    const double excess = std::max(0.0, mach - 0.7);
    study.add_run({{"mach", mach}, {"status", mach > 0.85 ? "failed" : "converged"}, {"cd", 0.01 + 0.05 * excess * excess}});
  }
  study.close();
}

int main() {
  sweep("monday.gamut", {0.5, 0.6, 0.7});
  sweep("tuesday.gamut", {0.8, 0.9});
  std::printf("appended %lld runs\n", (long long)gamut::append("monday.gamut", "tuesday.gamut"));

  const auto good = gamut::open("monday.gamut").select("status == converged");
  gamut::extract("monday.gamut", "converged.gamut", good);
  gamut::write_copy("converged.gamut", "converged_copy.gamut");

  const auto study = gamut::open("converged.gamut"), copy = gamut::open("converged_copy.gamut");
  std::printf("kept ids:");
  for (const int64_t id : study.get_row_ids()) std::printf(" %lld", (long long)id);
  std::printf(" at mach");
  for (const double mach : study.get_parameter<double>("mach")) std::printf(" %g", mach);
  std::printf("\n");
  const bool same = study.describe()["file_id"] == copy.describe()["file_id"];
  std::printf("same file id after the rewrite: %s\n", same ? "yes" : "no");
  std::printf("valid: %s\n", gamut::validate("converged.gamut").ok ? "yes" : "no");
}
