/* Canonical JSON writer.
 *
 * Produces byte-identical output to Python's
 *
 *     json.dumps(obj, sort_keys=True, separators=(",", ":"))
 *
 * which is what `rudestorm.governance.ProvenanceLog._digest` hashes. A record
 * written by a Cardputer to its SD card must therefore verify on the Pi with no
 * re-serialization step — the hash chain spans firmware and software.
 *
 * Two deliberate restrictions make that determinism achievable:
 *
 *   1. **No floats.** Python renders floats with repr(), whose shortest
 *      round-trip algorithm is not reproducible in portable C. Numeric values
 *      are integers; a confidence of 0.734 travels as `confidence_milli: 734`.
 *      Nothing in the chain is ever a float.
 *
 *   2. **ASCII only.** Python defaults to ensure_ascii=True, escaping non-ASCII
 *      as \uXXXX. Rather than reimplement UTF-8 decoding on an MCU, non-ASCII
 *      input is rejected at insert time so the mismatch surfaces at the call
 *      site instead of silently forking the chain.
 */
#ifndef RS_JSON_H
#define RS_JSON_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RS_JSON_MAX_FIELDS 16
#define RS_JSON_MAX_KEY 24

typedef enum {
    RS_JSON_INT,
    RS_JSON_STR,
    RS_JSON_BOOL,
    RS_JSON_RAW, /* pre-serialized canonical fragment, e.g. a nested object */
} rs_json_type;

typedef struct {
    char key[RS_JSON_MAX_KEY];
    rs_json_type type;
    int64_t as_int;
    bool as_bool;
    const char *as_str; /* borrowed; must outlive the render call */
} rs_json_field;

typedef struct {
    rs_json_field fields[RS_JSON_MAX_FIELDS];
    size_t count;
    bool overflow; /* set if a field was dropped; render() then fails */
} rs_json_obj;

void rs_json_init(rs_json_obj *obj);

/* Each returns false if the key is invalid, the object is full, or a string
 * value contains non-ASCII. A false return is sticky: render() will also fail,
 * so a caller may batch inserts and check once at the end. */
bool rs_json_add_int(rs_json_obj *obj, const char *key, int64_t value);
bool rs_json_add_str(rs_json_obj *obj, const char *key, const char *value);
bool rs_json_add_bool(rs_json_obj *obj, const char *key, bool value);
bool rs_json_add_raw(rs_json_obj *obj, const char *key, const char *canonical_json);

/* Render into `out`. Returns the number of bytes written (excluding NUL), or
 * -1 on overflow or a prior insert failure. Keys are emitted in byte order,
 * matching Python's sort_keys=True. */
int rs_json_render(const rs_json_obj *obj, char *out, size_t out_len);

/* Escape one string the way json.dumps does. Exposed for testing. */
int rs_json_escape(const char *in, char *out, size_t out_len);

#ifdef __cplusplus
}
#endif

#endif /* RS_JSON_H */
