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
  } catch (const gamut_core::Error& e) {
    return e.rule().empty() ? std::string("error") : e.rule();
  }
  return std::string();
}

using gamut_core::DType;
using gamut_core::Selection;
using gamut_core::internal::File;

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
    CHECK(gamut_core::units_parse(ok));
  }
  for (const char* bad : {"", " ", "m//s", "m+s", "m\ts"}) {
    CHECK(!gamut_core::units_parse(bad));
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
  CHECK(gamut_core::sha256_hex(bytes) ==
        "96df395d80ef548444562292de441525ba0b5c8ad00a8dadff19a19c943936c7");
}

void test_names() {
  using gamut_core::internal::legal_netcdf_name;
  CHECK(legal_netcdf_name("mach"));
  CHECK(legal_netcdf_name("velocity_x"));
  CHECK(legal_netcdf_name("_hidden"));
  CHECK(!legal_netcdf_name(""));
  CHECK(!legal_netcdf_name("a/b"));
  CHECK(!legal_netcdf_name(" a"));
  CHECK(gamut_core::internal::reserved_name("gamut_x"));
  CHECK(gamut_core::internal::iso8601_utc("2026-10-17T00:00:00Z"));
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
                     {H5S_UNLIMITED, 5}, {2, 5}, gamut_core::default_pipeline());
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
    f.write_attr("/mach", "units", gamut_core::AttrValue::text("1"));
    f.write_attr("/mach", "lower", gamut_core::AttrValue::real(0.5));
    f.write_attr("/", "n", gamut_core::AttrValue::integer(7));
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
  CHECK(gamut_core::internal::pipeline_of(pinfo) == gamut_core::default_pipeline());
  CHECK(pinfo.scales[1].size() == 1 && pinfo.scales[1][0] == "node_scale");
  CHECK(f.dataset_info("/row").is_scale);
  const auto sinfo = f.dataset_info("/node_scale");
  CHECK(sinfo.attr_order_tracked && sinfo.attr_order_indexed);
  bool saw_units = false;
  for (const auto& a : f.attributes("/mach")) {
    if (a.name == "units") saw_units = a.value.as_text() == "1" &&
                                       gamut_core::internal::is_spec_string(a.type);
  }
  CHECK(saw_units);
  std::remove(path.c_str());
#ifdef GAMUT_OWN_HDF5
  // The core's own HDF5 loads no filter plugin (src/h5.cpp).
  unsigned int plugins = 1;
  CHECK(H5PLget_loading_state(&plugins) >= 0 && plugins == 0);
#endif
}

void test_attribute_replacement() {
  using gamut_core::AttrValue;
  const std::string path = "core_replace_attr.gamut";
  const auto text_is = [](const File& f, const std::string& name,
                          const std::string& value) {
    for (const auto& a : f.attributes("/")) {
      if (a.name == name) {
        return a.value.kind() == AttrValue::Kind::Str &&
               a.value.as_text() == value &&
               gamut_core::internal::is_spec_string(a.type);
      }
    }
    return false;
  };
  const std::string old(60000, 'm');
  {
    File f = File::create(path);
    for (const std::string value : {std::string("first"), std::string(1000, 'x'),
                                    std::string("short"), std::string("\xc2\xb5"),
                                    std::string(), old}) {
      f.replace_attr("/", "title", AttrValue::text(value));
      CHECK(text_is(f, "title", value));
      CHECK(f.attributes("/").size() == 1);
    }
    for (int i = 0; i < 2; ++i) {
      CHECK(!raises([&] {
        f.replace_attr("/", "title", AttrValue::text(std::string(65536, 'x')));
      }).empty());
      CHECK(text_is(f, "title", old));
      CHECK(f.attributes("/").size() == 1);
    }
    CHECK(!raises([&] { f.replace_attr("/", "", AttrValue::text("bad")); }).empty());
    CHECK(!raises([&] {
      f.replace_attr("/missing", "title", AttrValue::text("bad"));
    }).empty());
    CHECK(text_is(f, "title", old));
    CHECK(f.attributes("/").size() == 1);
    CHECK(!raises([&] {
      f.replace_attr("/", "source", AttrValue::text(std::string(65536, 'x')));
    }).empty());
    CHECK(text_is(f, "title", old));
    CHECK(f.attributes("/").size() == 1);
  }
  {
    File f = File::open_read(path);
    CHECK(text_is(f, "title", old));
    CHECK(f.attributes("/").size() == 1);
  }
  {
    File f = File::open_write(path);
    // Temporary names must never overwrite an existing user attribute.
    f.write_attr("/", "_", AttrValue::text("keep new"));
    f.write_attr("/", "__", AttrValue::text("keep old"));
    for (const auto& value : {AttrValue::integer(42), AttrValue::real(1.25),
                              AttrValue::boolean(true)}) {
      f.replace_attr("/", "title", value);
      bool found = false;
      for (const auto& a : f.attributes("/")) {
        if (a.name == "title") found = a.value == value;
      }
      CHECK(found);
    }
    f.replace_attr("/", "_", AttrValue::text("keep new"));
    f.replace_attr("/", "__", AttrValue::text("keep old"));
    f.replace_attr("/", "title", AttrValue::text("final"));
    CHECK(text_is(f, "title", "final"));
    CHECK(text_is(f, "_", "keep new"));
    CHECK(text_is(f, "__", "keep old"));
    CHECK(f.attributes("/").size() == 3);
  }
  {
    File f = File::open_read(path);
    CHECK(text_is(f, "title", "final"));
    CHECK(!raises([&] {
      f.replace_attr("/", "title", AttrValue::text("read only"));
    }).empty());
    CHECK(text_is(f, "title", "final"));
    CHECK(f.attributes("/").size() == 3);
  }
  std::remove(path.c_str());
}

