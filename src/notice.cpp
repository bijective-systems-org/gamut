#include "notice.hpp"

#include <cstdio>
#include <mutex>
#include <set>
#include <utility>
#include <vector>

#include "gamut/gamut.h"

namespace gamut_core {
namespace internal {

namespace {

// The sink and the files shown, apart from the core's lock: a sink is
// called without that lock, and may set another sink.  Never destroyed, so
// a file opened during process exit still finds them.
struct Sink {
  std::mutex mutex;
  gamut_notice_fn fn = nullptr;   // nullptr: the default, stderr
  void* context = nullptr;
  std::set<std::string> shown;    // file_id (or path), NUL, marking
};

Sink& sink() {
  static Sink* s = new Sink();
  return *s;
}

// Notices composed on this thread and not yet delivered: (path, text).
thread_local std::vector<std::pair<std::string, std::string>> pending;

const char kReplacement[] = "\xEF\xBF\xBD";   // U+FFFD

// The code point of the UTF-8 sequence at s[i] and its length, or a length
// of 0 for an invalid sequence (overlong forms and surrogates included).
std::pair<unsigned, std::size_t> decode(const std::string& s, std::size_t i) {
  const unsigned char c = static_cast<unsigned char>(s[i]);
  if (c < 0x80) return {c, 1};
  std::size_t n = 0;
  unsigned code = 0, least = 0;
  if ((c & 0xE0u) == 0xC0u) {
    n = 2;
    code = c & 0x1Fu;
    least = 0x80;
  } else if ((c & 0xF0u) == 0xE0u) {
    n = 3;
    code = c & 0x0Fu;
    least = 0x800;
  } else if ((c & 0xF8u) == 0xF0u) {
    n = 4;
    code = c & 0x07u;
    least = 0x10000;
  } else {
    return {0, 0};
  }
  if (i + n > s.size()) return {0, 0};
  for (std::size_t k = 1; k < n; ++k) {
    const unsigned char x = static_cast<unsigned char>(s[i + k]);
    if ((x & 0xC0u) != 0x80u) return {0, 0};
    code = (code << 6) | (x & 0x3Fu);
  }
  if (code < least || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) return {0, 0};
  return {code, n};
}

bool replaced(unsigned code) {
  return (code < 0x20 && code != '\n' && code != '\t') || (code >= 0x7F && code <= 0x9F) ||
         (code >= 0x202A && code <= 0x202E) || (code >= 0x2066 && code <= 0x2069);
}

}  // namespace

std::string shown_text(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  std::size_t i = 0;
  while (i < s.size()) {
    if (s[i] == '\r') {
      out += '\n';
      i += i + 1 < s.size() && s[i + 1] == '\n' ? 2 : 1;
      continue;
    }
    const auto cp = decode(s, i);
    if (cp.second == 0 || replaced(cp.first)) {
      out += kReplacement;
      i += cp.second == 0 ? 1 : cp.second;
    } else {
      out.append(s, i, cp.second);
      i += cp.second;
    }
  }
  return out;
}

std::string marking_notice(const Schema& s, const std::string& path) {
  std::string text = "gamut: " + shown_text(path) + " carries a portion marking\n";
  std::string about;
  if (!s.created.empty()) about = "created " + shown_text(s.created);
  if (!s.writer.empty()) about += (about.empty() ? "written by " : " by ") + shown_text(s.writer);
  if (!s.file_id.empty()) about += (about.empty() ? "" : ", ") + std::string("file_id ") +
                                   shown_text(s.file_id);
  if (!about.empty()) text += "  " + about + "\n";
  const std::string marking = shown_text(s.portion_marking);
  text += "---- portion marking ----\n" + marking;
  if (marking.back() != '\n') text += '\n';
  return text + "---- end of portion marking ----";
}

void marking_opened(const Schema& s, const std::string& path) {
  if (s.portion_marking.empty()) return;
  // A file evaluated from a model carries the model file's marking (spec
  // section 7.4), and is known by that file's id: every answer of a loop
  // of evaluations is a new file, and its marking was shown with the model.
  const std::string& id = !s.evaluated_from.empty() ? s.evaluated_from : s.file_id;
  const std::string key = (id.empty() ? path : id) + '\0' + s.portion_marking;
  {
    Sink& k = sink();
    const std::lock_guard<std::mutex> lock(k.mutex);
    if (!k.shown.insert(key).second) return;
  }
  pending.emplace_back(shown_text(path), marking_notice(s, path));
}

DeliverNotices::DeliverNotices() { pending.clear(); }

DeliverNotices::~DeliverNotices() {
  if (pending.empty()) return;
  std::vector<std::pair<std::string, std::string>> notices;
  notices.swap(pending);   // a sink that opens a file delivers that file's itself
  for (const auto& n : notices) {
    gamut_notice_fn fn;
    void* context;
    {
      Sink& k = sink();
      const std::lock_guard<std::mutex> lock(k.mutex);
      fn = k.fn;
      context = k.context;
    }
    // A sink must not throw (gamut.h); one that does is not let past here.
    try {
      if (fn != nullptr) {
        fn(n.first.c_str(), n.second.c_str(), context);
      } else {
        std::fprintf(stderr, "%s\n", n.second.c_str());
      }
    } catch (...) {
    }
  }
}

}  // namespace internal
}  // namespace gamut_core

extern "C" void gamut_set_marking_notice(gamut_notice_fn fn, void* context) {
  gamut_core::internal::Sink& k = gamut_core::internal::sink();
  const std::lock_guard<std::mutex> lock(k.mutex);
  k.fn = fn;
  k.context = context;
  k.shown.clear();
}
