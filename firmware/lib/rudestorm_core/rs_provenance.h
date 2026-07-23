/* Hash-chained provenance, wire-compatible with rudestorm.governance.ProvenanceLog.
 *
 * Each record embeds the SHA-256 of its predecessor, so deleting or editing any
 * record breaks the chain detectably. The digest is taken over the canonical
 * JSON of:
 *
 *     {"action":...,"index":...,"payload":...,"prev_hash":...,"timestamp":...}
 *
 * with keys in byte order, exactly as `ProvenanceLog._digest` produces it. That
 * equivalence is the point: a Cardputer records events to its SD card while
 * offline, and when it later syncs, the Pi verifies the chain with the same code
 * path it uses for its own records. Custody survives the handoff.
 *
 * The chain is tamper-*evident*, not tamper-proof: anyone holding the device can
 * rewrite the whole log from genesis. Ed25519 signing over the head hash is what
 * makes a record attributable, and belongs on top of this, not inside it.
 */
#ifndef RS_PROVENANCE_H
#define RS_PROVENANCE_H

#include <stdbool.h>
#include <stddef.h>

#include "rs_json.h"
#include "rs_sha256.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 64 zeros — must match rudestorm.governance.GENESIS. */
extern const char RS_GENESIS[RS_SHA256_HEX_LEN];

typedef struct {
    char head[RS_SHA256_HEX_LEN];
    uint32_t count;
} rs_provenance;

void rs_provenance_init(rs_provenance *log);

/* Append one record and advance the head.
 *
 * `timestamp` must be an ISO-8601 UTC string matching what Python's
 * datetime.isoformat() produces, e.g. "2026-07-23T06:05:11.123456+00:00".
 * `payload_json` is a canonical JSON object (from rs_json_render).
 *
 * On success, writes the new head into `out_hash` and returns true. Returns
 * false without mutating the log if serialization overflows — a record that
 * cannot be hashed must never be silently dropped from the chain.
 */
bool rs_provenance_append(rs_provenance *log, const char *action,
                          const char *payload_json, const char *timestamp,
                          char out_hash[RS_SHA256_HEX_LEN]);

/* Compute a record's digest without mutating a log. Used to verify a chain
 * read back from SD, and by the cross-language conformance test. */
bool rs_provenance_digest(uint32_t index, const char *timestamp,
                          const char *action, const char *payload_json,
                          const char *prev_hash, char out_hash[RS_SHA256_HEX_LEN]);

#ifdef __cplusplus
}
#endif

#endif /* RS_PROVENANCE_H */
