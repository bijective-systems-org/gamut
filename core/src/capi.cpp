// The C interface: every mes_* function, each catching every exception
// at the boundary and turning it into a mes_error.
#include "mestra/mestra.h"

#include <cstring>
#include <exception>
#include <string>

#include "types.hpp"

namespace {

const char kVersion[] = "1.0.0.dev0";
const char kFormat[] = "mestra/1";

void copy_into(char* dst, std::size_t size, const std::string& src) {
  if (size == 0) return;
  const std::size_t n = src.size() < size - 1 ? src.size() : size - 1;
  std::memcpy(dst, src.data(), n);
  dst[n] = '\0';
}

}  // namespace

namespace mestra {
namespace internal {

// Fills `err` from the exception in flight; used by every catch block.
int fail(mes_error* err) {
  if (err == nullptr) return 1;
  std::memset(err, 0, sizeof *err);
  try {
    throw;
  } catch (const Error& e) {
    copy_into(err->rule, sizeof err->rule, e.rule());
    copy_into(err->path, sizeof err->path, e.path());
    copy_into(err->message, sizeof err->message, e.what());
  } catch (const std::bad_alloc&) {
    copy_into(err->message, sizeof err->message, "out of memory");
  } catch (const std::exception& e) {
    copy_into(err->message, sizeof err->message, e.what());
  } catch (...) {
    copy_into(err->message, sizeof err->message, "unknown failure");
  }
  return 1;
}

}  // namespace internal
}  // namespace mestra

extern "C" {

const char* mes_version(void) { return kVersion; }
const char* mes_format(void) { return kFormat; }

}  // extern "C"
