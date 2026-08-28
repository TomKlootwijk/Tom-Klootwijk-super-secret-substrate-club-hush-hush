#pragma once

#include <cstddef>
#include <cstdint>

#if defined(__CUDACC__)
#define SARA363_HD __host__ __device__ __forceinline__
#else
#define SARA363_HD inline
#endif

namespace sara363_cuda {

using byte = std::uint8_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;

SARA363_HD u64 rotr64(u64 x, unsigned n) { return (x >> n) | (x << (64U - n)); }

SARA363_HD u64 load_be64(const byte* p) {
    u64 value = 0;
    for (int i = 0; i < 8; ++i) {
        value = (value << 8U) | static_cast<u64>(p[i]);
    }
    return value;
}

SARA363_HD void store_be64(byte* p, u64 value) {
    for (int i = 7; i >= 0; --i) {
        p[i] = static_cast<byte>(value);
        value >>= 8U;
    }
}

struct Sha512Context {
    u64 state[8];
    byte block[128];
    u64 total_bytes;
    u32 used;
};

SARA363_HD void sha512_transform(Sha512Context& ctx, const byte* block) {
    constexpr u64 k[80] = {
        0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL, 0xb5c0fbcfec4d3b2fULL, 0xe9b5dba58189dbbcULL,
        0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL, 0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL,
        0xd807aa98a3030242ULL, 0x12835b0145706fbeULL, 0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
        0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL, 0x9bdc06a725c71235ULL, 0xc19bf174cf692694ULL,
        0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL, 0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL,
        0x2de92c6f592b0275ULL, 0x4a7484aa6ea6e483ULL, 0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
        0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL, 0xb00327c898fb213fULL, 0xbf597fc7beef0ee4ULL,
        0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL, 0x06ca6351e003826fULL, 0x142929670a0e6e70ULL,
        0x27b70a8546d22ffcULL, 0x2e1b21385c26c926ULL, 0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
        0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL, 0x81c2c92e47edaee6ULL, 0x92722c851482353bULL,
        0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL, 0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL,
        0xd192e819d6ef5218ULL, 0xd69906245565a910ULL, 0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
        0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL, 0x2748774cdf8eeb99ULL, 0x34b0bcb5e19b48a8ULL,
        0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL, 0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL,
        0x748f82ee5defb2fcULL, 0x78a5636f43172f60ULL, 0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
        0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL, 0xbef9a3f7b2c67915ULL, 0xc67178f2e372532bULL,
        0xca273eceea26619cULL, 0xd186b8c721c0c207ULL, 0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL,
        0x06f067aa72176fbaULL, 0x0a637dc5a2c898a6ULL, 0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
        0x28db77f523047d84ULL, 0x32caab7b40c72493ULL, 0x3c9ebe0a15c9bebcULL, 0x431d67c49c100d4cULL,
        0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL, 0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL,
    };

    u64 w[80];
    for (int i = 0; i < 16; ++i) {
        w[i] = load_be64(block + i * 8);
    }
    for (int i = 16; i < 80; ++i) {
        const u64 s0 = rotr64(w[i - 15], 1) ^ rotr64(w[i - 15], 8) ^ (w[i - 15] >> 7U);
        const u64 s1 = rotr64(w[i - 2], 19) ^ rotr64(w[i - 2], 61) ^ (w[i - 2] >> 6U);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }

    u64 a = ctx.state[0];
    u64 b = ctx.state[1];
    u64 c = ctx.state[2];
    u64 d = ctx.state[3];
    u64 e = ctx.state[4];
    u64 f = ctx.state[5];
    u64 g = ctx.state[6];
    u64 h = ctx.state[7];

    for (int i = 0; i < 80; ++i) {
        const u64 s1 = rotr64(e, 14) ^ rotr64(e, 18) ^ rotr64(e, 41);
        const u64 ch = (e & f) ^ ((~e) & g);
        const u64 temp1 = h + s1 + ch + k[i] + w[i];
        const u64 s0 = rotr64(a, 28) ^ rotr64(a, 34) ^ rotr64(a, 39);
        const u64 maj = (a & b) ^ (a & c) ^ (b & c);
        const u64 temp2 = s0 + maj;
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    ctx.state[0] += a;
    ctx.state[1] += b;
    ctx.state[2] += c;
    ctx.state[3] += d;
    ctx.state[4] += e;
    ctx.state[5] += f;
    ctx.state[6] += g;
    ctx.state[7] += h;
}

SARA363_HD void sha512_init(Sha512Context& ctx) {
    ctx.state[0] = 0x6a09e667f3bcc908ULL;
    ctx.state[1] = 0xbb67ae8584caa73bULL;
    ctx.state[2] = 0x3c6ef372fe94f82bULL;
    ctx.state[3] = 0xa54ff53a5f1d36f1ULL;
    ctx.state[4] = 0x510e527fade682d1ULL;
    ctx.state[5] = 0x9b05688c2b3e6c1fULL;
    ctx.state[6] = 0x1f83d9abfb41bd6bULL;
    ctx.state[7] = 0x5be0cd19137e2179ULL;
    ctx.total_bytes = 0;
    ctx.used = 0;
}

SARA363_HD void sha512_update(Sha512Context& ctx, const byte* data, std::size_t length) {
    ctx.total_bytes += static_cast<u64>(length);
    while (length != 0) {
        const std::size_t available = 128U - ctx.used;
        const std::size_t take = length < available ? length : available;
        for (std::size_t i = 0; i < take; ++i) {
            ctx.block[ctx.used + static_cast<u32>(i)] = data[i];
        }
        ctx.used += static_cast<u32>(take);
        data += take;
        length -= take;
        if (ctx.used == 128U) {
            sha512_transform(ctx, ctx.block);
            ctx.used = 0;
        }
    }
}

SARA363_HD void sha512_final(Sha512Context& ctx, byte out[64]) {
    const u64 bit_length_low = ctx.total_bytes << 3U;
    const u64 bit_length_high = ctx.total_bytes >> 61U;
    ctx.block[ctx.used++] = 0x80U;
    if (ctx.used > 112U) {
        while (ctx.used < 128U) {
            ctx.block[ctx.used++] = 0;
        }
        sha512_transform(ctx, ctx.block);
        ctx.used = 0;
    }
    while (ctx.used < 112U) {
        ctx.block[ctx.used++] = 0;
    }
    store_be64(ctx.block + 112, bit_length_high);
    store_be64(ctx.block + 120, bit_length_low);
    sha512_transform(ctx, ctx.block);
    for (int i = 0; i < 8; ++i) {
        store_be64(out + i * 8, ctx.state[i]);
    }
}

SARA363_HD void sha512(const byte* data, std::size_t length, byte out[64]) {
    Sha512Context ctx{};
    sha512_init(ctx);
    sha512_update(ctx, data, length);
    sha512_final(ctx, out);
}

SARA363_HD void hmac_sha512_2(const byte* key,
                              std::size_t key_length,
                              const byte* data_a,
                              std::size_t length_a,
                              const byte* data_b,
                              std::size_t length_b,
                              byte out[64]) {
    byte key_block[128];
    for (int i = 0; i < 128; ++i) {
        key_block[i] = 0;
    }
    if (key_length > 128U) {
        sha512(key, key_length, key_block);
    } else {
        for (std::size_t i = 0; i < key_length; ++i) {
            key_block[i] = key[i];
        }
    }

    byte inner_pad[128];
    byte outer_pad[128];
    for (int i = 0; i < 128; ++i) {
        inner_pad[i] = static_cast<byte>(key_block[i] ^ 0x36U);
        outer_pad[i] = static_cast<byte>(key_block[i] ^ 0x5cU);
    }

    byte inner_digest[64];
    Sha512Context inner{};
    sha512_init(inner);
    sha512_update(inner, inner_pad, 128);
    sha512_update(inner, data_a, length_a);
    if (length_b != 0) {
        sha512_update(inner, data_b, length_b);
    }
    sha512_final(inner, inner_digest);

    Sha512Context outer{};
    sha512_init(outer);
    sha512_update(outer, outer_pad, 128);
    sha512_update(outer, inner_digest, 64);
    sha512_final(outer, out);
}

SARA363_HD void hmac_sha512(const byte* key,
                            std::size_t key_length,
                            const byte* data,
                            std::size_t data_length,
                            byte out[64]) {
    hmac_sha512_2(key, key_length, data, data_length, nullptr, 0, out);
}

SARA363_HD void pbkdf2_hmac_sha512_2048(const byte* password,
                                        std::size_t password_length,
                                        const byte* salt,
                                        std::size_t salt_length,
                                        byte out[64]) {
    const byte block_index[4] = {0, 0, 0, 1};
    byte u[64];
    byte next[64];
    hmac_sha512_2(password, password_length, salt, salt_length, block_index, 4, u);
    for (int i = 0; i < 64; ++i) {
        out[i] = u[i];
    }
    for (int round = 1; round < 2048; ++round) {
        hmac_sha512(password, password_length, u, 64, next);
        for (int i = 0; i < 64; ++i) {
            u[i] = next[i];
            out[i] ^= next[i];
        }
    }
}

struct U256 {
    u32 limb[8]; // little-endian base 2^32
};

SARA363_HD U256 u256_zero() {
    U256 r{};
    for (int i = 0; i < 8; ++i) {
        r.limb[i] = 0;
    }
    return r;
}

SARA363_HD U256 u256_from_be(const byte in[32]) {
    U256 r{};
    for (int i = 0; i < 8; ++i) {
        const int p = 28 - i * 4;
        r.limb[i] = (static_cast<u32>(in[p]) << 24U) | (static_cast<u32>(in[p + 1]) << 16U) |
                    (static_cast<u32>(in[p + 2]) << 8U) | static_cast<u32>(in[p + 3]);
    }
    return r;
}

SARA363_HD void u256_to_be(const U256& value, byte out[32]) {
    for (int i = 0; i < 8; ++i) {
        const u32 word = value.limb[i];
        const int p = 28 - i * 4;
        out[p] = static_cast<byte>(word >> 24U);
        out[p + 1] = static_cast<byte>(word >> 16U);
        out[p + 2] = static_cast<byte>(word >> 8U);
        out[p + 3] = static_cast<byte>(word);
    }
}

SARA363_HD bool u256_is_zero(const U256& a) {
    u32 combined = 0;
    for (int i = 0; i < 8; ++i) {
        combined |= a.limb[i];
    }
    return combined == 0;
}

SARA363_HD int u256_compare(const U256& a, const U256& b) {
    for (int i = 7; i >= 0; --i) {
        if (a.limb[i] < b.limb[i]) {
            return -1;
        }
        if (a.limb[i] > b.limb[i]) {
            return 1;
        }
    }
    return 0;
}

SARA363_HD u32 u256_add_raw(const U256& a, const U256& b, U256& out) {
    u64 carry = 0;
    for (int i = 0; i < 8; ++i) {
        const u64 sum = static_cast<u64>(a.limb[i]) + b.limb[i] + carry;
        out.limb[i] = static_cast<u32>(sum);
        carry = sum >> 32U;
    }
    return static_cast<u32>(carry);
}

SARA363_HD u32 u256_sub_raw(const U256& a, const U256& b, U256& out) {
    u64 borrow = 0;
    for (int i = 0; i < 8; ++i) {
        const u64 subtrahend = static_cast<u64>(b.limb[i]) + borrow;
        const u64 minuend = static_cast<u64>(a.limb[i]);
        out.limb[i] = static_cast<u32>((1ULL << 32U) + minuend - subtrahend);
        borrow = minuend < subtrahend ? 1U : 0U;
    }
    return static_cast<u32>(borrow);
}

SARA363_HD U256 secp_p() {
    U256 p{{0xfffffc2fU, 0xfffffffeU, 0xffffffffU, 0xffffffffU,
            0xffffffffU, 0xffffffffU, 0xffffffffU, 0xffffffffU}};
    return p;
}

SARA363_HD U256 secp_n() {
    U256 n{{0xd0364141U, 0xbfd25e8cU, 0xaf48a03bU, 0xbaaedce6U,
            0xfffffffeU, 0xffffffffU, 0xffffffffU, 0xffffffffU}};
    return n;
}

SARA363_HD U256 reduce_p(const u32 input[16]) {
    u64 acc[18];
    for (int i = 0; i < 18; ++i) {
        acc[i] = 0;
    }
    for (int i = 0; i < 8; ++i) {
        acc[i] = input[i];
    }
    for (int i = 8; i < 16; ++i) {
        acc[i - 8] += static_cast<u64>(input[i]) * 977ULL;
        acc[i - 7] += input[i];
    }

    for (int round = 0; round < 12; ++round) {
        for (int i = 0; i < 17; ++i) {
            const u64 carry = acc[i] >> 32U;
            acc[i] &= 0xffffffffULL;
            acc[i + 1] += carry;
        }
        bool any_high = false;
        for (int i = 8; i < 18; ++i) {
            any_high = any_high || acc[i] != 0;
        }
        if (!any_high) {
            break;
        }
        for (int i = 17; i >= 8; --i) {
            const u64 high = acc[i];
            acc[i] = 0;
            acc[i - 8] += high * 977ULL;
            acc[i - 7] += high;
        }
    }

    U256 r{};
    for (int i = 0; i < 8; ++i) {
        r.limb[i] = static_cast<u32>(acc[i]);
    }
    const U256 p = secp_p();
    if (u256_compare(r, p) >= 0) {
        U256 reduced{};
        u256_sub_raw(r, p, reduced);
        r = reduced;
    }
    return r;
}

SARA363_HD U256 fe_add(const U256& a, const U256& b) {
    U256 low{};
    const u32 carry = u256_add_raw(a, b, low);
    u32 wide[16];
    for (int i = 0; i < 16; ++i) {
        wide[i] = 0;
    }
    for (int i = 0; i < 8; ++i) {
        wide[i] = low.limb[i];
    }
    wide[8] = carry;
    return reduce_p(wide);
}

SARA363_HD U256 fe_sub(const U256& a, const U256& b) {
    U256 result{};
    const u32 borrow = u256_sub_raw(a, b, result);
    const U256 p = secp_p();
    if (borrow != 0) {
        U256 adjusted{};
        u256_add_raw(result, p, adjusted);
        result = adjusted;
    } else if (u256_compare(result, p) >= 0) {
        U256 adjusted{};
        u256_sub_raw(result, p, adjusted);
        result = adjusted;
    }
    return result;
}

SARA363_HD U256 fe_mul(const U256& a, const U256& b) {
    u32 product[16];
    for (int i = 0; i < 16; ++i) {
        product[i] = 0;
    }
    for (int i = 0; i < 8; ++i) {
        u64 carry = 0;
        for (int j = 0; j < 8; ++j) {
            const int k = i + j;
            const u64 current = static_cast<u64>(a.limb[i]) * b.limb[j] + product[k] + carry;
            product[k] = static_cast<u32>(current);
            carry = current >> 32U;
        }
        int k = i + 8;
        while (carry != 0 && k < 16) {
            const u64 current = static_cast<u64>(product[k]) + carry;
            product[k] = static_cast<u32>(current);
            carry = current >> 32U;
            ++k;
        }
    }
    return reduce_p(product);
}

SARA363_HD U256 fe_square(const U256& a) { return fe_mul(a, a); }

SARA363_HD U256 fe_mul_small(const U256& a, unsigned multiplier) {
    U256 result = u256_zero();
    for (unsigned i = 0; i < multiplier; ++i) {
        result = fe_add(result, a);
    }
    return result;
}

SARA363_HD U256 fe_inverse(const U256& a) {
    const U256 exponent{{0xfffffc2dU, 0xfffffffeU, 0xffffffffU, 0xffffffffU,
                         0xffffffffU, 0xffffffffU, 0xffffffffU, 0xffffffffU}};
    U256 result = u256_zero();
    result.limb[0] = 1;
    for (int bit = 255; bit >= 0; --bit) {
        result = fe_square(result);
        if (((exponent.limb[bit / 32] >> (bit % 32)) & 1U) != 0) {
            result = fe_mul(result, a);
        }
    }
    return result;
}

struct JacobianPoint {
    U256 x;
    U256 y;
    U256 z;
};

SARA363_HD U256 generator_x() {
    return U256{{0x16f81798U, 0x59f2815bU, 0x2dce28d9U, 0x029bfcdbU,
                 0xce870b07U, 0x55a06295U, 0xf9dcbbacU, 0x79be667eU}};
}

SARA363_HD U256 generator_y() {
    return U256{{0xfb10d4b8U, 0x9c47d08fU, 0xa6855419U, 0xfd17b448U,
                 0x0e1108a8U, 0x5da4fbfcU, 0x26a3c465U, 0x483ada77U}};
}

SARA363_HD JacobianPoint point_infinity() {
    JacobianPoint p{};
    p.x = u256_zero();
    p.y = u256_zero();
    p.z = u256_zero();
    return p;
}

SARA363_HD bool point_is_infinity(const JacobianPoint& p) { return u256_is_zero(p.z); }

SARA363_HD JacobianPoint point_double(const JacobianPoint& p) {
    if (point_is_infinity(p) || u256_is_zero(p.y)) {
        return point_infinity();
    }
    const U256 a = fe_square(p.x);
    const U256 b = fe_square(p.y);
    const U256 c = fe_square(b);
    const U256 x_plus_b = fe_add(p.x, b);
    const U256 d = fe_mul_small(fe_sub(fe_sub(fe_square(x_plus_b), a), c), 2);
    const U256 e = fe_mul_small(a, 3);
    const U256 f = fe_square(e);
    JacobianPoint result{};
    result.x = fe_sub(f, fe_mul_small(d, 2));
    result.y = fe_sub(fe_mul(e, fe_sub(d, result.x)), fe_mul_small(c, 8));
    result.z = fe_mul_small(fe_mul(p.y, p.z), 2);
    return result;
}

SARA363_HD JacobianPoint point_add_generator(const JacobianPoint& p) {
    const U256 gx = generator_x();
    const U256 gy = generator_y();
    if (point_is_infinity(p)) {
        JacobianPoint result{};
        result.x = gx;
        result.y = gy;
        result.z = u256_zero();
        result.z.limb[0] = 1;
        return result;
    }
    const U256 z1z1 = fe_square(p.z);
    const U256 u2 = fe_mul(gx, z1z1);
    const U256 s2 = fe_mul(gy, fe_mul(p.z, z1z1));
    const U256 h = fe_sub(u2, p.x);
    const U256 hh = fe_square(h);
    const U256 i = fe_mul_small(hh, 4);
    const U256 j = fe_mul(h, i);
    const U256 r = fe_mul_small(fe_sub(s2, p.y), 2);
    const U256 v = fe_mul(p.x, i);

    if (u256_is_zero(h)) {
        return u256_is_zero(fe_sub(s2, p.y)) ? point_double(p) : point_infinity();
    }

    JacobianPoint result{};
    result.x = fe_sub(fe_sub(fe_square(r), j), fe_mul_small(v, 2));
    result.y = fe_sub(fe_mul(r, fe_sub(v, result.x)), fe_mul_small(fe_mul(p.y, j), 2));
    result.z = fe_sub(fe_sub(fe_square(fe_add(p.z, h)), z1z1), hh);
    return result;
}

SARA363_HD bool secp256k1_compressed(const U256& scalar, byte out[33]) {
    const U256 n = secp_n();
    if (u256_is_zero(scalar) || u256_compare(scalar, n) >= 0) {
        return false;
    }
    JacobianPoint q = point_infinity();
    for (int bit = 255; bit >= 0; --bit) {
        q = point_double(q);
        if (((scalar.limb[bit / 32] >> (bit % 32)) & 1U) != 0) {
            q = point_add_generator(q);
        }
    }
    if (point_is_infinity(q)) {
        return false;
    }
    const U256 z_inverse = fe_inverse(q.z);
    const U256 z_inverse2 = fe_square(z_inverse);
    const U256 affine_x = fe_mul(q.x, z_inverse2);
    const U256 affine_y = fe_mul(q.y, fe_mul(z_inverse2, z_inverse));
    out[0] = static_cast<byte>(0x02U | (affine_y.limb[0] & 1U));
    u256_to_be(affine_x, out + 1);
    return true;
}

SARA363_HD bool scalar_add_mod_n(const U256& a, const U256& b, U256& result) {
    const U256 n = secp_n();
    U256 sum{};
    const u32 carry = u256_add_raw(a, b, sum);
    if (carry != 0 || u256_compare(sum, n) >= 0) {
        U256 reduced{};
        u256_sub_raw(sum, n, reduced);
        sum = reduced;
    }
    result = sum;
    return !u256_is_zero(result);
}

struct ExtendedPrivateKey {
    byte private_key[32];
    byte chain_code[32];
    byte public_key[33];
    u32 valid;
};

SARA363_HD ExtendedPrivateKey bip32_master(const byte* seed, std::size_t seed_length) {
    constexpr byte key[] = {'B', 'i', 't', 'c', 'o', 'i', 'n', ' ', 's', 'e', 'e', 'd'};
    byte digest[64];
    hmac_sha512(key, sizeof(key), seed, seed_length, digest);
    ExtendedPrivateKey result{};
    for (int i = 0; i < 32; ++i) {
        result.private_key[i] = digest[i];
        result.chain_code[i] = digest[i + 32];
    }
    const U256 scalar = u256_from_be(result.private_key);
    result.valid = secp256k1_compressed(scalar, result.public_key) ? 1U : 0U;
    return result;
}

SARA363_HD ExtendedPrivateKey bip32_ckd_private(const ExtendedPrivateKey& parent, u32 index) {
    ExtendedPrivateKey result{};
    if (parent.valid == 0) {
        return result;
    }

    byte data[37];
    if (index >= 0x80000000U) {
        data[0] = 0;
        for (int i = 0; i < 32; ++i) {
            data[i + 1] = parent.private_key[i];
        }
    } else {
        for (int i = 0; i < 33; ++i) {
            data[i] = parent.public_key[i];
        }
    }
    data[33] = static_cast<byte>(index >> 24U);
    data[34] = static_cast<byte>(index >> 16U);
    data[35] = static_cast<byte>(index >> 8U);
    data[36] = static_cast<byte>(index);

    byte digest[64];
    hmac_sha512(parent.chain_code, 32, data, 37, digest);
    const U256 left = u256_from_be(digest);
    const U256 n = secp_n();
    if (u256_compare(left, n) >= 0) {
        return result;
    }
    const U256 parent_scalar = u256_from_be(parent.private_key);
    U256 child_scalar{};
    if (!scalar_add_mod_n(left, parent_scalar, child_scalar)) {
        return result;
    }
    u256_to_be(child_scalar, result.private_key);
    for (int i = 0; i < 32; ++i) {
        result.chain_code[i] = digest[i + 32];
    }
    result.valid = secp256k1_compressed(child_scalar, result.public_key) ? 1U : 0U;
    return result;
}

} // namespace sara363_cuda

#undef SARA363_HD