void test_attribute_replacement_boundaries() {
  using gamut_core::AttrValue;
  const auto text_is = [](const File& f, const std::string& object,
                          const std::string& name, const std::string& text) {
    for (const auto& a : f.attributes(object)) {
      if (a.name == name) return a.value == AttrValue::text(text);
    }
    return false;
  };
  for (const std::string object : {std::string("/"), std::string("/notes")}) {
    // HDF5 1.14.6 loses the original if it is renamed to a longer backup
    // name at these compact-message sizes.
    for (int size = 65496; size <= 65503; ++size) {
      const std::string path = "core_replace_boundary.gamut";
      {
        File f = File::create(path);
        f.make_group(object);
        f.write_attr(object, "title", AttrValue::text(std::string(size, 'm')));
        for (int i = 1; i <= 8; ++i) {
          f.write_attr(object, std::string(i, '_'), AttrValue::integer(i));
        }
        CHECK(!raises([&] {
          f.replace_attr(object, "title", AttrValue::text(std::string(65536, 'x')));
        }).empty());
        CHECK(text_is(f, object, "title", std::string(size, 'm')));
        CHECK(f.attributes(object).size() == 9);
        f.replace_attr(object, "title", AttrValue::text("new"));
        CHECK(text_is(f, object, "title", "new"));
        CHECK(!raises([&] {
          f.replace_attr(object, "title", AttrValue::text(std::string(65536, 'x')));
        }).empty());
        CHECK(text_is(f, object, "title", "new"));
        CHECK(f.attributes(object).size() == 9);
      }
      {
        File f = File::open_read(path);
        CHECK(text_is(f, object, "title", "new"));
        const auto attrs = f.attributes(object);
        CHECK(attrs.size() == 9);
        for (int i = 1; i <= 8; ++i) {
          bool found = false;
          for (const auto& a : attrs) {
            if (a.name == std::string(i, '_')) found = a.value == AttrValue::integer(i);
          }
          CHECK(found);
        }
      }
      std::remove(path.c_str());
    }
    // This tight-boundary seed is readable before any replacement. Larger
    // raw seeds above can already be unreadable after close without replacing.
    const std::string tight_path = "core_replace_tight.gamut";
    const std::string tight(65496, 'm');
    {
      File f = File::create(tight_path);
      f.make_group(object);
      f.write_attr(object, "title", AttrValue::text(tight));
      for (int i = 1; i <= 8; ++i) f.write_attr(object, std::string(i, '_'), AttrValue::integer(i));
    }
    {
      File f = File::open_write(tight_path);
      CHECK(text_is(f, object, "title", tight));
      CHECK(!raises([&] {
        f.replace_attr(object, "title", AttrValue::text(std::string(65536, 'x')));
      }).empty());
      CHECK(text_is(f, object, "title", tight));
    }
    {
      File f = File::open_read(tight_path);
      CHECK(text_is(f, object, "title", tight));
      CHECK(f.attributes(object).size() == 9);
    }
    std::remove(tight_path.c_str());
    // If every one-byte recovery name is occupied, refuse before touching
    // the original rather than making a compact attribute's name longer.
    const std::string path = "core_replace_no_backup.gamut";
    const std::string names = "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const std::string old = "unchanged";
    {
      File f = File::create(path);
      f.make_group(object);
      f.write_attr(object, "title", AttrValue::text(old));
      for (const char name : names) f.write_attr(object, std::string(1, name), AttrValue::integer(7));
      CHECK(!raises([&] { f.replace_attr(object, "title", AttrValue::text("new")); }).empty());
      CHECK(text_is(f, object, "title", old));
      CHECK(f.attributes(object).size() == names.size() + 1);
    }
    {
      File f = File::open_read(path);
      CHECK(text_is(f, object, "title", old));
      CHECK(f.attributes(object).size() == names.size() + 1);
    }
    std::remove(path.c_str());
  }
}

