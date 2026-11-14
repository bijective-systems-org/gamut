// An append session (spec section 11.5).  Runs are added to a copy beside
// the file, and the copy replaces the file when the session closes, so a
// writer stopped partway leaves the file as it was.  A lock file beside the
// file lets one session at a time append; readers keep the file itself.
#pragma once

#include <memory>
#include <string>

namespace gamut_core {
namespace internal {

class AppendSession {
 public:
  // Takes the append lock of the file at `path` and removes copies that
  // stopped sessions left.  Refuses a file another session is appending to.
  static std::unique_ptr<AppendSession> lock(const std::string& path);
  ~AppendSession();
  AppendSession(const AppendSession&) = delete;
  AppendSession& operator=(const AppendSession&) = delete;

  // Copies the file beside itself (a clone where the filesystem has them)
  // and returns the copy's path, which the session writes.
  const std::string& copy();
  // Makes the copy durable and renames it over the file.  When the rename
  // fails the copy is kept and the error names it.
  void publish();

 private:
  AppendSession() = default;
  void release();

  std::string target_;      // the file, symbolic links resolved
  std::string lock_path_;
  std::string copy_path_;
  bool published_ = false;
  bool keep_copy_ = false;
#ifdef _WIN32
  void* handle_ = nullptr;  // the lock file, deleted when this handle closes
#else
  int fd_ = -1;
#endif
};

}  // namespace internal
}  // namespace gamut_core
