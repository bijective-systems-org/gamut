// Unit tests of the core's internals.  Each test states what the spec
// decides and checks it; the corpus checks whole files.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <string>
#include <vector>

#include "h5.hpp"
#include "gamut/gamut.h"
#include "names.hpp"
#include "sha256.hpp"
#include "types.hpp"
#include "units.hpp"

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
std::string raises(F f) {
  try {
    f();
  } catch (const gamut::Error& e) {
    return e.rule().empty() ? std::string("error") : e.rule();
  }
  return std::string();
}

using gamut::DType;
using gamut::Selection;
using gamut::internal::File;

void test_selection() {
  CHECK(Selection::all().count(5, "x") == 5);
  CHECK(Selection::range(1, 4).count(5, "x") == 3);
  CHECK(Selection::list({0, 2, 3}).count(5, "x") == 3);
  CHECK(!raises([] { Selection::range(2, 6).count(5, "x"); }).empty());
  CHECK(!raises([] { Selection::list({1, 1}).count(5, "x"); }).empty());
  CHECK(!raises([] { Selection::list({3, 2}).count(5, "x"); }).empty());
  CHECK(!raises([] { Selection::list({-1}).count(5, "x"); }).empty());
  const auto runs = Selection::list({0, 1, 2, 5, 7, 8}).runs(10, "x");
  CHECK(runs.size() == 3);
  CHECK(runs[0].first == 0 && runs[0].second == 3);
  CHECK(runs[1].first == 5 && runs[1].second == 1);
  CHECK(runs[2].first == 7 && runs[2].second == 2);
  CHECK(Selection::range(3, 3).runs(5, "x").empty());
}

void test_units() {
  for (const char* ok : {"Pa", "m s-1", "W m-2", "1", "kg m-3", "degree",
                         "m2", "s^0.5", "(m s-1)2", "days since 2000-01-01"}) {
    CHECK(gamut::units_parse(ok));
  }
  for (const char* bad : {"", " ", "m//s", "m+s", "m\ts"}) {
    CHECK(!gamut::units_parse(bad));
  }
}

void test_sha256_support_id_example() {
  // Spec section 14's worked example.
  std::string bytes;
  const std::int64_t n_nodes = 6;
  bytes.append(reinterpret_cast<const char*>(&n_nodes), 8);
  const std::uint8_t types[] = {9, 9};
  bytes.append(reinterpret_cast<const char*>(types), 2);
  const std::int64_t offsets[] = {0, 4, 8};
  bytes.append(reinterpret_cast<const char*>(offsets), sizeof offsets);
  const std::int64_t conn[] = {0, 1, 4, 3, 1, 2, 5, 4};
  bytes.append(reinterpret_cast<const char*>(conn), sizeof conn);
  CHECK(bytes.size() == 98);
  CHECK(gamut::sha256_hex(bytes) ==
        "96df395d80ef548444562292de441525ba0b5c8ad00a8dadff19a19c943936c7");
}

void test_names() {
  using gamut::internal::legal_netcdf_name;
  CHECK(legal_netcdf_name("mach"));
  CHECK(legal_netcdf_name("velocity_x"));
  CHECK(legal_netcdf_name("_hidden"));
  CHECK(!legal_netcdf_name(""));
  CHECK(!legal_netcdf_name("a/b"));
  CHECK(!legal_netcdf_name(" a"));
  CHECK(gamut::internal::reserved_name("gamut_x"));
  CHECK(gamut::internal::iso8601_utc("2026-10-17T00:00:00Z"));
}

void test_capi_basics() {
  CHECK(std::strcmp(gamut_format(), "gamut/1") == 0);
  CHECK(std::strlen(gamut_version()) > 0);
}

