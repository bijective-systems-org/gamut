// Tests of the C++ interface, include/gamut/gamut.hpp, linked to the shared
// library as a program using it would be: every declaration, the three mesh
// arrangements, appending, reads, selections, the file copies, validation,
// and the errors.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include <gamut/gamut.hpp>

namespace {

int g_failures = 0;
int g_checks = 0;

#define CHECK(cond)                                                                         \
  do {                                                                                      \
    ++g_checks;                                                                             \
    if (!(cond)) {                                                                          \
      ++g_failures;                                                                         \
      std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond);         \
    }                                                                                       \
  } while (0)

// The rule a call is refused with ("error" when it names none), or "" when
// it succeeds.
template <class F>
std::string refused(F f) {
  try {
    f();
  } catch (const gamut::Error& e) {
    return e.rule().empty() ? std::string("error") : e.rule();
  }
  return std::string();
}

// A ring of n quadrilaterals around a square hole: 2n nodes, n cells.
std::vector<double> ring_points(int n, double scale) {
  std::vector<double> p;
  for (int ring = 1; ring <= 2; ++ring)
    for (int k = 0; k < n; ++k) {
      const double a = 2 * std::acos(-1.0) * k / n;
      p.insert(p.end(), {scale * ring * std::cos(a), scale * ring * std::sin(a)});
    }
  return p;
}

gamut::Cells ring_cells(int n) {
  gamut::Cells c;
  c.offsets.push_back(0);
  for (int64_t k = 0; k < n; ++k) {
    const int64_t next = (k + 1) % n;
    c.types.push_back(9);
    c.connectivity.insert(c.connectivity.end(), {k, next, next + n, k + n});
    c.offsets.push_back(4 * (k + 1));
  }
  return c;
}

void test_table() {
  {
    auto s = gamut::create("table.gamut", "header tests");
    s.declare_parameter("mach", "condition", "1");
    s.declare_parameter("alpha", "condition", "degree", -10.0, 10.0);
    s.declare_label("status", "status", {"converged", "failed"});
    s.declare_label("split", "split", {"train", "test"});
    s.declare_scalar("cl", "1");
    s.declare_scalar("cl_std", "1", gamut::std_of("cl"));
    s.declare_scalar("cl_p95", "1", gamut::quantile_of("cl", 0.95));
    s.declare_scalar("dcl_dalpha", "degree-1", gamut::derivative_of("cl", "alpha"));
    s.set_constant("reference_area", 12.5, "m2");
    s.set_attribute("title", "Wing A polar");
    for (int k = 0; k < 6; ++k) {
      const double alpha = 2.0 * k - 4.0;
      const int64_t id = s.add_run({{"mach", 0.5 + 0.1 * (k % 2)}, {"alpha", alpha},
                                    {"status", k == 5 ? "failed" : "converged"},
                                    {"split", k % 3 == 0 ? "test" : "train"},
                                    {"cl", 0.1 * alpha}, {"cl_std", 0.01}, {"cl_p95", 0.1 * alpha + 0.02},
                                    {"dcl_dalpha", 0.1}});
      CHECK(id == k);
    }
    CHECK(refused([&] { s.row_count(); }) == "error");          // a writer does not read
    s.close();
    CHECK(refused([&] { s.close(); }).empty());                  // closing twice is harmless
  }
  const auto s = gamut::open("table.gamut");
  CHECK(s.row_count() == 6);
  CHECK(s.type() == "table");
  CHECK(s.describe()["title"] == "Wing A polar");
  CHECK(s.describe("alpha")["units"] == "degree");
  CHECK(s.describe("cl_std")["statistic"] == "std");
  CHECK(s.describe("dcl_dalpha")["with_respect_to"] == "alpha");
  CHECK(std::fabs(std::stod(s.describe("cl_p95")["q"]) - 0.95) < 1e-12);
  CHECK(s.names("parameters").size() == 2);
  CHECK(s.categories("status") == (std::vector<std::string>{"converged", "failed"}));
  CHECK(s.get_label("status", {5}) == std::vector<std::string>{"failed"});
  CHECK(s.get_parameter("alpha", gamut::Selection::range(1, 3)) == (std::vector<double>{-2.0, 0.0}));
  CHECK(std::fabs(s.get_constant("reference_area") - 12.5) < 1e-12);
  CHECK(s.get_row_ids() == (std::vector<int64_t>{0, 1, 2, 3, 4, 5}));
  CHECK(s.select("alpha > 0 and status == converged") == (std::vector<int64_t>{3, 4}));
  CHECK(s.select("mach > 9").empty());
  CHECK(refused([&] { s.select("alpha >> 0"); }) != "");
  CHECK(refused([&] { s.get_scalar("nothing"); }) != "");
  const gamut::Report r = gamut::validate("table.gamut");
  CHECK(r.ok);
  CHECK(!r.warnings.empty());                                     // the failed run is reported
}

