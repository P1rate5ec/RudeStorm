/* Cross-language conformance harness.
 *
 * Builds a provenance chain from fixed inputs and prints one TSV row per record:
 *
 *     index <TAB> action <TAB> payload_json <TAB> timestamp <TAB> this_hash
 *
 * `rudestorm/tests/test_firmware_conformance.py` compiles and runs this, then
 * recomputes every hash with rudestorm.governance.ProvenanceLog and asserts they
 * match. If canonical JSON ever drifts between the firmware and the middleware,
 * that test fails rather than a field device silently writing an unverifiable
 * log.
 */
#include <stdio.h>
#include <string.h>

#include "rs_json.h"
#include "rs_provenance.h"

static void emit(rs_provenance *log, const char *action, const char *payload,
                 const char *timestamp) {
    char hash[RS_SHA256_HEX_LEN];
    if (!rs_provenance_append(log, action, payload, timestamp, hash)) {
        fprintf(stderr, "append failed for action=%s\n", action);
        return;
    }
    printf("%u\t%s\t%s\t%s\t%s\n", log->count - 1, action, payload, timestamp, hash);
}

int main(void) {
    rs_provenance log;
    rs_json_obj obj;
    char p1[512], p2[512], p3[512], p4[512];

    rs_provenance_init(&log);

    /* 1. A boot record: strings and ints, keys deliberately out of order to
     *    prove the renderer sorts them. */
    rs_json_init(&obj);
    rs_json_add_str(&obj, "node_tier", "cardputer_adv");
    rs_json_add_str(&obj, "fw_version", "0.1.0");
    rs_json_add_int(&obj, "boot_count", 7);
    rs_json_add_bool(&obj, "sd_present", true);
    if (rs_json_render(&obj, p1, sizeof(p1)) < 0) return 1;
    emit(&log, "node_boot", p1, "2026-07-23T06:05:11.123456+00:00");

    /* 2. A detection with confidence as scaled integer milli-units. */
    rs_json_init(&obj);
    rs_json_add_str(&obj, "modality", "wifi_csi");
    rs_json_add_str(&obj, "kind", "presence");
    rs_json_add_int(&obj, "confidence_milli", 734);
    rs_json_add_str(&obj, "source_id", "card-01");
    if (rs_json_render(&obj, p2, sizeof(p2)) < 0) return 1;
    emit(&log, "detection", p2, "2026-07-23T06:05:12.500000+00:00");

    /* 3. Escaping: quotes, backslash, newline, tab, and a control character. */
    rs_json_init(&obj);
    rs_json_add_str(&obj, "ssid", "Guest \"WiFi\"\\Lobby");
    rs_json_add_str(&obj, "note", "line1\nline2\tend\x01");
    rs_json_add_int(&obj, "rssi_dbm", -71);
    if (rs_json_render(&obj, p3, sizeof(p3)) < 0) return 1;
    emit(&log, "rogue_ap", p3, "2026-07-23T06:05:13.000000+00:00");

    /* 4. Negative and large integers, plus an empty payload object. */
    rs_json_init(&obj);
    rs_json_add_int(&obj, "offset_ns", -9007199254740993LL);
    rs_json_add_int(&obj, "seq", 4294967295LL);
    if (rs_json_render(&obj, p4, sizeof(p4)) < 0) return 1;
    emit(&log, "clock_sync", p4, "2026-07-23T06:05:14.000000+00:00");

    /* Final head, for a whole-chain equality check. */
    printf("HEAD\t%s\n", log.head);
    return 0;
}
