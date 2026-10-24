// Writer and reader of the core, end to end on real files: every file type,
// appends in one session and across reopenings, and refusals by rule.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iterator>
#include <string>
#include <vector>

#include <hdf5.h>
#include <hdf5_hl.h>
#include <zlib.h>

#include "chunk.hpp"
#include "h5.hpp"
#include "reader.hpp"
#include "types.hpp"
#include "validate.hpp"
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
  } catch (const gamut_core::Error& e) {
    return e.rule().empty() ? std::string("error") : e.rule();
  }
  return std::string();
}

using gamut_core::AttrValue;
using gamut_core::DType;
using gamut_core::FilterStep;
using gamut_core::Selection;
using namespace gamut_core::internal;

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
  const std::string path = "wr_table.gamut";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->set_attribute("title", "polar");
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_parameter(param("alpha", "condition", "degree"));
    w->declare_label("status", "status", {"converged", "failed"});
    w->declare_result(scalar("cl", "1"));
    w->declare_result(scalar("cd", "1", DType::Float32));
    gamut_core::internal::Constant c;
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
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

void test_shared_fixed() {
  const std::string path = "wr_shared.gamut";
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
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

void test_shared_per_group_out_of_order() {
  // R5-1: categories declared up front, runs arriving out of code order.
  const std::string path = "wr_group.gamut";
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
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

void test_changing_per_run_and_group() {
  const std::string path = "wr_changing.gamut";
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
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

void test_refusals() {
  const std::string path = "wr_refuse.gamut";
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
  CHECK(rule_of([] { Writer::create("wr_bad.gamut", "t", "changing", "fixed"); }) == "E6");
  CHECK(rule_of([] { Writer::create("wr_bad.gamut", "t", "shared", ""); }) == "E6");   // a mesh needs per
  w.reset();
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
  std::remove("wr_bad.gamut");
}

// How far each row lies outside its parameter's bounds: zero inside and on
// a bound, the signed distance past the bound outside, NaN for a missing
// value.  A parameter without bounds, or with bounds the validator rejects,
// is refused rather than reported as inside; so are other names and bad
// selections.
// An int64 parameter is measured as an integer: as a double it loses bits
// past 2^53, which would mark a row one past its bound as inside.
void test_outside_large_integers() {
  const std::string path = "wr_bounds_int.gamut";
  const std::int64_t big = std::int64_t(1) << 53;
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    auto declare = [&](const char* name, double lower, double upper) {
      Parameter p = param(name, "design", "1");
      p.dtype = DType::Int64;
      p.lower = lower;
      p.upper = upper;
      w->declare_parameter(p);
    };
    const double top = 9223372036854775808.0;   // 2^63, past every int64
    declare("up", static_cast<double>(big), static_cast<double>(big));
    declare("down", -static_cast<double>(big), -static_cast<double>(big));
    declare("half", 0.5, 10.0);
    declare("edge", top, top + 2048);
    declare("floor", -top - 2048, -top - 2048);
    declare("tiny", -1e-20, -1e-20);
    declare("tenth", -0.1, -0.1);
    declare("gap", 0.5, 0.5);
    const std::int64_t max = INT64_MAX, min = INT64_MIN;
    const std::vector<std::int64_t> up = {big - 1, big, big + 1, big + 3};
    const std::vector<std::int64_t> down = {-big - 3, -big, -big + 1, -big};
    const std::vector<std::int64_t> half = {0, 1, 10, 11};
    const std::vector<std::int64_t> edge = {max, max - 1, 0, max};
    const std::vector<std::int64_t> floor = {min + 1, min, 0, min + 1};
    const std::vector<std::int64_t> tiny = {0, -1, 0, 1};
    const std::vector<std::int64_t> tenth = {0, 0, 0, 0};
    const std::vector<std::int64_t> gap = {big + 3, 0, 1, big + 3};
    Batch b;
    b.runs = 4;
    b.values["up"] = Column::of(DType::Int64, up.data(), 4);
    b.values["down"] = Column::of(DType::Int64, down.data(), 4);
    b.values["half"] = Column::of(DType::Int64, half.data(), 4);
    b.values["edge"] = Column::of(DType::Int64, edge.data(), 4);
    b.values["floor"] = Column::of(DType::Int64, floor.data(), 4);
    b.values["tiny"] = Column::of(DType::Int64, tiny.data(), 4);
    b.values["tenth"] = Column::of(DType::Int64, tenth.data(), 4);
    b.values["gap"] = Column::of(DType::Int64, gap.data(), 4);
    w->add_runs(b);
    w->close();
  }
  auto r = Reader::open(path);
  auto outside = [&](const std::string& name) {
    std::vector<double> out(4);
    r->outside(name, Selection::all(), out.data(), out.size() * sizeof(double));
    return out;
  };
  CHECK(outside("up") == std::vector<double>({-1, 0, 1, 3}));
  CHECK(outside("down") == std::vector<double>({-3, 0, 1, 0}));
  CHECK(outside("half") == std::vector<double>({-0.5, 0, 0, 1}));
  // Bounds past every int64, and fractions far below one.
  CHECK(outside("edge") == std::vector<double>({-1, -2, -9223372036854775808.0, -1}));
  CHECK(outside("floor") == std::vector<double>({2049, 2048, 9223372036854777856.0, 2049}));
  CHECK(outside("tiny") == std::vector<double>({1e-20, -1 + 1e-20, 1e-20, 1 + 1e-20}));
  CHECK(outside("tenth") == std::vector<double>({0.1, 0.1, 0.1, 0.1}));
  // A large gap from a fractional bound: 2^53 + 3 - 0.5 lies between the
  // doubles 2^53 + 2 and 2^53 + 4, nearer the first.
  CHECK(outside("gap") == std::vector<double>({9007199254740994.0, -0.5, 0.5, 9007199254740994.0}));
  // A buffer larger than the selection is filled as far as it needs, as
  // every read does; an empty selection writes nothing.
  std::vector<double> roomy(6, 7.0);
  r->outside("up", Selection::all(), roomy.data(), roomy.size() * sizeof(double));
  CHECK(roomy[2] == 1 && roomy[4] == 7.0 && roomy[5] == 7.0);
  r->outside("up", Selection::range(1, 1), roomy.data(), roomy.size() * sizeof(double));
  CHECK(roomy[0] == -1);
  r.reset();
  std::remove(path.c_str());
}

void test_outside_bounds() {
  const std::string path = "wr_bounds.gamut";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    Parameter x = param("x", "design", "m");
    x.lower = 0.0;
    x.upper = 1.0;
    w->declare_parameter(x);
    Parameter n = param("n", "design", "1");
    n.dtype = DType::Int64;
    n.lower = 2.0;
    n.upper = 4.0;
    w->declare_parameter(n);
    w->declare_parameter(param("mach", "condition", "1"));
    w->declare_result(scalar("cl", "1"));
    const std::vector<std::int64_t> counts = {1, 2, 3, 4, 5, 6};
    Batch b;
    b.runs = 6;
    b.values["x"] = f64({-0.5, 0.0, 0.25, 1.0, 1.5, 0.5});
    b.values["n"] = Column::of(DType::Int64, counts.data(), 6);
    b.values["mach"] = f64({0.1, 0.2, 0.3, 0.4, 0.5, 0.6});
    b.values["cl"] = f64({0, 0, 0, 0, 0, 0});
    w->add_runs(b);
    w->close();
  }
  {
    // The writer never stores a missing parameter (E5); a file may hold one.
    File f = File::open_write(path);
    const double missing = std::nan("");
    f.write("/x", DType::Float64, {5}, {1}, &missing);
  }
  auto r = Reader::open(path);
  auto outside = [&](const std::string& name, const Selection& rows) {
    std::vector<double> out(static_cast<std::size_t>(r->shape(name, rows, Selection::all()).at(0)));
    r->outside(name, rows, out.data(), out.size() * sizeof(double));
    return out;
  };
  const auto x = outside("x", Selection::all());
  CHECK(x.size() == 6 && x[0] == -0.5 && x[1] == 0.0 && x[2] == 0.0 && x[3] == 0.0 &&
        x[4] == 0.5 && std::isnan(x[5]));
  CHECK(outside("x", Selection::list({0, 4})) == std::vector<double>({-0.5, 0.5}));
  CHECK(outside("x", Selection::range(1, 4)) == std::vector<double>({0.0, 0.0, 0.0}));
  CHECK(outside("x", Selection::range(2, 2)).empty());
  CHECK(outside("n", Selection::all()) == std::vector<double>({-1, 0, 0, 0, 1, 2}));
  double buf[8] = {};
  auto refused = [&](const std::string& name, const Selection& rows, std::size_t bytes) {
    try {
      r->outside(name, rows, buf, bytes);
    } catch (const gamut_core::Error& e) {
      return (e.rule().empty() ? std::string("error") : e.rule()) + ": " + e.what();
    }
    return std::string();
  };
  CHECK(refused("mach", Selection::all(), sizeof buf).find("mach declares no bounds") !=
        std::string::npos);
  CHECK(refused("cl", Selection::all(), sizeof buf).find("no parameter \"cl\"") != std::string::npos);
  CHECK(refused("nothing", Selection::all(), sizeof buf).find("no parameter") != std::string::npos);
  CHECK(refused("x", Selection::list({6}), sizeof buf).find("outside the 6 positions") !=
        std::string::npos);
  CHECK(refused("x", Selection::list({3, 1}), sizeof buf).find("strictly increasing") !=
        std::string::npos);
  CHECK(refused("x", Selection::range(4, 9), sizeof buf).find("outside the 6 positions") !=
        std::string::npos);
  CHECK(refused("x", Selection::all(), sizeof(double)).find("the buffer holds 8 bytes") !=
        std::string::npos);
  r.reset();
  {
    File f = File::open_write(path);
    f.replace_attr("/x", "upper", AttrValue::real(-1.0));     // below lower
    f.replace_attr("/n", "upper", AttrValue::text("4"));      // a bound that is not a number
  }
  r = Reader::open(path);
  CHECK(refused("x", Selection::all(), sizeof buf).compare(0, 5, "E16: ") == 0);
  CHECK(refused("n", Selection::all(), sizeof buf).compare(0, 5, "E16: ") == 0);
  r.reset();
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

std::string file_bytes(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

// A file of another major format version is refused by reading and by
// appending alike (spec section 17), and appending changes nothing first.
void test_other_major_version() {
  const std::string path = "wr_major.gamut";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->declare_result(scalar("cl", "1"));
    w->close();
  }
  {
    File f = File::open_write(path);
    f.replace_attr("/", "format", AttrValue::text("gamut/2"));
  }
  const std::string before = file_bytes(path);
  CHECK(rule_of([&] { Reader::open(path); }) == "E1");
  CHECK(rule_of([&] { Writer::open_append(path); }) == "E1");
  CHECK(file_bytes(path) == before);
  std::remove(path.c_str());
}

bool exists(const std::string& path) { return std::ifstream(path).good(); }

void detach_row_scale(const File& f, const char* path) {
  const hid_t d = H5Dopen2(f.get(), path, H5P_DEFAULT);
  const hid_t row = H5Dopen2(f.get(), "/row", H5P_DEFAULT);
  CHECK(H5DSdetach_scale(d, row, 0) >= 0);
  H5Dclose(row);
  H5Dclose(d);
}

// A table whose scalar result keeps its values in a file outside it
// (HDF5 external storage), as a crafted file could: nothing reads that
// file, and appending neither creates nor changes it, nor the table.
void test_values_stored_outside() {
  const std::string path = "wr_outside.gamut";
  const std::string outside = "wr_outside.raw";
  std::remove(outside.c_str());
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->declare_parameter(param("x", "design", "1"));
    w->declare_result(scalar("y", "1"));
    w->close();
  }
  {
    File f = File::open_write(path);
    detach_row_scale(f, "/y");
    CHECK(H5Ldelete(f.get(), "/y", H5P_DEFAULT) >= 0);
    const hsize_t zero = 0, unlimited = H5S_UNLIMITED;
    const hid_t space = H5Screate_simple(1, &zero, &unlimited);
    const hid_t dcpl = H5Pcreate(H5P_DATASET_CREATE);
    H5Pset_external(dcpl, outside.c_str(), 0, H5F_UNLIMITED);
    const hid_t d = H5Dcreate2(f.get(), "/y", H5T_IEEE_F64LE, space, H5P_DEFAULT, dcpl,
                               H5P_DEFAULT);
    CHECK(d >= 0);
    const hid_t row = H5Dopen2(f.get(), "/row", H5P_DEFAULT);
    CHECK(H5DSattach_scale(d, row, 0) >= 0);
    H5Dclose(row);
    H5Dclose(d);
    H5Pclose(dcpl);
    H5Sclose(space);
    f.write_attr("/y", "role", AttrValue::text("scalar"));
    f.write_attr("/y", "units", AttrValue::text("1"));
  }
  const std::string before = file_bytes(path);
  CHECK(rule_of([&] { Writer::open_append(path); }) == "E22");
  CHECK(file_bytes(path) == before);
  CHECK(!exists(outside));
  const Report report = validate_file(path);
  bool e22 = false;
  for (const auto& finding : report.findings) e22 = e22 || finding.rule == "E22";
  CHECK(e22);
  CHECK(rule_of([&] { Reader::open(path); }) == "E22");
  CHECK(!exists(outside));
  std::remove(path.c_str());
}

// The validator looks for values stored outside the file under /private
// too, since copying a file reads its private records.
void test_private_values_stored_outside() {
  const std::string path = "wr_outside_private.gamut";
  const std::string outside = "wr_outside_private.raw";
  std::remove(outside.c_str());
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->declare_parameter(param("x", "design", "1"));
    w->close();
  }
  {
    File f = File::open_write(path);
    const hid_t g = H5Gcreate2(f.get(), "/private", H5P_DEFAULT, H5P_DEFAULT, H5P_DEFAULT);
    const hsize_t four = 4;
    const hid_t space = H5Screate_simple(1, &four, nullptr);
    const hid_t dcpl = H5Pcreate(H5P_DATASET_CREATE);
    H5Pset_external(dcpl, outside.c_str(), 0, H5F_UNLIMITED);
    const hid_t d = H5Dcreate2(g, "record", H5T_STD_U8LE, space, H5P_DEFAULT, dcpl, H5P_DEFAULT);
    CHECK(d >= 0);
    H5Dclose(d);
    H5Pclose(dcpl);
    H5Sclose(space);
    H5Gclose(g);
  }
  bool e22 = false;
  for (const auto& finding : validate_file(path).findings) {
    e22 = e22 || (finding.rule == "E22" && finding.path.find("private") != std::string::npos);
  }
  CHECK(e22);
  CHECK(!exists(outside));
  std::remove(path.c_str());
}

