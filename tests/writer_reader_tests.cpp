// Writer and reader of the core, end to end on real files: every file type,
// appends in one session and across reopenings, and refusals by rule.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

#include "chunk.hpp"
#include "h5.hpp"
#include "reader.hpp"
#include "types.hpp"
#include "writer.hpp"

namespace {

int g_failures = 0;
int g_checks = 0;

#define CHECK(cond)                                                         \
  do {                                                                      \
    ++g_checks;                                                             \
    if (!(cond)) {                                                          \
      ++g_failures;                                                         \
      std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                   #cond);                                                  \
    }                                                                       \
  } while (0)

template <class F>
std::string rule_of(F f) {
  try {
    f();
  } catch (const mestra::Error& e) {
    return e.rule().empty() ? std::string("error") : e.rule();
  }
  return std::string();
}

using mestra::DType;
using mestra::Selection;
using namespace mestra::internal;

Column f64(const std::vector<double>& v) {
  return Column::of(DType::Float64, v.data(), static_cast<std::int64_t>(v.size()));
}
Column f32(const std::vector<float>& v) {
  return Column::of(DType::Float32, v.data(), static_cast<std::int64_t>(v.size()));
}

Parameter param(const std::string& name, const std::string& role,
                const std::string& units) {
  Parameter p;
  p.name = name;
  p.role = role;
  p.units = units;
  return p;
}

Result scalar(const std::string& name, const std::string& units,
              DType t = DType::Float64) {
  Result r;
  r.name = name;
  r.where = "scalar";
  r.units = units;
  r.dtype = t;
  return r;
}

Result field(const std::string& name, const std::string& where,
             const std::string& units, DType t = DType::Float64) {
  Result r = scalar(name, units, t);
  r.where = where;
  return r;
}

std::vector<double> read_f64(const Reader& r, const std::string& path,
                             const Selection& rows = Selection::all(),
                             const Selection& sites = Selection::all()) {
  const auto shape = r.shape(path, rows, sites);
  std::int64_t n = 1;
  for (auto x : shape) n *= x;
  std::vector<double> out(static_cast<std::size_t>(n));
  r.read(path, rows, sites, DType::Float64, out.data(), out.size() * 8);
  return out;
}

std::vector<std::int64_t> read_i64(const Reader& r, const std::string& path,
                                   const Selection& rows = Selection::all(),
                                   const Selection& sites = Selection::all()) {
  const auto shape = r.shape(path, rows, sites);
  std::int64_t n = 1;
  for (auto x : shape) n *= x;
  std::vector<std::int64_t> out(static_cast<std::size_t>(n));
  r.read(path, rows, sites, DType::Int64, out.data(), out.size() * 8);
  return out;
}

// A quad grid of nx x ny nodes.
Geometry grid(int nx, int ny, double scale = 1.0, bool with_cells = true) {
  Geometry g;
  std::vector<double> pts;
  for (int j = 0; j < ny; ++j) {
    for (int i = 0; i < nx; ++i) {
      pts.push_back(i * scale);
      pts.push_back(j * scale);
    }
  }
  g.n_nodes = nx * ny;
  g.axes = 2;
  g.points = f64(pts);
  if (with_cells) {
    g.offsets.push_back(0);
    for (int j = 0; j + 1 < ny; ++j) {
      for (int i = 0; i + 1 < nx; ++i) {
        const std::int64_t a = j * nx + i;
        g.types.push_back(9);
        for (const std::int64_t v : {a, a + 1, a + nx + 1, a + nx}) g.connectivity.push_back(v);
        g.offsets.push_back(static_cast<std::int64_t>(g.connectivity.size()));
      }
    }
  }
  return g;
}

void test_table_run_at_a_time() {
  const std::string path = "wr_table.mes";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->set_attribute("title", "polar");
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_parameter(param("alpha", "condition", "degree"));
    w->declare_label("status", "status", {"converged", "failed"});
    w->declare_result(scalar("cl", "1"));
    w->declare_result(scalar("cd", "1", DType::Float32));
    mestra::internal::Constant c;
    c.name = "s_ref";
    c.units = "m2";
    c.f = 12.5;
    w->set_constant(c);
    for (int i = 0; i < 1000; ++i) {
      Batch b;
      b.runs = 1;
      b.values["mach"] = f64({0.3 + 0.001 * i});
      b.values["alpha"] = f64({static_cast<double>(i % 9)});
      b.names["status"] = {i % 100 == 99 ? "failed" : "converged"};
      b.values["cl"] = f64({0.1 * (i % 9)});
      if (i % 2 == 0) b.values["cd"] = f32({0.01f});   // odd runs leave cd missing
      CHECK(w->add_runs(b) == i);
    }
    w->close();
  }
  auto file_size = [&]() {
    FILE* fp = std::fopen(path.c_str(), "rb");
    std::fseek(fp, 0, SEEK_END);
    const long size = std::ftell(fp);
    std::fclose(fp);
    return size;
  };
  std::printf("table file after 1000 appends in one session: %ld bytes\n", file_size());
  {
    auto r = Reader::open(path);
    CHECK(r->schema().rows == 1000);
    CHECK(r->schema().type() == "table");
    CHECK(read_i64(*r, "row")[999] == 999);
    const auto mach = read_f64(*r, "mach", Selection::range(10, 12));
    CHECK(mach.size() == 2 && std::fabs(mach[0] - 0.31) < 1e-12);
    const auto cd = read_f64(*r, "cd", Selection::list({0, 1}));
    CHECK(cd[0] == static_cast<double>(0.01f) && std::isnan(cd[1]));
    const auto names = r->label_names("status", Selection::list({98, 99}));
    CHECK(names[0] == "converged" && names[1] == "failed");
    // The run table's chunk is the capped leading chunk, not one entry.
    const auto info = r->file().dataset_info("/cl");
    CHECK(info.chunked && info.chunk[0] == 512);
    CHECK(r->names("scalars") == std::vector<std::string>({"cd", "cl"}));
    bool constant_ok = false;
    for (const auto& kv : r->describe("s_ref")) constant_ok = constant_ok || (kv.first == "kind" && kv.second == "constant");
    CHECK(constant_ok);
  }
  // Reopen and append; ids continue.  Reopening per append keeps the file
  // at the size of its data (persistent free space).
  for (int k = 0; k < 50; ++k) {
    auto w = Writer::open_append(path);
    Batch b;
    b.runs = 1;
    b.values["mach"] = f64({0.9});
    b.values["alpha"] = f64({1.0});
    b.names["status"] = {"converged"};
    b.values["cl"] = f64({0.5});
    CHECK(w->add_runs(b) == 1000 + k);
    w->close();
    if (k == 0 || k == 9 || k == 49) std::printf("  after reopen %d: %ld bytes\n", k + 1, file_size());
  }
  {
    auto r = Reader::open(path);
    CHECK(r->schema().rows == 1050);
    CHECK(read_i64(*r, "row")[1049] == 1049);
    FILE* fp = std::fopen(path.c_str(), "rb");
    std::fseek(fp, 0, SEEK_END);
    const long size = std::ftell(fp);
    std::fclose(fp);
    std::printf("table file after 1000 + 50 reopened appends: %ld bytes\n", size);
    CHECK(size < 200000);
  }
  if (!std::getenv("MESTRA_KEEP")) std::remove(path.c_str());
}

