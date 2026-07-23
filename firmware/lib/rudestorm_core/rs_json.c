#include "rs_json.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void rs_json_init(rs_json_obj *obj) {
    memset(obj, 0, sizeof(*obj));
}

static bool is_ascii_printable_or_ctrl(const char *s) {
    for (; *s; ++s) {
        if ((unsigned char)*s > 0x7f) return false;
    }
    return true;
}

static rs_json_field *claim(rs_json_obj *obj, const char *key) {
    rs_json_field *f;
    if (obj->count >= RS_JSON_MAX_FIELDS || key == NULL ||
        strlen(key) >= RS_JSON_MAX_KEY || key[0] == '\0') {
        obj->overflow = true;
        return NULL;
    }
    f = &obj->fields[obj->count++];
    memset(f, 0, sizeof(*f));
    /* Length already checked against RS_JSON_MAX_KEY. */
    memcpy(f->key, key, strlen(key) + 1);
    return f;
}

bool rs_json_add_int(rs_json_obj *obj, const char *key, int64_t value) {
    rs_json_field *f = claim(obj, key);
    if (!f) return false;
    f->type = RS_JSON_INT;
    f->as_int = value;
    return true;
}

bool rs_json_add_str(rs_json_obj *obj, const char *key, const char *value) {
    rs_json_field *f;
    if (value == NULL || !is_ascii_printable_or_ctrl(value)) {
        obj->overflow = true;
        return false;
    }
    f = claim(obj, key);
    if (!f) return false;
    f->type = RS_JSON_STR;
    f->as_str = value;
    return true;
}

bool rs_json_add_bool(rs_json_obj *obj, const char *key, bool value) {
    rs_json_field *f = claim(obj, key);
    if (!f) return false;
    f->type = RS_JSON_BOOL;
    f->as_bool = value;
    return true;
}

bool rs_json_add_raw(rs_json_obj *obj, const char *key, const char *canonical_json) {
    rs_json_field *f;
    if (canonical_json == NULL || !is_ascii_printable_or_ctrl(canonical_json)) {
        obj->overflow = true;
        return false;
    }
    f = claim(obj, key);
    if (!f) return false;
    f->type = RS_JSON_RAW;
    f->as_str = canonical_json;
    return true;
}

int rs_json_escape(const char *in, char *out, size_t out_len) {
    static const char hex[] = "0123456789abcdef";
    size_t o = 0;

#define PUT(c)                       \
    do {                             \
        if (o + 1 >= out_len) return -1; \
        out[o++] = (char)(c);        \
    } while (0)

    for (; *in; ++in) {
        unsigned char c = (unsigned char)*in;
        switch (c) {
            case '"':  PUT('\\'); PUT('"');  break;
            case '\\': PUT('\\'); PUT('\\'); break;
            case '\n': PUT('\\'); PUT('n');  break;
            case '\r': PUT('\\'); PUT('r');  break;
            case '\t': PUT('\\'); PUT('t');  break;
            case '\b': PUT('\\'); PUT('b');  break;
            case '\f': PUT('\\'); PUT('f');  break;
            default:
                if (c < 0x20) {
                    /* json.dumps emits \u00xx for other control characters. */
                    PUT('\\'); PUT('u'); PUT('0'); PUT('0');
                    PUT(hex[(c >> 4) & 0x0f]);
                    PUT(hex[c & 0x0f]);
                } else {
                    PUT(c);
                }
        }
    }
#undef PUT
    if (o >= out_len) return -1;
    out[o] = '\0';
    return (int)o;
}

static int cmp_field(const void *a, const void *b) {
    return strcmp(((const rs_json_field *)a)->key, ((const rs_json_field *)b)->key);
}

int rs_json_render(const rs_json_obj *obj, char *out, size_t out_len) {
    rs_json_field sorted[RS_JSON_MAX_FIELDS];
    size_t i, o = 0;

    if (obj->overflow) return -1;

    memcpy(sorted, obj->fields, obj->count * sizeof(rs_json_field));
    /* Python's sort_keys sorts by Unicode code point; for ASCII that is
     * byte order, which is exactly what strcmp gives. */
    qsort(sorted, obj->count, sizeof(rs_json_field), cmp_field);

#define EMIT(str)                                       \
    do {                                                \
        size_t _n = strlen(str);                        \
        if (o + _n + 1 >= out_len) return -1;           \
        memcpy(out + o, (str), _n);                     \
        o += _n;                                        \
    } while (0)
#define EMIT_CH(c)                                      \
    do {                                                \
        if (o + 2 >= out_len) return -1;                \
        out[o++] = (char)(c);                           \
    } while (0)

    EMIT_CH('{');
    for (i = 0; i < obj->count; ++i) {
        char scratch[256];
        const rs_json_field *f = &sorted[i];

        if (i > 0) EMIT_CH(',');

        if (rs_json_escape(f->key, scratch, sizeof(scratch)) < 0) return -1;
        EMIT_CH('"'); EMIT(scratch); EMIT_CH('"');
        EMIT_CH(':');

        switch (f->type) {
            case RS_JSON_INT:
                snprintf(scratch, sizeof(scratch), "%" PRId64, f->as_int);
                EMIT(scratch);
                break;
            case RS_JSON_BOOL:
                EMIT(f->as_bool ? "true" : "false");
                break;
            case RS_JSON_STR:
                if (rs_json_escape(f->as_str, scratch, sizeof(scratch)) < 0) return -1;
                EMIT_CH('"'); EMIT(scratch); EMIT_CH('"');
                break;
            case RS_JSON_RAW:
                EMIT(f->as_str);
                break;
        }
    }
    EMIT_CH('}');

#undef EMIT
#undef EMIT_CH

    out[o] = '\0';
    return (int)o;
}
