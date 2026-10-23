// Tests of the C++ interface, include/gamut/gamut.hpp, linked to the shared
// library as a program using it would be: every declaration, the three mesh
// arrangements, appending, reads, selections, the file copies, validation,
// the errors, and calls from several threads at once.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <thread>
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

void test_integers_batches_and_reads() {
  {
    auto s = gamut::create("batches.gamut", "header tests");
    s.declare_label("run", "group");
    s.declare_parameter("t", "time", "s", "run");
    s.declare_parameter("n", "design", "1");
    s.declare_scalar("cl", "1");
    CHECK(s.handle() != nullptr);
    gamut::Study moved = std::move(s);                            // the file moves with the study
    CHECK(s.handle() == nullptr);
    CHECK(moved.add_run({{"run", "a"}, {"t", 0.0}, {"n", 3}, {"cl", 0.5}}) == 0);
    const std::vector<int64_t> ids = moved.add_runs(
        {{"run", std::vector<std::string>{"a", "b", "b"}}, {"t", std::vector<double>{1.0, 0.0, 1.0}},
         {"n", std::vector<int64_t>{3, 4, 4}}, {"cl", std::vector<double>{0.6, 0.7, 0.8}}});
    CHECK((ids == std::vector<int64_t>{1, 2, 3}));
    CHECK(refused([&] { moved.add_runs({{"t", std::vector<double>{1.0}}, {"n", std::vector<int64_t>{}}}); }) == "E5");
    moved.close();
  }
  {
    auto s = gamut::open("batches.gamut", "a");                    // a table, no mesh
    s.add_run({{"run", "c"}, {"t", 0.0}, {"n", 5}, {"cl", 0.9}});
    s.close();
  }
  const auto s = gamut::open("batches.gamut");
  CHECK(s.row_count() == 5);
  CHECK(s.describe("n")["dtype"] == "int64");
  CHECK((s.read<int64_t>("n", gamut::all, gamut::all).values == std::vector<int64_t>{3, 3, 4, 4, 5}));
  CHECK((s.read<int32_t>("n", {4}, gamut::all).values == std::vector<int32_t>{5}));
  CHECK(std::fabs(s.read<float>("cl", {1}, gamut::all).values[0] - 0.6f) < 1e-6f);
  CHECK((s.get_scalar("cl", std::vector<int64_t>{0, 3}) == std::vector<double>{0.5, 0.8}));
  CHECK(s.get_scalar("cl", std::vector<int64_t>{}).empty());       // no positions, no values
  CHECK(s.describe("t")["run_group"] == "run");
  CHECK((s.select("run == b") == std::vector<int64_t>{2, 3}));
  const gamut::Array<double> cl = s.get_field("cl");               // any name reads as an array
  double total = 0;
  for (double v : cl) total += v;
  CHECK(std::fabs(total - 3.5) < 1e-12 && cl[4] == 0.9);
}

void test_geometry_per_run_and_members() {
  {
    auto s = gamut::create("per_run.gamut", "header tests", "shared", "run");
    s.declare_coordinates("m", 2);
    s.declare_parameter("k", "condition", "1");
    s.declare_field("p", "node", "Pa");
    s.set_mesh(16, ring_cells(8));
    for (int k = 0; k < 2; ++k)
      s.add_run({{"k", double(k)}}, {{"p", std::vector<double>(16, 0.0)}},
                gamut::Geometry{ring_points(8, 1.0 + k), std::nullopt, {}});
    s.close();
  }
  const auto r = gamut::open("per_run.gamut");
  CHECK(refused([&] { r.get_points(); }) == "error");            // the geometry changes: give the row
  const gamut::Array<double> p = r.get_points(1);
  CHECK((p.shape == std::vector<int64_t>{16, 2}) && std::fabs(p(0, 0) - 2.0) < 1e-12);

  {
    auto s = gamut::open("family.gamut", "a");
    s.add_run({{"member", "slim"}, {"gamma", 5.0}}, {{"p", std::vector<double>(16, 0.0)}});
    s.add_run({{"member", "huge"}, {"gamma", 5.0}}, {{"p", std::vector<double>(16, 9.0)}},
              gamut::Geometry{ring_points(8, 4.0), std::nullopt, {}});
    s.close();
  }
  const auto f = gamut::open("family.gamut");
  CHECK(f.row_count() == 6);
  CHECK(std::fabs(f.get_points(5)(0, 0) - 4.0) < 1e-12);
  CHECK(gamut::validate("family.gamut").ok);
}

