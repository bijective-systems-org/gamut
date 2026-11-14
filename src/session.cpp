#include "session.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <random>
#include <system_error>

#include "types.hpp"

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <sys/clonefile.h>
#elif defined(__linux__)
#include <linux/fs.h>
#include <sys/ioctl.h>
#endif
#endif

namespace fs = std::filesystem;

namespace gamut_core {
namespace internal {

namespace {

const char* const kLockSuffix = ".appending";
const char* const kCopySuffix = ".appending-";

std::string hex8() {
  std::random_device rd;
  char out[9];
  std::snprintf(out, sizeof out, "%08x", static_cast<unsigned>(rd()));
  return out;
}

bool is_hex8(const std::string& s) {
  if (s.size() != 8) return false;
  for (const char c : s) {
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

std::string busy(const std::string& path) {
  return "\"" + path + "\" is being appended to by another session; close that one first (a "
         "file takes one append at a time)";
}

#if !defined(_WIN32)
std::string os_error() { return std::strerror(errno); }

// Writes the file or folder at `path` to the disk: the copy before it is
// renamed, then its folder, so the rename lasts.
void sync_path(const std::string& path) {
  const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) return;
  ::fsync(fd);
  ::close(fd);
}
#endif

// A copy of `src` at `dst`, which does not exist yet: a clone where the
// filesystem makes one, else the bytes.
void copy_file(const std::string& src, const std::string& dst) {
#if defined(__APPLE__)
  if (::clonefile(src.c_str(), dst.c_str(), 0) == 0) return;
#elif defined(__linux__) && defined(FICLONE)
  {
    const int in = ::open(src.c_str(), O_RDONLY | O_CLOEXEC);
    if (in >= 0) {
      struct stat st{};
      const mode_t mode = ::fstat(in, &st) == 0 ? (st.st_mode & 07777) : 0644;
      const int out = ::open(dst.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, mode);
      if (out >= 0) {
        const bool cloned = ::ioctl(out, FICLONE, in) == 0 && ::fchmod(out, mode) == 0;
        ::close(out);
        ::close(in);
        if (cloned) return;
        ::unlink(dst.c_str());
      } else {
        ::close(in);
      }
    }
  }
#endif
  std::error_code ec;
  const fs::path from = fs::u8path(src), to = fs::u8path(dst);
  fs::copy_file(from, to, fs::copy_options::none, ec);
  if (!ec) fs::permissions(to, fs::status(from, ec).permissions(), ec);
  if (ec) {
    std::error_code ignored;
    fs::remove(to, ignored);
    throw Error("", "cannot copy \"" + src + "\" beside itself to append to it: " + ec.message() +
                        "; the file is unchanged");
  }
}

}  // namespace

std::unique_ptr<AppendSession> AppendSession::lock(const std::string& path) {
  std::error_code ec;
  const fs::path given = fs::u8path(path);
  if (!fs::exists(given, ec)) throw Error("E1", "there is no file \"" + path + "\"");
  const fs::path target = fs::canonical(given, ec);
  if (ec) throw Error("E1", "cannot open \"" + path + "\": " + ec.message());
  std::unique_ptr<AppendSession> s(new AppendSession());
  s->target_ = target.u8string();
  s->lock_path_ = s->target_ + kLockSuffix;
#if defined(_WIN32)
  // Opened without sharing and deleted when its handle closes, the process's
  // end included: a second session cannot open it.
  HANDLE h = ::CreateFileW(fs::u8path(s->lock_path_).wstring().c_str(), GENERIC_READ | DELETE, 0,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_DELETE_ON_CLOSE,
                           nullptr);
  if (h == INVALID_HANDLE_VALUE) {
    const DWORD e = ::GetLastError();
    if (e == ERROR_SHARING_VIOLATION) throw Error("", busy(path));
    throw Error("", "cannot create \"" + s->lock_path_ + "\" to append to \"" + path +
                        "\": " + std::system_category().message(static_cast<int>(e)));
  }
  s->handle_ = h;
#else
  // flock on a lock file beside the file: the lock ends with the process,
  // and readers, which never take it, keep reading the file meanwhile.
  bool unlocked = false;
  for (int attempt = 0; attempt < 16 && s->fd_ < 0; ++attempt) {
    const int fd = ::open(s->lock_path_.c_str(), O_RDONLY | O_CREAT | O_CLOEXEC, 0666);
    if (fd < 0) {
      throw Error("", "cannot create \"" + s->lock_path_ + "\" to append to \"" + path +
                          "\": " + os_error());
    }
    if (::flock(fd, LOCK_EX | LOCK_NB) != 0) {
      const int e = errno;
      ::close(fd);
      if (e == EWOULDBLOCK) throw Error("", busy(path));
      // A filesystem without locks: the session goes on unlocked, as HDF5's
      // best-effort locking does.
      if (e != ENOLCK && e != ENOTSUP && e != EOPNOTSUPP && e != ENOSYS) {
        errno = e;
        throw Error("", "cannot lock \"" + s->lock_path_ + "\": " + os_error());
      }
      unlocked = true;
      break;
    }
    // A session that ended between the open and the lock removed the file
    // this lock is on; the lock counts only on the file at the path now.
    struct stat held{}, now{};
    if (::fstat(fd, &held) == 0 && ::stat(s->lock_path_.c_str(), &now) == 0 &&
        held.st_dev == now.st_dev && held.st_ino == now.st_ino) {
      s->fd_ = fd;
    } else {
      ::close(fd);
    }
  }
  if (s->fd_ < 0 && !unlocked) {
    throw Error("", "cannot take the append lock \"" + s->lock_path_ + "\"");
  }
#endif
  // Every copy beside the file is a stopped session's: a live one would hold
  // the lock.
  const std::string prefix = target.filename().u8string() + kCopySuffix;
  for (const auto& entry : fs::directory_iterator(target.parent_path(), ec)) {
    const std::string name = entry.path().filename().u8string();
    if (name.size() == prefix.size() + 8 && name.compare(0, prefix.size(), prefix) == 0 &&
        is_hex8(name.substr(prefix.size()))) {
      std::error_code ignored;
      fs::remove(entry.path(), ignored);
    }
  }
  return s;
}

const std::string& AppendSession::copy() {
  for (int attempt = 0; copy_path_.empty(); ++attempt) {
    const std::string candidate = target_ + kCopySuffix + hex8();
    std::error_code ec;
    if (fs::exists(fs::u8path(candidate), ec)) {
      if (attempt > 16) throw Error("", "cannot name a copy of \"" + target_ + "\"");
      continue;
    }
    copy_file(target_, candidate);
    copy_path_ = candidate;
  }
  return copy_path_;
}

void AppendSession::publish() {
  keep_copy_ = true;   // from here the copy holds the session's runs
  std::string why;
#if defined(_WIN32)
  const std::wstring from = fs::u8path(copy_path_).wstring();
  const std::wstring to = fs::u8path(target_).wstring();
  HANDLE h = ::CreateFileW(from.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, nullptr);
  if (h != INVALID_HANDLE_VALUE) {
    ::FlushFileBuffers(h);
    ::CloseHandle(h);
  }
  // A reader holding the file open blocks the rename while it does.
  for (int attempt = 0; attempt < 50; ++attempt) {
    if (::MoveFileExW(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
      why.clear();
      break;
    }
    const DWORD e = ::GetLastError();
    why = std::system_category().message(static_cast<int>(e));
    if (e != ERROR_SHARING_VIOLATION && e != ERROR_ACCESS_DENIED) break;
    ::Sleep(100);
  }
#else
  sync_path(copy_path_);
  if (::rename(copy_path_.c_str(), target_.c_str()) == 0) {
    sync_path(fs::u8path(target_).parent_path().u8string());
  } else {
    why = os_error();
  }
#endif
  if (!why.empty()) {
    throw Error("", "cannot replace \"" + target_ + "\" with its appended copy: " + why +
                        "; the runs added are in \"" + copy_path_ +
                        "\": rename it over the file before appending to it again, which removes "
                        "such copies");
  }
  published_ = true;
  release();
}

void AppendSession::release() {
#if defined(_WIN32)
  if (handle_ != nullptr) {
    ::CloseHandle(static_cast<HANDLE>(handle_));
    handle_ = nullptr;
  }
#else
  if (fd_ >= 0) {
    // Removed while still locked, so a session waiting on this file sees
    // it replaced and takes the next one.
    ::unlink(lock_path_.c_str());
    ::close(fd_);
    fd_ = -1;
  }
#endif
}

AppendSession::~AppendSession() {
  if (!published_ && !keep_copy_ && !copy_path_.empty()) {
    std::error_code ignored;
    fs::remove(fs::u8path(copy_path_), ignored);
  }
  release();
}

}  // namespace internal
}  // namespace gamut_core
