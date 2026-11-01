// The notice shown when a marked file opens (spec section 8): composed and
// sanitised here, queued for the calling thread while the core's lock is
// held, and given to the caller's sink once the lock is released.
#ifndef GAMUT_CORE_NOTICE_HPP
#define GAMUT_CORE_NOTICE_HPP

#include <string>

#include "schema.hpp"

namespace gamut_core {
namespace internal {

// `s` with CRLF and CR as LF, and U+FFFD for each invalid UTF-8 byte, each
// control character but LF and TAB, each C1 control and each bidirectional
// override or isolate: text a crafted file cannot use to move a terminal's
// cursor, reorder what is shown or break a decoder.
std::string shown_text(const std::string& s);

// The notice for a file whose schema `s` was read from `path`, as every
// language shows it.
std::string marking_notice(const Schema& s, const std::string& path);

// Called when a file's schema is read: a non-empty marking not yet shown in
// this process (since the sink was last set) is queued for the calling
// thread.
void marking_opened(const Schema& s, const std::string& path);

// Gives the notices queued during one call to the sink.  A C entry point
// that can open a file holds one, declared before its lock, so delivery
// comes after the lock is released, on failure too.  (Notices queued by the
// core's own tests, which open files without one, are dropped.)
struct DeliverNotices {
  DeliverNotices();
  DeliverNotices(const DeliverNotices&) = delete;
  DeliverNotices& operator=(const DeliverNotices&) = delete;
  ~DeliverNotices();
};

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_NOTICE_HPP
