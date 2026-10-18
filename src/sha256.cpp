#include "sha256.hpp"

#include <cstring>

#include "types.hpp"

namespace gamut_core {
namespace {

const std::uint32_t kK[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu,
    0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u,
    0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u,
    0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
    0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u,
    0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
    0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
    0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u,
    0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u, 0x1e376c08u,
    0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu,
    0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

inline std::uint32_t rotr(std::uint32_t x, unsigned n) {
  return (x >> n) | (x << (32u - n));
}

}  // namespace

Sha256::Sha256() {
  h_[0] = 0x6a09e667u;
  h_[1] = 0xbb67ae85u;
  h_[2] = 0x3c6ef372u;
  h_[3] = 0xa54ff53au;
  h_[4] = 0x510e527fu;
  h_[5] = 0x9b05688cu;
  h_[6] = 0x1f83d9abu;
  h_[7] = 0x5be0cd19u;
  std::memset(buffer_, 0, sizeof(buffer_));
}

void Sha256::block(const std::uint8_t* p) {
  std::uint32_t w[64];
  for (int i = 0; i < 16; ++i) {
    w[i] = (static_cast<std::uint32_t>(p[4 * i]) << 24) |
           (static_cast<std::uint32_t>(p[4 * i + 1]) << 16) |
           (static_cast<std::uint32_t>(p[4 * i + 2]) << 8) |
           static_cast<std::uint32_t>(p[4 * i + 3]);
  }
  for (int i = 16; i < 64; ++i) {
    const std::uint32_t s0 =
        rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
    const std::uint32_t s1 =
        rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  std::uint32_t a = h_[0], b = h_[1], c = h_[2], d = h_[3];
  std::uint32_t e = h_[4], f = h_[5], g = h_[6], hh = h_[7];
  for (int i = 0; i < 64; ++i) {
    const std::uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
    const std::uint32_t ch = (e & f) ^ (~e & g);
    const std::uint32_t t1 = hh + s1 + ch + kK[i] + w[i];
    const std::uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
    const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
    const std::uint32_t t2 = s0 + maj;
    hh = g;
    g = f;
    f = e;
    e = d + t1;
    d = c;
    c = b;
    b = a;
    a = t1 + t2;
  }
  h_[0] += a;
  h_[1] += b;
  h_[2] += c;
  h_[3] += d;
  h_[4] += e;
  h_[5] += f;
  h_[6] += g;
  h_[7] += hh;
}

void Sha256::update(const void* data, std::size_t length) {
  if (!digest_.empty()) {
    throw Error("", "this SHA-256 has been finished and cannot be added to");
  }
  const std::uint8_t* p = static_cast<const std::uint8_t*>(data);
  total_bits_ += static_cast<std::uint64_t>(length) * 8u;
  while (length > 0) {
    const std::size_t room = 64 - buffered_;
    const std::size_t take = length < room ? length : room;
    std::memcpy(buffer_ + buffered_, p, take);
    buffered_ += take;
    p += take;
    length -= take;
    if (buffered_ == 64) {
      block(buffer_);
      buffered_ = 0;
    }
  }
}

std::string Sha256::hex() {
  // Idempotent: the padding is hashed once and the digest kept, so a
  // second call answers with the same 64 characters instead of
  // padding the padding.
  if (!digest_.empty()) return digest_;
  // The padded tail is at most 63 + 1 + 55 + 8 = 127 bytes.
  const std::uint64_t bits = total_bits_;
  std::uint8_t tail[128];
  std::memset(tail, 0, sizeof(tail));
  std::size_t n = buffered_;
  std::memcpy(tail, buffer_, n);
  tail[n++] = 0x80;
  while (n % 64 != 56) tail[n++] = 0;
  for (int i = 0; i < 8; ++i) {
    tail[n++] = static_cast<std::uint8_t>((bits >> (56 - 8 * i)) & 0xffu);
  }
  for (std::size_t off = 0; off < n; off += 64) block(tail + off);
  buffered_ = 0;

  static const char* digits = "0123456789abcdef";
  std::string out;
  out.reserve(64);
  for (int i = 0; i < 8; ++i) {
    for (int b = 3; b >= 0; --b) {
      const std::uint8_t byte =
          static_cast<std::uint8_t>((h_[i] >> (8 * b)) & 0xffu);
      out.push_back(digits[byte >> 4]);
      out.push_back(digits[byte & 0x0fu]);
    }
  }
  digest_ = out;
  return out;
}

std::string sha256_hex(const void* data, std::size_t length) {
  Sha256 s;
  s.update(data, length);
  return s.hex();
}

std::string sha256_hex(const std::string& data) {
  return sha256_hex(data.data(), data.size());
}

}  // namespace gamut_core