// A run-table column grows with each run, so appending refuses one that
// cannot grow (E20) before writing anything.
void test_append_needs_growable_columns() {
  const std::string path = "wr_fixed.gamut";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->declare_result(scalar("y", "1"));
    w->close();
  }
  {
    File f = File::open_write(path);
    detach_row_scale(f, "/y");
    CHECK(H5Ldelete(f.get(), "/y", H5P_DEFAULT) >= 0);
    f.create_dataset("/y", DType::Float64, 0, {0}, {0}, {}, {});
    const hid_t d = H5Dopen2(f.get(), "/y", H5P_DEFAULT);
    const hid_t row = H5Dopen2(f.get(), "/row", H5P_DEFAULT);
    CHECK(H5DSattach_scale(d, row, 0) >= 0);
    H5Dclose(row);
    H5Dclose(d);
    f.write_attr("/y", "role", AttrValue::text("scalar"));
    f.write_attr("/y", "units", AttrValue::text("1"));
  }
  const std::string before = file_bytes(path);
  CHECK(rule_of([&] { Writer::open_append(path); }) == "E20");
  CHECK(file_bytes(path) == before);
  std::remove(path.c_str());
}

// The threaded reader given more selections than a dataset has axes falls
// back to the serial read, which refuses it, rather than index past them.
void test_threaded_read_of_fewer_axes() {
  const std::string path = "wr_rank.gamut";
  {
    File f = File::create(path);
    f.create_dataset("/x", DType::Float64, 0, {16}, {H5S_UNLIMITED}, {4}, {});
    const std::vector<double> x(16, 1.0);
    f.write("/x", DType::Float64, {0}, {16}, x.data());
  }
  const File f = File::open_read(path);
  double out[4] = {0, 0, 0, 0};
  const std::vector<Selection> two = {Selection::all(), Selection::range(0, 1)};
  CHECK(!rule_of([&] { f.read("/x", DType::Float64, two, out, sizeof out, 4); }).empty());
  CHECK(!rule_of([&] { f.read("/x", DType::Float64, two, out, sizeof out); }).empty());
  std::remove(path.c_str());
}