void test_attribute_replacement_metadata() {
  using gamut_core::AttrValue;
  using gamut_core::internal::Id;
  const std::string path = "core_replace_metadata.gamut";
  {
    File f = File::create(path);
    Id object(H5Oopen(f.get(), "/", H5P_DEFAULT));
    const hsize_t count = 3;
    Id space(H5Screate_simple(1, &count, nullptr));
    {
      Id attr(H5Acreate2(object.get(), "array", H5T_STD_I64LE, space.get(),
                         H5P_DEFAULT, H5P_DEFAULT));
      const std::int64_t values[] = {3, 5, 8};
      CHECK(attr.valid() && H5Awrite(attr.get(), H5T_NATIVE_INT64, values) >= 0);
    }
    CHECK(!raises([&] {
      f.replace_attr("/", "array", AttrValue::text(std::string(65536, 'x')));
    }).empty());
    {
      Id attr(H5Aopen(object.get(), "array", H5P_DEFAULT));
      Id type(H5Aget_type(attr.get()));
      Id stored(H5Aget_space(attr.get()));
      CHECK(attr.valid() && H5Tequal(type.get(), H5T_STD_I64LE) > 0);
      CHECK(H5Sextent_equal(space.get(), stored.get()) > 0);
      std::int64_t values[3] = {};
      CHECK(H5Aread(attr.get(), H5T_NATIVE_INT64, values) >= 0);
      CHECK(values[0] == 3 && values[1] == 5 && values[2] == 8);
    }
    // Pointer-bearing types are refused before any original mutation.
    Id variable(H5Tcopy(H5T_C_S1));
    CHECK(H5Tset_size(variable.get(), H5T_VARIABLE) >= 0);
    Id scalar(H5Screate(H5S_SCALAR));
    {
      Id attr(H5Acreate2(object.get(), "variable", variable.get(), scalar.get(),
                         H5P_DEFAULT, H5P_DEFAULT));
      const char* value = "original variable string";
      CHECK(attr.valid() && H5Awrite(attr.get(), variable.get(), &value) >= 0);
    }
    CHECK(!raises([&] { f.replace_attr("/", "variable", AttrValue::text("new")); }).empty());
    CHECK(f.attributes("/").size() == 2);
  }
  {
    File f = File::open_read(path);
    Id attr(H5Aopen(f.get(), "array", H5P_DEFAULT));
    std::int64_t values[3] = {};
    CHECK(attr.valid() && H5Aread(attr.get(), H5T_NATIVE_INT64, values) >= 0);
    CHECK(values[0] == 3 && values[1] == 5 && values[2] == 8);
    Id variable(H5Aopen(f.get(), "variable", H5P_DEFAULT));
    Id type(H5Aget_type(variable.get()));
    CHECK(H5Tis_variable_str(type.get()) > 0);
    char* value = nullptr;
    CHECK(H5Aread(variable.get(), type.get(), &value) >= 0);
    CHECK(value != nullptr && std::string(value) == "original variable string");
    if (value != nullptr) H5free_memory(value);
    CHECK(f.attributes("/").size() == 2);
  }
  std::remove(path.c_str());
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
      {"attribute_replacement", test_attribute_replacement},
      {"attribute_replacement_boundaries", test_attribute_replacement_boundaries},
      {"attribute_replacement_metadata", test_attribute_replacement_metadata},
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
