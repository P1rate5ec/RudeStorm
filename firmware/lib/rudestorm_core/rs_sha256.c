#include "rs_sha256.h"

#include <string.h>

#define ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z) (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define EP1(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIG0(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ ((x) >> 3))
#define SIG1(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ ((x) >> 10))

static const uint32_t K[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u,
    0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u,
    0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
    0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au,
    0x5b9cca4fu, 0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

static void rs_sha256_transform(rs_sha256_ctx *ctx, const uint8_t data[64]) {
    uint32_t m[64];
    uint32_t a, b, c, d, e, f, g, h, t1, t2;
    int i;

    for (i = 0; i < 16; ++i) {
        m[i] = ((uint32_t)data[i * 4] << 24) | ((uint32_t)data[i * 4 + 1] << 16) |
               ((uint32_t)data[i * 4 + 2] << 8) | ((uint32_t)data[i * 4 + 3]);
    }
    for (; i < 64; ++i) {
        m[i] = SIG1(m[i - 2]) + m[i - 7] + SIG0(m[i - 15]) + m[i - 16];
    }

    a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5]; g = ctx->state[6]; h = ctx->state[7];

    for (i = 0; i < 64; ++i) {
        t1 = h + EP1(e) + CH(e, f, g) + K[i] + m[i];
        t2 = EP0(a) + MAJ(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
}

void rs_sha256_init(rs_sha256_ctx *ctx) {
    ctx->bitlen = 0;
    ctx->buflen = 0;
    ctx->state[0] = 0x6a09e667u; ctx->state[1] = 0xbb67ae85u;
    ctx->state[2] = 0x3c6ef372u; ctx->state[3] = 0xa54ff53au;
    ctx->state[4] = 0x510e527fu; ctx->state[5] = 0x9b05688cu;
    ctx->state[6] = 0x1f83d9abu; ctx->state[7] = 0x5be0cd19u;
}

void rs_sha256_update(rs_sha256_ctx *ctx, const void *data, size_t len) {
    const uint8_t *p = (const uint8_t *)data;
    size_t i;
    for (i = 0; i < len; ++i) {
        ctx->buffer[ctx->buflen++] = p[i];
        if (ctx->buflen == 64) {
            rs_sha256_transform(ctx, ctx->buffer);
            ctx->bitlen += 512;
            ctx->buflen = 0;
        }
    }
}

void rs_sha256_final(rs_sha256_ctx *ctx, uint8_t out[RS_SHA256_DIGEST_LEN]) {
    size_t i = ctx->buflen;

    /* Pad: 0x80, then zeros, leaving 8 bytes for the length. */
    if (i < 56) {
        ctx->buffer[i++] = 0x80;
        while (i < 56) ctx->buffer[i++] = 0x00;
    } else {
        ctx->buffer[i++] = 0x80;
        while (i < 64) ctx->buffer[i++] = 0x00;
        rs_sha256_transform(ctx, ctx->buffer);
        memset(ctx->buffer, 0, 56);
    }

    ctx->bitlen += (uint64_t)ctx->buflen * 8;
    for (i = 0; i < 8; ++i) {
        ctx->buffer[63 - i] = (uint8_t)(ctx->bitlen >> (i * 8));
    }
    rs_sha256_transform(ctx, ctx->buffer);

    for (i = 0; i < 4; ++i) {
        int j;
        for (j = 0; j < 8; ++j) {
            out[i + j * 4] = (uint8_t)(ctx->state[j] >> (24 - i * 8));
        }
    }
}

void rs_sha256_hex(const void *data, size_t len, char hex[RS_SHA256_HEX_LEN]) {
    static const char digits[] = "0123456789abcdef";
    uint8_t digest[RS_SHA256_DIGEST_LEN];
    rs_sha256_ctx ctx;
    int i;

    rs_sha256_init(&ctx);
    rs_sha256_update(&ctx, data, len);
    rs_sha256_final(&ctx, digest);

    for (i = 0; i < RS_SHA256_DIGEST_LEN; ++i) {
        hex[i * 2] = digits[digest[i] >> 4];
        hex[i * 2 + 1] = digits[digest[i] & 0x0f];
    }
    hex[RS_SHA256_HEX_LEN - 1] = '\0';
}