// A read is refused before any buffer is sized when it would return more
// than 2^30 values (8 GiB at 8 bytes a value), however few are stored.
void test_read_limit_before_allocation() {
  const std::string path = "wr_huge.gamut";
  {
    auto w = Writer::create(path, "tests", "", "fixed");
    w->declare_result(scalar("y", "1"));
    w->close();
  }
  {
    File f = File::open_write(path);
    f.set_extent("/row", {(hsize_t(1) << 30) + 1});
    f.set_extent("/y", {(hsize_t(1) << 30) + 1});
  }
  const auto r = Reader::open(path);
  CHECK(rule_of([&] { r->shape("y", Selection::all(), Selection::all()); }) == "E23");
  CHECK(r->shape("y", Selection::range(0, 8), Selection::all()) ==
        std::vector<std::int64_t>{8});
  std::remove(path.c_str());
}

// An unfiltered chunk stored in fewer bytes than it holds, as a damaged
// filter message leaves a compressed one: reading or writing it is refused
// rather than letting HDF5 read past its buffer.
void test_short_unfiltered_chunk() {
  const std::string path = "wr_short_chunk.gamut";
  {
    // Three chunks of four; the middle one stored in 20 bytes, not 32.
    File f = File::create(path);
    f.create_dataset("/x", DType::Float64, 0, {12}, {H5S_UNLIMITED}, {4}, {});
    const hid_t d = H5Dopen2(f.get(), "/x", H5P_DEFAULT);
    const hsize_t origin = 4;
    const unsigned char bytes[20] = {};
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 0, &origin, sizeof bytes, bytes) >= 0);
    H5Dclose(d);
  }
  {
    const File f = File::open_read(path);
    double out[12] = {};
    CHECK(rule_of([&] { f.read("/x", DType::Float64, {}, out, sizeof out); }) == "E23");
    CHECK(rule_of([&] {
            f.read("/x", DType::Float64, {}, out, sizeof out, 4);
          }) == "E23");
    // Chunks never written read as zeros, and positions 0 and 11 touch only
    // the first and last chunks.
    CHECK(rule_of([&] {
            f.read("/x", DType::Float64, {Selection::range(8, 12)}, out, 4 * sizeof(double));
          }).empty());
    CHECK(rule_of([&] {
            f.read("/x", DType::Float64, {Selection::list({0, 11})}, out, 2 * sizeof(double));
          }).empty());
  }
  {
    File f = File::open_write(path);
    const double one[2] = {1.0, 2.0};
    CHECK(rule_of([&] { f.write("/x", DType::Float64, {5}, {2}, one); }) == "E23");
    CHECK(rule_of([&] { f.write("/x", DType::Float64, {9}, {2}, one); }).empty());
  }
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}


