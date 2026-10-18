#include "chunk.hpp"

namespace mestra {
namespace internal {

namespace {

hsize_t product(const std::vector<hsize_t>& v, std::size_t from) {
  hsize_t n = 1;
  for (std::size_t i = from; i < v.size(); ++i) n *= (v[i] == 0 ? 1 : v[i]);
  return n;
}

}  // namespace

std::vector<hsize_t> leading_chunk(std::size_t item,
                                   const std::vector<hsize_t>& trailing) {
  std::vector<hsize_t> chunk;
  const hsize_t b = static_cast<hsize_t>(item) * product(trailing, 0);
  if (b <= kChunkBytes) {
    hsize_t c = kChunkBytes / b > 0 ? kChunkBytes / b : 1;
    if (c > kMaxLeadingEntries) c = kMaxLeadingEntries;
    chunk.push_back(c);
    for (const hsize_t t : trailing) chunk.push_back(t == 0 ? 1 : t);
    return chunk;
  }
  chunk.push_back(1);
  const hsize_t rest = static_cast<hsize_t>(item) * product(trailing, 1);
  hsize_t m = kChunkBytes / rest;
  if (m < 1) m = 1;
  const hsize_t n = trailing.empty() ? 1 : trailing[0];
  chunk.push_back(m < n ? m : n);
  for (std::size_t i = 1; i < trailing.size(); ++i) {
    chunk.push_back(trailing[i] == 0 ? 1 : trailing[i]);
  }
  return chunk;
}

std::vector<hsize_t> end_to_end_chunk(std::size_t item,
                                      const std::vector<hsize_t>& trailing) {
  std::vector<hsize_t> chunk;
  const hsize_t b = static_cast<hsize_t>(item) * product(trailing, 0);
  chunk.push_back(kChunkBytes / b > 0 ? kChunkBytes / b : 1);
  for (const hsize_t t : trailing) chunk.push_back(t == 0 ? 1 : t);
  return chunk;
}

bool chunk_larger_than_default(const std::vector<hsize_t>& chunk,
                               const std::vector<hsize_t>& dflt) {
  if (chunk.size() != dflt.size()) return true;
  for (std::size_t i = 0; i < chunk.size(); ++i) {
    if (chunk[i] > dflt[i]) return true;
  }
  return false;
}

}  // namespace internal
}  // namespace mestra