void test_refusals_before_the_library() {
  auto s = gamut::create("cells.gamut", "header tests", "shared", "fixed");
  s.declare_coordinates("m", 2);
  gamut::Cells short_offsets = ring_cells(8);
  short_offsets.offsets.pop_back();
  CHECK(refused([&] { s.set_mesh(ring_points(8, 1.0), short_offsets); }) == "E5");
  CHECK(refused([&] { s.set_mesh(std::vector<double>(5, 0.0), ring_cells(8)); }) == "E5");
  s.abandon();
  CHECK(refused([] { gamut::open("cells.gamut"); }) != "");          // abandoned and removed
  {
    auto cloud = gamut::create("cloud.gamut", "header tests", "shared", "fixed");   // probes, no cells
    cloud.declare_coordinates("m", 3);
    cloud.declare_field("p", "node", "Pa");
    cloud.set_mesh({0, 0, 0, 1, 0, 0, 0, 1, 0}, gamut::Cells{});
    cloud.add_run({}, {{"p", {1.0, 2.0, 3.0}}});
    cloud.close();
  }
  CHECK((gamut::open("cloud.gamut").get_field("p").values == std::vector<double>{1.0, 2.0, 3.0}));
  std::FILE* text = std::fopen("not_a_study.gamut", "w");
  std::fputs("not HDF5\n", text);
  std::fclose(text);
  const gamut::Report report = gamut::validate("not_a_study.gamut");
  CHECK(!report.ok && !report.errors.empty() && report.errors[0].rule == "E1");
}

}  // namespace

// Threads that write and read their own files and read a shared one at the
// same time: HDF5 is not thread-safe, so the library makes the calls take
// turns.  Without that, this crashes inside HDF5.
void test_calls_from_several_threads() {
  {
    auto s = gamut::create("threads_shared.gamut", "header tests");
    s.declare_parameter("x", "design", "1");
    s.declare_scalar("y", "1");
    for (int k = 0; k < 50; ++k) s.add_run({{"x", double(k)}, {"y", 2.0 * k}});
    s.close();
  }
  const std::size_t threads = 8;
  std::vector<int> wrong(threads, 0);
  std::vector<std::thread> pool;
  for (std::size_t t = 0; t < threads; ++t) {
    pool.emplace_back([t, &wrong] {
      try {
        const std::string own = "thread" + std::to_string(t) + ".gamut";
        for (int round = 0; round < 20; ++round) {
          {
            auto w = gamut::create(own, "header tests");
            w.declare_parameter("x", "design", "1");
            w.declare_scalar("y", "1");
            for (int k = 0; k < 10; ++k) w.add_run({{"x", double(k)}, {"y", static_cast<double>(t)}});
            w.close();
          }
          const auto mine = gamut::open(own);
          if (mine.get_scalar("y") != std::vector<double>(10, static_cast<double>(t))) ++wrong[t];
          const auto shared = gamut::open("threads_shared.gamut");
          const std::vector<double> y = shared.get_scalar("y");
          if (y.size() != 50 || y[49] != 98.0) ++wrong[t];
        }
      } catch (...) {
        ++wrong[t];
      }
    });
  }
  for (auto& th : pool) th.join();
  for (std::size_t t = 0; t < threads; ++t) {
    CHECK(wrong[t] == 0);
    std::remove(("thread" + std::to_string(t) + ".gamut").c_str());
  }
  std::remove("threads_shared.gamut");
}

int main() {
  test_table();
  test_shared_fixed_and_append();
  test_family_and_changing();
  test_copies_and_errors();
  test_integers_batches_and_reads();
  test_geometry_per_run_and_members();
  test_refusals_before_the_library();
  test_calls_from_several_threads();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