// --- the core's own reading of chunked datasets ------------------------

// One selection per axis: everything, an inner range, or scattered points.
Selection axis_selection(int kind, hsize_t length) {
  const auto n = static_cast<std::int64_t>(length);
  if (kind == 1) return Selection::range(1, n - 1);
  if (kind == 2) return Selection::list(n > 2 ? std::vector<std::int64_t>{0, 2, n - 1}
                                              : std::vector<std::int64_t>{0});
  return Selection::all();
}

// HDF5's own read of `sel`: the reference the core's chunk reading must
// give byte for byte.
std::vector<unsigned char> hdf5_read(hid_t file, const char* name, hid_t mem, std::size_t size,
                                     const std::vector<hsize_t>& shape,
                                     const std::vector<Selection>& sel) {
  const hid_t d = H5Dopen2(file, name, H5P_DEFAULT);
  const hid_t space = H5Dget_space(d);
  const std::size_t rank = shape.size();
  std::vector<std::vector<std::pair<std::int64_t, std::int64_t>>> runs(rank);
  std::vector<hsize_t> count(rank);
  std::size_t n = 1;
  for (std::size_t a = 0; a < rank; ++a) {
    runs[a] = sel[a].runs(static_cast<std::int64_t>(shape[a]), name);
    count[a] = static_cast<hsize_t>(sel[a].count(static_cast<std::int64_t>(shape[a]), name));
    n *= static_cast<std::size_t>(count[a]);
  }
  std::vector<std::size_t> at(rank, 0);
  std::vector<hsize_t> start(rank), block(rank);
  bool first = true;
  while (true) {
    for (std::size_t a = 0; a < rank; ++a) {
      start[a] = static_cast<hsize_t>(runs[a][at[a]].first);
      block[a] = static_cast<hsize_t>(runs[a][at[a]].second);
    }
    H5Sselect_hyperslab(space, first ? H5S_SELECT_SET : H5S_SELECT_OR, start.data(), nullptr,
                        block.data(), nullptr);
    first = false;
    std::size_t a = rank;
    bool done = true;
    while (a > 0) {
      --a;
      if (++at[a] < runs[a].size()) {
        done = false;
        break;
      }
      at[a] = 0;
    }
    if (done) break;
  }
  const hid_t memspace = H5Screate_simple(static_cast<int>(rank), count.data(), nullptr);
  std::vector<unsigned char> out(n * size);
  CHECK(H5Dread(d, mem, memspace, space, H5P_DEFAULT, out.data()) >= 0);
  H5Sclose(memspace);
  H5Sclose(space);
  H5Dclose(d);
  return out;
}

