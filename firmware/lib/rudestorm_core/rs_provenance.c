#include "rs_provenance.h"

#include <string.h>

const char RS_GENESIS[RS_SHA256_HEX_LEN] =
    "0000000000000000000000000000000000000000000000000000000000000000";

/* One record's canonical JSON. Sized for a 512-byte payload plus the fixed
 * fields; the ESP32 has 512 KB of SRAM, so this sits comfortably on the stack
 * of a normal task but is too large for an ISR — append from a task context. */
#define RS_RECORD_BUF 1024

void rs_provenance_init(rs_provenance *log) {
    memcpy(log->head, RS_GENESIS, RS_SHA256_HEX_LEN);
    log->count = 0;
}

bool rs_provenance_digest(uint32_t index, const char *timestamp,
                          const char *action, const char *payload_json,
                          const char *prev_hash, char out_hash[RS_SHA256_HEX_LEN]) {
    rs_json_obj rec;
    char buf[RS_RECORD_BUF];
    int len;

    rs_json_init(&rec);
    /* Insertion order is irrelevant — rs_json_render sorts by key, matching
     * Python's sort_keys=True. Listed here in the sorted order for clarity. */
    rs_json_add_str(&rec, "action", action);
    rs_json_add_int(&rec, "index", (int64_t)index);
    rs_json_add_raw(&rec, "payload", payload_json);
    rs_json_add_str(&rec, "prev_hash", prev_hash);
    rs_json_add_str(&rec, "timestamp", timestamp);

    len = rs_json_render(&rec, buf, sizeof(buf));
    if (len < 0) return false;

    rs_sha256_hex(buf, (size_t)len, out_hash);
    return true;
}

bool rs_provenance_append(rs_provenance *log, const char *action,
                          const char *payload_json, const char *timestamp,
                          char out_hash[RS_SHA256_HEX_LEN]) {
    char next[RS_SHA256_HEX_LEN];

    if (!rs_provenance_digest(log->count, timestamp, action, payload_json,
                              log->head, next)) {
        return false;
    }

    memcpy(log->head, next, RS_SHA256_HEX_LEN);
    log->count++;
    if (out_hash) memcpy(out_hash, next, RS_SHA256_HEX_LEN);
    return true;
}