void test_h5_roundtrip() {
  const std::string path = "core_unit_h5.gamut";
  {
    File f = File::create(path);
    f.make_scale("/row_scale", 0, true);
    // A float32 block of 4 rows x 5 nodes, chunked and compressed.
    f.create_dataset("/g/p", DType::Float32, 0, {4, 5},
                     {H5S_UNLIMITED, 5}, {2, 5}, gamut::default_pipeline());
    std::vector<float> p(20);
    for (int i = 0; i < 20; ++i) p[static_cast<std::size_t>(i)] = static_cast<float>(i) * 0.5f;
    f.write("/g/p", DType::Float32, {0, 0}, {4, 5}, p.data());
    // Grow by one row and write it.
    f.set_extent("/g/p", {5, 5});
    std::vector<float> extra = {100, 101, 102, 103, 104};
    f.write("/g/p", DType::Float32, {4, 0}, {1, 5}, extra.data());
    // int64 coordinate variable.
    f.create_dataset("/row", DType::Int64, 0, {3}, {H5S_UNLIMITED}, {512}, {});
    const std::int64_t ids[] = {0, 1, 2};
    f.write("/row", DType::Int64, {0}, {3}, ids);
    f.mark_coordinate_scale("/row", "row");
    f.create_dataset("/mach", DType::Float64, 0, {3}, {H5S_UNLIMITED}, {512}, {});
    const double mach[] = {0.5, 0.6, 0.7};
    f.write("/mach", DType::Float64, {0}, {3}, mach);
    f.attach_scale("/mach", "/row", 0);
    f.write_attr("/mach", "units", gamut::AttrValue::text("1"));
    f.write_attr("/mach", "lower", gamut::AttrValue::real(0.5));
    f.write_attr("/", "n", gamut::AttrValue::integer(7));
    f.create_dataset("/categories/status", DType::String, 9, {2}, {H5S_UNLIMITED},
                     {64}, {});
    f.write_strings("/categories/status", 0, {"converged", "failed"});
    f.make_scale("/node_scale", 5, false);
    f.attach_scale("/g/p", "/node_scale", 1);
  }
  File f = File::open_read(path);
  // Whole read, widened to float64 by HDF5.
  std::vector<double> all(25);
  f.read("/g/p", DType::Float64, {}, all.data(), all.size() * 8);
  CHECK(all[0] == 0.0 && all[19] == 9.5 && all[24] == 104.0);
  // Rows 1..3 (index list with a gap), nodes 2..4.
  std::vector<float> part(2 * 2);
  f.read("/g/p", DType::Float32,
         {Selection::list({1, 3}), Selection::range(2, 4)}, part.data(),
         part.size() * 4);
  CHECK(part[0] == 3.5f && part[1] == 4.0f && part[2] == 8.5f && part[3] == 9.0f);
  // A wrong buffer size is refused.
  CHECK(!raises([&] {
           f.read("/g/p", DType::Float32, {Selection::range(0, 1)}, part.data(), 4);
         }).empty());
  const auto shape = f.selected_shape("/g/p", {Selection::list({0, 4})});
  CHECK(shape.size() == 2 && shape[0] == 2 && shape[1] == 5);
  CHECK(f.read_i64("/row") == std::vector<std::int64_t>({0, 1, 2}));
  CHECK(f.read_strings("/categories/status") ==
        std::vector<std::string>({"converged", "failed"}));
  const auto info = f.dataset_info("/mach");
  CHECK(info.scales.size() == 1 && info.scales[0].size() == 1 &&
        info.scales[0][0] == "row");
  const auto pinfo = f.dataset_info("/g/p");
  CHECK(pinfo.chunked && pinfo.chunk[0] == 2);
  CHECK(gamut::internal::pipeline_of(pinfo) == gamut::default_pipeline());
  CHECK(pinfo.scales[1].size() == 1 && pinfo.scales[1][0] == "node_scale");
  CHECK(f.dataset_info("/row").is_scale);
  const auto sinfo = f.dataset_info("/node_scale");
  CHECK(sinfo.attr_order_tracked && sinfo.attr_order_indexed);
  bool saw_units = false;
  for (const auto& a : f.attributes("/mach")) {
    if (a.name == "units") saw_units = a.value.as_text() == "1" &&
                                       gamut::internal::is_spec_string(a.type);
  }
  CHECK(saw_units);
  std::remove(path.c_str());
#ifdef GAMUT_OWN_HDF5
  // The core's own HDF5 loads no filter plugin (src/h5.cpp).
  unsigned int plugins = 1;
  CHECK(H5PLget_loading_state(&plugins) >= 0 && plugins == 0);
#endif
}

}  // namespace

int main() {
  const std::vector<std::pair<const char*, std::function<void()>>> tests = {
      {"selection", test_selection},
      {"units", test_units},
      {"sha256", test_sha256_support_id_example},
      {"names", test_names},
      {"capi", test_capi_basics},
      {"h5", test_h5_roundtrip},
  };
  for (const auto& t : tests) {
    try {
      t.second();
    } catch (const std::exception& e) {
      ++g_failures;
      std::fprintf(stderr, "%s: unexpected exception: %s\n", t.first, e.what());
    }
  }
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