// Every read the core makes of a chunked dataset equals HDF5's: element
// types big- and little-endian, each filter combination, a user fill
// value and chunks never written, edge chunks, one to three axes, ranges
// and scattered points, conversions (narrowing too), one and four threads.
void test_chunk_reads_equal_hdf5() {
  const std::string path = "wr_chunk_reads.gamut";
  struct Case {
    const char* name;
    hid_t type;
    std::vector<hsize_t> shape, chunk;
    int filters;   // 0 none, 1 shuffle and gzip, 2 gzip, 3 shuffle, 4 gzip then shuffle
    bool fill;
    hsize_t written;   // rows written along the first axis; the rest never are
  };
  const std::vector<Case> cases = {
      {"/a", H5T_IEEE_F64LE, {37}, {8}, 1, false, 37},
      {"/b", H5T_IEEE_F32LE, {37}, {8}, 2, true, 30},
      {"/c", H5T_STD_I32LE, {37}, {5}, 3, false, 37},
      {"/d", H5T_IEEE_F64BE, {9, 13}, {4, 5}, 1, true, 7},
      {"/e", H5T_STD_I64LE, {9, 13}, {4, 5}, 4, false, 9},
      {"/f", H5T_IEEE_F64LE, {5, 4, 6}, {2, 3, 4}, 1, false, 3},
      {"/g", H5T_STD_U8LE, {5, 4, 6}, {2, 3, 4}, 2, true, 5},
      {"/h", H5T_IEEE_F64LE, {9, 13}, {4, 5}, 0, true, 6},
  };
  {
    File f = File::create(path);
    for (const Case& c : cases) {
      const int rank = static_cast<int>(c.shape.size());
      const hid_t space = H5Screate_simple(rank, c.shape.data(), nullptr);
      const hid_t dcpl = H5Pcreate(H5P_DATASET_CREATE);
      H5Pset_chunk(dcpl, rank, c.chunk.data());
      if (c.filters == 1 || c.filters == 3) H5Pset_shuffle(dcpl);
      if (c.filters == 1 || c.filters == 2 || c.filters == 4) H5Pset_deflate(dcpl, 1);
      if (c.filters == 4) H5Pset_shuffle(dcpl);
      if (c.fill) {
        const double fill = -7.0;
        H5Pset_fill_value(dcpl, H5T_NATIVE_DOUBLE, &fill);
      }
      const hid_t d = H5Dcreate2(f.get(), c.name, c.type, space, H5P_DEFAULT, dcpl, H5P_DEFAULT);
      CHECK(d >= 0);
      std::vector<hsize_t> count = c.shape;
      count[0] = c.written;
      std::size_t n = 1;
      for (const hsize_t x : count) n *= static_cast<std::size_t>(x);
      std::vector<double> values(n);
      for (std::size_t i = 0; i < n; ++i) values[i] = static_cast<double>((i * 37) % 251) - 60.5;
      const std::vector<hsize_t> start(c.shape.size(), 0);
      const hid_t fs = H5Dget_space(d);
      H5Sselect_hyperslab(fs, H5S_SELECT_SET, start.data(), nullptr, count.data(), nullptr);
      const hid_t ms = H5Screate_simple(rank, count.data(), nullptr);
      CHECK(H5Dwrite(d, H5T_NATIVE_DOUBLE, ms, fs, H5P_DEFAULT, values.data()) >= 0);
      H5Sclose(ms);
      H5Sclose(fs);
      H5Dclose(d);
      H5Pclose(dcpl);
      H5Sclose(space);
    }
  }
  const File f = File::open_read(path);
  const std::vector<DType> mems = {DType::Float64, DType::Float32, DType::Int64, DType::Int32};
  for (const Case& c : cases) {
    const std::size_t rank = c.shape.size();
    std::size_t combos = 1;
    for (std::size_t a = 0; a < rank; ++a) combos *= 3;
    for (std::size_t k = 0; k < combos; ++k) {
      std::vector<Selection> sel;
      std::size_t code = k;
      for (std::size_t a = 0; a < rank; ++a) {
        sel.push_back(axis_selection(static_cast<int>(code % 3), c.shape[a]));
        code /= 3;
      }
      for (const DType mem : mems) {
        const std::vector<unsigned char> want =
            hdf5_read(f.get(), c.name, memory_type(mem), dtype_size(mem), c.shape, sel);
        for (const int threads : {1, 4}) {
          std::vector<unsigned char> got(want.size(), 0xAB);
          const std::string rule = rule_of(
              [&] { f.read(c.name, mem, sel, got.data(), got.size(), threads); });
          CHECK(rule.empty());
          CHECK(got == want);
          if (!rule.empty() || got != want) {
            std::fprintf(stderr, "  %s, selection %zu, mem %d, %d threads\n", c.name, k,
                         static_cast<int>(mem), threads);
          }
        }
      }
    }
  }
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

// A dataset of more chunks than one batch: four threads read what one does.
void test_threaded_reads_across_batches() {
  const std::string path = "wr_batches.gamut";
  std::vector<double> x(3001);
  for (std::size_t i = 0; i < x.size(); ++i) x[i] = std::sin(static_cast<double>(i));
  {
    File f = File::create(path);
    f.create_dataset("/x", DType::Float64, 0, {3001}, {H5S_UNLIMITED}, {8},
                     {FilterStep::shuffle(), FilterStep::gzip(1)});
    f.write("/x", DType::Float64, {0}, {3001}, x.data());
  }
  const File f = File::open_read(path);
  std::vector<double> one(x.size()), four(x.size());
  f.read("/x", DType::Float64, {}, one.data(), one.size() * 8, 1);
  f.read("/x", DType::Float64, {}, four.data(), four.size() * 8, 4);
  CHECK(one == x);
  CHECK(four == x);
  std::remove(path.c_str());
}

// Writes and reads in one open file: the core keeps what it knows of the
// stored chunks current as the dataset grows and chunks are rewritten.
void test_reads_after_writes_in_one_file() {
  const std::string path = "wr_grow.gamut";
  File f = File::create(path);
  f.create_dataset("/x", DType::Float64, 0, {0}, {H5S_UNLIMITED}, {4},
                   {FilterStep::shuffle(), FilterStep::gzip(1)});
  std::vector<double> want;
  for (int step = 0; step < 6; ++step) {
    const double add[3] = {step + 0.25, step + 0.5, step + 0.75};
    f.set_extent("/x", {want.size() + 3});
    f.write("/x", DType::Float64, {want.size()}, {3}, add);
    want.insert(want.end(), add, add + 3);
    std::vector<double> got(want.size());
    f.read("/x", DType::Float64, {}, got.data(), got.size() * 8);
    CHECK(got == want);
  }
  std::remove(path.c_str());
}

std::vector<unsigned char> zlib_of(std::size_t zeros) {
  std::vector<unsigned char> plain(zeros, 0), out(compressBound(static_cast<uLong>(zeros)));
  uLongf n = static_cast<uLongf>(out.size());
  compress2(out.data(), &n, plain.data(), static_cast<uLong>(plain.size()), 1);
  out.resize(n);
  return out;
}

// A compressed chunk that does not decode to a whole chunk is refused
// (E23) on a read, serial or threaded, and before a write rewrites it,
// where HDF5 would read or write past its buffer; the other chunks read
// and write as before.
void test_compressed_chunks_that_decode_short() {
  const std::string path = "wr_short_inflate.gamut";
  std::vector<double> x(16);
  for (std::size_t i = 0; i < x.size(); ++i) x[i] = static_cast<double>(i) + 0.5;
  {
    File f = File::create(path);
    f.create_dataset("/x", DType::Float64, 0, {16}, {H5S_UNLIMITED}, {4},
                     {FilterStep::shuffle(), FilterStep::gzip(1)});
    f.write("/x", DType::Float64, {0}, {16}, x.data());
    const hid_t d = H5Dopen2(f.get(), "/x", H5P_DEFAULT);
    // Chunk 1 inflates to 16 bytes of its 32; chunk 2 to 64; chunk 3 is
    // not a zlib stream at all.
    const std::vector<unsigned char> short_chunk = zlib_of(16), long_chunk = zlib_of(64);
    const unsigned char junk[24] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
    const hsize_t at1 = 4, at2 = 8, at3 = 12;
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 0, &at1, short_chunk.size(), short_chunk.data()) >= 0);
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 0, &at2, long_chunk.size(), long_chunk.data()) >= 0);
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 0, &at3, sizeof junk, junk) >= 0);
    H5Dclose(d);
  }
  {
    const File f = File::open_read(path);
    double out[16] = {};
    for (const int threads : {1, 4}) {
      CHECK(rule_of([&] { f.read("/x", DType::Float64, {}, out, sizeof out, threads); }) ==
            "E23");
    }
    for (const std::int64_t at : {4, 8, 12}) {
      CHECK(rule_of([&] {
              f.read("/x", DType::Float64, {Selection::range(at, at + 1)}, out, 8);
            }) == "E23");
    }
    CHECK(rule_of([&] { f.read("/x", DType::Float64, {Selection::range(0, 4)}, out, 32); })
              .empty());
    CHECK(out[0] == 0.5 && out[3] == 3.5);
  }
  {
    File f = File::open_write(path);
    const double two[2] = {1.0, 2.0};
    CHECK(rule_of([&] { f.write("/x", DType::Float64, {5}, {2}, two); }) == "E23");
    CHECK(rule_of([&] { f.write("/x", DType::Float64, {1}, {2}, two); }).empty());
  }
  if (!std::getenv("GAMUT_KEEP")) std::remove(path.c_str());
}

