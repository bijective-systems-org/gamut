// The model-data codec of spec section 12: a dictionary to an HDF5 group
// and back, identically in every language because it is done once, here.
#ifndef GAMUT_CORE_CODEC_HPP
#define GAMUT_CORE_CODEC_HPP

#include <string>
#include <vector>

#include "h5.hpp"
#include "value.hpp"

namespace gamut_core {
namespace internal {

// Reads the dictionary on the group `path`.  At the top level the group's
// own attributes `type`, `inputs` and `repr` are not dictionary entries.
// Anything section 12 cannot represent raises E18; a link that is not hard
// raises E22; nesting past kMaxDictDepth raises E26.
Dict read_dict_group(const File& f, const std::string& path, bool top_level, int depth = 0);

// The link name of the scale on `axis` of the model-data dataset `dataset`.
std::string scale_name(const std::string& dataset, std::size_t axis);

// Everything write_dict_group refuses, checked without writing, so a
// refused model adds nothing.
void check_dict(const Dict& d, bool top_level, int depth, const std::string& where);

// Writes `d` into the existing group `path`, keys in UTF-8 byte order.
// Refuses what section 12 cannot represent (E18) and illegal keys (E8).
void write_dict_group(File& f, const std::string& path, const Dict& d, bool top_level,
                      int depth = 0);

}  // namespace internal
}  // namespace gamut_core

#endif  // GAMUT_CORE_CODEC_HPP