void test_shared_fixed_and_append() {
  const std::vector<double> points = ring_points(8, 1.0);
  const gamut::Cells cells = ring_cells(8);
  std::vector<int64_t> wall(16, 0);
  for (int k = 0; k < 8; ++k) wall[static_cast<size_t>(k)] = 1;
  {
    auto s = gamut::create("shared.gamut", "header tests", "shared", "fixed");
    s.declare_coordinates("m", 2);
    s.declare_parameter("gamma", "design", "m2 s-1");
    s.declare_mesh_label("surface", "node", {"field", "wall"});
    s.declare_field("p", "node", "Pa");
    s.declare_field("q", "cell", "W m-2");
    s.set_mesh(points, cells, {{"surface", wall}});
    for (int k = 0; k < 3; ++k)
      s.add_run({{"gamma", double(k)}}, {{"p", std::vector<double>(16, 100.0 * k)},
                                         {"q", std::vector<double>(8, double(k))}});
    s.close();
  }
  {
    auto s = gamut::open("shared.gamut", "a");
    s.add_run({{"gamma", 3.0}}, {{"p", std::vector<double>(16, 300.0)}, {"q", std::vector<double>(8, 3.0)}});
    CHECK(refused([&] { s.add_run({{"gamma", 4.0}}, {{"p", std::vector<double>(5, 0.0)}}); }) != "");
    s.close();
  }
  auto s = gamut::open("shared.gamut", "r", 2);
  CHECK(s.row_count() == 4);
  const gamut::Array<double> block = s.get_field("p");
  CHECK((block.shape == std::vector<int64_t>{4, 16}));
  CHECK(block(3, 15) == 300.0);
  const gamut::Array<double> node = s.get_field("p", gamut::all, {2});
  CHECK((node.values == std::vector<double>{0.0, 100.0, 200.0, 300.0}));
  CHECK((s.get_field("q", {1, 2}, gamut::Selection::range(0, 2)).shape == std::vector<int64_t>{2, 2}));
  const gamut::Array<double> p = s.get_points();
  CHECK((p.shape == std::vector<int64_t>{16, 2}));
  CHECK(p.values == points);
  CHECK(s.get_cells().connectivity == cells.connectivity);
  CHECK(s.get_mesh_label("surface") == wall);
  CHECK(s.categories("surface")[1] == "wall");
  CHECK(gamut::validate("shared.gamut").ok);
  // A reader does not write.
  CHECK(refused([&] { s.add_run({{"gamma", 5.0}}); }) == "error");
}

void test_family_and_changing() {
  {
    auto s = gamut::create("family.gamut", "header tests", "shared", "group:member");
    s.declare_coordinates("m", 2);
    s.declare_label("member", "group");
    s.set_generalisation_group("member");
    s.declare_parameter("gamma", "condition", "m2 s-1");
    s.declare_field("p", "node", "Pa");
    s.set_mesh(16, ring_cells(8));
    for (int m = 0; m < 2; ++m)
      for (int k = 0; k < 2; ++k) {
        gamut::Geometry g{ring_points(8, 1.0 + m), std::nullopt, {}};
        s.add_run({{"member", m == 0 ? "slim" : "wide"}, {"gamma", double(k)}},
                  {{"p", std::vector<double>(16, double(m))}}, g);
      }
    // A geometry needs its member by name.
    CHECK(refused([&] { s.add_run({{"gamma", 9.0}}, {{"p", std::vector<double>(16, 0.0)}},
                                  gamut::Geometry{ring_points(8, 3.0), std::nullopt, {}}); }) == "E2");
    s.close();
  }
  const auto f = gamut::open("family.gamut");
  CHECK(f.row_count() == 4);
  CHECK(std::fabs(f.get_points(2).values[0] - 2.0) < 1e-12);    // the wide member's first node
  CHECK(f.get_label("member") == (std::vector<std::string>{"slim", "slim", "wide", "wide"}));

  {
    auto s = gamut::create("changing.gamut", "header tests", "changing", "run");
    s.declare_coordinates("m", 2);
    s.declare_parameter("n", "design", "1");
    s.declare_field("q", "cell", "1");
    for (int n : {4, 8}) {
      gamut::Geometry g{ring_points(n, 1.0), ring_cells(n), {}};
      s.add_run({{"n", double(n)}}, {{"q", std::vector<double>(static_cast<size_t>(n), 1.0)}}, g);
    }
    s.close();
  }
  const auto c = gamut::open("changing.gamut");
  CHECK(c.type() == "changing");
  CHECK(c.get_cells(1).types.size() == 8);
  CHECK(c.get_field("q", {1}).size() == 8);
  CHECK(refused([&] { c.get_field("q"); }) != "");              // across runs needs a shared mesh
}

void test_copies_and_errors() {
  gamut::write_copy("table.gamut", "table_again.gamut");
  CHECK(refused([] { gamut::append("table.gamut", "table.gamut"); }) != "");   // one file
  CHECK(gamut::append("table.gamut", "table_again.gamut") == 6);
  gamut::extract("table.gamut", "subset.gamut", {0, 7});
  CHECK(gamut::open("subset.gamut").get_row_ids() == (std::vector<int64_t>{0, 7}));
  gamut::write_copy("subset.gamut", "subset_copy.gamut");
  CHECK(gamut::open("subset_copy.gamut").describe()["file_id"] ==
        gamut::open("subset.gamut").describe()["file_id"]);
  CHECK(refused([] { gamut::open("no such file.gamut"); }) != "");
  CHECK(refused([] { gamut::open("table.gamut", "w"); }) == "error");
  CHECK(refused([] {
          auto s = gamut::create("bad.gamut", "header tests");
          s.declare_parameter("speed", "condition", "m//s");
        }) != "");
  // A shared mesh never set refuses to close; leaving scope then discards
  // the file instead of leaving half of one.
  {
    auto s = gamut::create("unfinished.gamut", "header tests", "shared", "fixed");
    s.declare_coordinates("m", 2);
    CHECK(refused([&] { s.close(); }) != "");
  }
  CHECK(refused([] { gamut::open("unfinished.gamut"); }) != "");
  CHECK(gamut::format() == "gamut/1");
  CHECK(!gamut::version().empty());
}

}  // namespace

int main() {
  test_table();
  test_shared_fixed_and_append();
  test_family_and_changing();
  test_copies_and_errors();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