// A chunk written with every filter skipped is stored whole, or refused.
void test_chunk_with_filters_skipped() {
  const std::string path = "wr_skipped.gamut";
  {
    File f = File::create(path);
    f.create_dataset("/x", DType::Float64, 0, {8}, {H5S_UNLIMITED}, {4},
                     {FilterStep::shuffle(), FilterStep::gzip(1)});
    const hid_t d = H5Dopen2(f.get(), "/x", H5P_DEFAULT);
    const double whole[4] = {1, 2, 3, 4};
    const unsigned char part[20] = {};
    const hsize_t at0 = 0, at1 = 4;
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 3, &at0, sizeof whole, whole) >= 0);
    CHECK(H5Dwrite_chunk(d, H5P_DEFAULT, 3, &at1, sizeof part, part) >= 0);
    H5Dclose(d);
  }
  const File f = File::open_read(path);
  double out[4] = {};
  CHECK(rule_of([&] { f.read("/x", DType::Float64, {Selection::range(0, 4)}, out, 32); })
            .empty());
  CHECK(out[0] == 1 && out[3] == 4);
  CHECK(rule_of([&] { f.read("/x", DType::Float64, {Selection::range(4, 8)}, out, 32); }) ==
        "E23");
  std::remove(path.c_str());
}

// A filter the format does not allow is not read (E20, spec section 11.2).
void test_other_filter_is_not_read() {
  const std::string path = "wr_fletcher.gamut";
  {
    File f = File::create(path);
    const hsize_t n = 8, c = 4;
    const hid_t space = H5Screate_simple(1, &n, nullptr);
    const hid_t dcpl = H5Pcreate(H5P_DATASET_CREATE);
    H5Pset_chunk(dcpl, 1, &c);
    H5Pset_fletcher32(dcpl);
    const hid_t d = H5Dcreate2(f.get(), "/x", H5T_IEEE_F64LE, space, H5P_DEFAULT, dcpl,
                               H5P_DEFAULT);
    const double v[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    CHECK(H5Dwrite(d, H5T_NATIVE_DOUBLE, H5S_ALL, H5S_ALL, H5P_DEFAULT, v) >= 0);
    H5Dclose(d);
    H5Pclose(dcpl);
    H5Sclose(space);
  }
  const File f = File::open_read(path);
  double out[8] = {};
  CHECK(rule_of([&] { f.read("/x", DType::Float64, {}, out, sizeof out); }) == "E20");
  std::remove(path.c_str());
}

}  // namespace

