// SHA-256, written out rather than depended on, because the only use
// this library has for a hash is the support_id of spec section 14
// and a crypto library would be a dependency the format does not need.
#ifndef MESTRA_CORE_SHA256_HPP
#define MESTRA_CORE_SHA256_HPP

#include <cstddef>
#include <cstdint>
#include <string>


namespace mestra {

class Sha256 {
 public:
  Sha256();
  // Adds to the message.  Throws mestra::Error once `hex` has been
  // called, because the state is final by then.
  void update(const void* data, std::size_t length);
  // The digest in lower-case hexadecimal, 64 characters.  Calling it
  // again returns the same digest rather than hashing the padding a
  // second time.
  std::string hex();

 private:
  void block(const std::uint8_t* p);

  std::uint32_t h_[8];
  std::uint8_t buffer_[64];
  std::size_t buffered_ = 0;
  std::uint64_t total_bits_ = 0;
  std::string digest_;      // set by the first call to hex()
};

std::string sha256_hex(const void* data, std::size_t length);
std::string sha256_hex(const std::string& data);

}  // namespace mestra

#endif  // MESTRA_CORE_SHA256_HPP