void test_shared_fixed() {
  const std::string path = "wr_shared.mes";
  {
    auto w = Writer::create(path, "tests", "shared", "fixed");
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_coordinates("m", DType::Float64, 2);
    MeshLabel zone;
    zone.name = "zone";
    zone.where = "cell";
    w->declare_mesh_label(zone, {"inlet", "wall"});
    w->declare_result(field("p", "node", "Pa", DType::Float32));
    Result ux = field("u_x", "cell", "m s-1");
    ux.vector = "velocity";
    ux.axis = "x";
    Result uy = field("u_y", "cell", "m s-1");
    uy.vector = "velocity";
    uy.axis = "y";
    w->declare_result(ux);
    w->declare_result(uy);
    Geometry g = grid(4, 3);
    g.labels["zone"] = {0, 0, 0, 1, 1, 1};
    w->set_mesh(g);
    Batch b;
    b.runs = 6;
    b.values["mach"] = f64({0.1, 0.2, 0.3, 0.4, 0.5, 0.6});
    std::vector<float> p(6 * 12);
    for (std::size_t i = 0; i < p.size(); ++i) p[i] = static_cast<float>(i);
    b.values["p"] = f32(p);
    b.values["u_x"] = f64(std::vector<double>(36, 1.0));
    b.values["u_y"] = f64(std::vector<double>(36, 2.0));
    w->add_runs(b);
    w->close();
  }
  auto r = Reader::open(path);
  CHECK(r->schema().type() == "shared");
  CHECK(r->schema().mesh.n_nodes == 12 && r->schema().mesh.n_cells == 6);
  const auto region = read_f64(*r, "node_fields/p", Selection::all(), Selection::range(2, 4));
  CHECK(region.size() == 12 && region[0] == 2.0 && region[1] == 3.0 && region[2] == 14.0);
  const auto one = read_f64(*r, "node_fields/p", Selection::list({5}));
  CHECK(one.size() == 12 && one[11] == 71.0);
  // A buffer is a capacity: filled from the start, the rest left alone.
  std::vector<double> roomy(20, -1.0);
  r->read("node_fields/p", Selection::list({5}), Selection::range(0, 2), DType::Float64,
          roomy.data(), roomy.size() * sizeof(double));
  CHECK(roomy[0] == 60.0 && roomy[1] == 61.0 && roomy[2] == -1.0);
  double tight = 0.0;
  CHECK(!rule_of([&] {
           r->read("node_fields/p", Selection::list({5}), Selection::range(0, 2),
                   DType::Float64, &tight, sizeof tight);
         }).empty());
  const auto coords = read_f64(*r, "coordinates");
  CHECK(coords.size() == 24 && coords[2] == 1.0);
  const auto zone = read_i64(*r, "cell_labels/zone");
  CHECK(zone.size() == 6 && zone[3] == 1);
  const auto types = read_i64(*r, "cells/types");
  CHECK(types.size() == 6 && types[0] == 9);
  CHECK(r->schema().mesh.support_id.size() == 64);
  if (!std::getenv("MESTRA_KEEP")) std::remove(path.c_str());
}

