// The model-data codec of spec section 12: a dictionary to an HDF5 group
// and back, identically in every language because it is done once, here.
#ifndef MESTRA_CORE_CODEC_HPP
#define MESTRA_CORE_CODEC_HPP

#include <string>
#include <vector>

#include "h5.hpp"
#include "value.hpp"

namespace mestra {
namespace internal {

// Reads the dictionary on the group `path`.  At the top level the group's
// own attributes `type`, `inputs` and `repr` are not dictionary entries.
// Anything section 12 cannot represent raises E18; a link that is not hard
// raises E22; nesting past kMaxDictDepth raises E23.
Dict read_dict_group(const File& f, const std::string& path, bool top_level, int depth = 0);

// Writes `d` into the existing group `path`, keys in UTF-8 byte order.
// Refuses what section 12 cannot represent (E18) and illegal keys (E8).
void write_dict_group(File& f, const std::string& path, const Dict& d, bool top_level,
                      int depth = 0);

}  // namespace internal
}  // namespace mestra

#endif  // MESTRA_CORE_CODEC_HPP
