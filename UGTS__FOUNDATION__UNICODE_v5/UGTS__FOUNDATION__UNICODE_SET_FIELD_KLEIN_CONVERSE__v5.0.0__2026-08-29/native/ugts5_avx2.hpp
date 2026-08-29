#pragma once

// Optional AVX2 extraction profile. The scalar PackedNode32 codec remains the
// conformance oracle. Per-node parity may be verified scalar or by a separately
// validated vector popcount routine; merely extracting bit 31 is not verification.

#ifdef __AVX2__
#include <immintrin.h>
#include <cstdint>

namespace ugts5 {

struct Decoded8 {
    __m256i family;
    __m256i kappa;
    __m256i delta_rho_u8;
    __m256i delta_theta;
    __m256i grammar_path;
    __m256i local_flags;
    __m256i active;
};

inline Decoded8 decode8(const std::uint32_t* words) noexcept {
    const __m256i raw = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(words));
    const __m256i mask1 = _mm256_set1_epi32(0x01);
    const __m256i mask3 = _mm256_set1_epi32(0x03);
    const __m256i mask7 = _mm256_set1_epi32(0x07);
    const __m256i maskff = _mm256_set1_epi32(0xff);
    const __m256i op = _mm256_and_si256(_mm256_srli_epi32(raw, 27), _mm256_set1_epi32(0x0f));
    return {
        _mm256_and_si256(_mm256_srli_epi32(op, 1), mask7),
        _mm256_and_si256(op, mask1),
        _mm256_and_si256(_mm256_srli_epi32(raw, 19), maskff),
        _mm256_and_si256(_mm256_srli_epi32(raw, 11), maskff),
        _mm256_and_si256(_mm256_srli_epi32(raw, 3), maskff),
        _mm256_and_si256(_mm256_srli_epi32(raw, 1), mask3),
        _mm256_and_si256(raw, mask1),
    };
}

inline __m256i expand_boolean_mask(__m256i zero_or_one) noexcept {
    // 0 -> 0x00000000, 1 -> 0xffffffff. This is suitable for lane-wise
    // AND/ANDNOT/OR selection and avoids passing 0/1 directly to blendv.
    return _mm256_sub_epi32(_mm256_setzero_si256(), zero_or_one);
}

inline __m256i select_epi32(__m256i full_mask, __m256i when_true, __m256i when_false) noexcept {
    return _mm256_or_si256(_mm256_and_si256(full_mask, when_true), _mm256_andnot_si256(full_mask, when_false));
}

}  // namespace ugts5
#endif