void test_shared_per_group_out_of_order() {
  // R5-1: categories declared up front, runs arriving out of code order.
  const std::string path = "wr_group.mes";
  {
    auto w = Writer::create(path, "tests", "shared", "group:member");
    w->declare_label("member", "group", {"a", "b", "c"});
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_coordinates("m", DType::Float32, 2);
    w->declare_result(field("p", "node", "Pa"));
    Geometry cells = grid(3, 3);
    cells.points = Column();
    w->set_mesh(cells);
    Batch b;
    b.runs = 3;
    b.names["member"] = {"c", "c", "a"};
    b.values["mach"] = f64({5, 8, 5});
    b.values["p"] = f64(std::vector<double>(27, 1.0));
    Geometry gc = grid(3, 3, 3.0, false);
    Geometry ga = grid(3, 3, 1.0, false);
    b.member_geometry["c"] = gc;
    b.member_geometry["a"] = ga;
    w->add_runs(b);
    w->close();
  }
  {
    auto w = Writer::open_append(path);
    Batch b;
    b.runs = 2;
    b.names["member"] = {"a", "b"};
    b.values["mach"] = f64({8, 5});
    b.member_geometry["b"] = grid(3, 3, 2.0, false);
    w->add_runs(b);   // p missing: NaN
    w->close();
  }
  auto r = Reader::open(path);
  CHECK(r->schema().rows == 5);
  CHECK(r->schema().mesh.n_instances == 3);
  CHECK(read_i64(*r, "row").size() == 5);
  // Row 0 is member c, whose geometry is scaled by 3; row 2 is member a.
  const auto c0 = read_f64(*r, "coordinates", Selection::list({0}));
  const auto c2 = read_f64(*r, "coordinates", Selection::list({2}));
  const auto c4 = read_f64(*r, "coordinates", Selection::list({4}));
  CHECK(c0.size() == 18 && c0[2] == 3.0 && c2[2] == 1.0 && c4[2] == 2.0);
  const auto both = read_f64(*r, "coordinates", Selection::list({1, 3}));
  CHECK(both.size() == 36 && both[2] == 3.0 && both[18 + 2] == 1.0);
  const auto p = read_f64(*r, "node_fields/p", Selection::list({4}));
  CHECK(std::isnan(p[0]));
  if (!std::getenv("MESTRA_KEEP")) std::remove(path.c_str());
}