int main() {
  const std::vector<std::pair<const char*, std::function<void()>>> tests = {
      {"table", test_table_run_at_a_time},
      {"shared_fixed", test_shared_fixed},
      {"shared_group", test_shared_per_group_out_of_order},
      {"changing", test_changing_per_run_and_group},
      {"refusals", test_refusals},
      {"bounds", test_outside_bounds},
      {"bounds_int", test_outside_large_integers},
      {"other_major", test_other_major_version},
      {"outside", test_values_stored_outside},
      {"growable", test_append_needs_growable_columns},
      {"rank", test_threaded_read_of_fewer_axes},
      {"read_limit", test_read_limit_before_allocation},
      {"short_chunk", test_short_unfiltered_chunk},
      {"private_outside", test_private_values_stored_outside},
      {"chunk_reads", test_chunk_reads_equal_hdf5},
      {"chunk_batches", test_threaded_reads_across_batches},
      {"chunk_writes", test_reads_after_writes_in_one_file},
      {"chunk_short_inflate", test_compressed_chunks_that_decode_short},
      {"chunk_filters_skipped", test_chunk_with_filters_skipped},
      {"chunk_other_filter", test_other_filter_is_not_read},
  };
  for (const auto& t : tests) {
    try {
      t.second();
    } catch (const gamut_core::Error& e) {
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
