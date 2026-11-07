#ifndef AOS_DEMO_PROFILE_H
#define AOS_DEMO_PROFILE_H

#include <stdint.h>
#include <string.h>

namespace aos_demo_profile {

static const uint32_t kRequiredSpi = 0x1234;
static const uint8_t kRequiredPrimaryHeader[6] = {
    0x69, 0x52, 0x12, 0x34, 0x56, 0x4a
};

// Return a route-ready error code, or nullptr when the fixed frame profile
// matches. The Data Field is deliberately variable and validated separately
// using its explicit UTF-8 length prefix.
inline const char *validateFixedProfile(uint32_t spi, const uint8_t *primaryHeader) {
  if (spi == 0 || spi == 0xffff) return "spi_must_not_be_reserved";
  if (spi != kRequiredSpi) return "spi_must_match_fixed_profile_0x1234";
  if (primaryHeader == nullptr ||
      memcmp(primaryHeader, kRequiredPrimaryHeader, sizeof(kRequiredPrimaryHeader)) != 0) {
    return "primary_header_must_match_fixed_profile_69521234564a";
  }
  return nullptr;
}

}  // namespace aos_demo_profile

#endif  // AOS_DEMO_PROFILE_H