void test_changing_per_run_and_group() {
  const std::string path = "wr_changing.mes";
  {
    auto w = Writer::create(path, "tests", "changing", "group:member");
    w->declare_label("member", "group", {});
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_coordinates("m", DType::Float64, 2);
    MeshLabel patch;
    patch.name = "patch";
    patch.where = "cell";
    w->declare_mesh_label(patch, {});
    w->declare_result(field("p", "node", "Pa"));
    w->declare_result(field("t", "cell", "K"));
    Batch b;
    b.runs = 3;
    b.names["member"] = {"big", "small", "big"};
    b.values["mach"] = f64({1, 2, 3});
    Geometry big = grid(4, 4);
    big.labels["patch"] = std::vector<std::int64_t>(9, 7);
    Geometry small = grid(2, 2);
    small.labels["patch"] = {3};
    b.member_geometry["big"] = big;
    b.member_geometry["small"] = small;
    std::vector<double> p;
    for (int i = 0; i < 16; ++i) p.push_back(i);
    for (int i = 0; i < 4; ++i) p.push_back(100 + i);
    for (int i = 0; i < 16; ++i) p.push_back(200 + i);
    b.values["p"] = f64(p);
    b.values["t"] = f64(std::vector<double>(9 + 1 + 9, 300.0));
    w->add_runs(b);
    w->close();
  }
  auto r = Reader::open(path);
  CHECK(r->schema().type() == "changing");
  const auto p1 = read_f64(*r, "node_fields/p", Selection::list({1}));
  CHECK(p1.size() == 4 && p1[0] == 100.0);
  const auto p2 = read_f64(*r, "node_fields/p", Selection::list({2}), Selection::range(3, 5));
  CHECK(p2.size() == 2 && p2[0] == 203.0);
  const auto conn = read_i64(*r, "cells/connectivity", Selection::list({1}));
  CHECK(conn.size() == 4 && conn[2] == 3);
  const auto offs = read_i64(*r, "cells/offsets", Selection::list({2}));
  CHECK(offs.size() == 10 && offs[0] == 0 && offs[9] == 36);
  const auto patch = read_i64(*r, "cell_labels/patch", Selection::list({1}));
  CHECK(patch.size() == 1 && patch[0] == 3);
  // Across runs is a shared-mesh operation.
  CHECK(!rule_of([&] { read_f64(*r, "node_fields/p"); }).empty());
  if (!std::getenv("MESTRA_KEEP")) std::remove(path.c_str());
}

void test_refusals() {
  const std::string path = "wr_refuse.mes";
  auto w = Writer::create(path, "tests", "shared", "fixed");
  w->declare_parameter(param("mach", "condition", "1"));
  CHECK(rule_of([&] { w->declare_parameter(param("bad name", "design", "1")); }) == "E8");
  CHECK(rule_of([&] { w->declare_parameter(param("x", "design", "m//s")); }) == "E7");
  CHECK(rule_of([&] { w->declare_parameter(param("row", "design", "1")); }) == "E8");
  w->declare_result(scalar("p", "Pa"));
  CHECK(rule_of([&] { w->declare_result(field("p", "node", "Pa")); }) == "E8");
  Result q = field("q", "node", "Pa");
  q.relation.statistic = "quantile";
  q.relation.of = "p_field";
  CHECK(rule_of([&] { w->declare_result(q); }) == "E12");   // no q
  CHECK(rule_of([] { Writer::create("wr_bad.mes", "t", "changing", "fixed"); }) == "E6");
  w.reset();
  if (!std::getenv("MESTRA_KEEP")) std::remove(path.c_str());
  std::remove("wr_bad.mes");
}

}  // namespace

int main() {
  const std::vector<std::pair<const char*, std::function<void()>>> tests = {
      {"table", test_table_run_at_a_time},
      {"shared_fixed", test_shared_fixed},
      {"shared_group", test_shared_per_group_out_of_order},
      {"changing", test_changing_per_run_and_group},
      {"refusals", test_refusals},
  };
  for (const auto& t : tests) {
    try {
      t.second();
    } catch (const mestra::Error& e) {
      ++g_failures;
      std::fprintf(stderr, "%s: unexpected error %s: %s\n", t.first, e.rule().c_str(), e.what());
    } catch (const std::exception& e) {
      ++g_failures;
      std::fprintf(stderr, "%s: unexpected exception: %s\n", t.first, e.what());
    }
  }
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
