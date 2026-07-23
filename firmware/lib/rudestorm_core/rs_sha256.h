/* SHA-256 (FIPS 180-4).
 *
 * Self-contained so the provenance chain works identically on an ESP32-S3, on a
 * host build, and in CI — with no mbedTLS, no ESP-IDF, and no libc beyond
 * string.h. The chain is the audit story; it must not depend on which platform
 * happened to write the record.
 */
#ifndef RS_SHA256_H
#define RS_SHA256_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RS_SHA256_DIGEST_LEN 32
#define RS_SHA256_HEX_LEN 65 /* 64 hex chars + NUL */

typedef struct {
    uint32_t state[8];
    uint64_t bitlen;
    uint8_t buffer[64];
    size_t buflen;
} rs_sha256_ctx;

void rs_sha256_init(rs_sha256_ctx *ctx);
void rs_sha256_update(rs_sha256_ctx *ctx, const void *data, size_t len);
void rs_sha256_final(rs_sha256_ctx *ctx, uint8_t out[RS_SHA256_DIGEST_LEN]);

/* Convenience: hash `data` and write lowercase hex + NUL into `hex`. */
void rs_sha256_hex(const void *data, size_t len, char hex[RS_SHA256_HEX_LEN]);

#ifdef __cplusplus
}
#endif

#endif /* RS_SHA256_H */
