"""The firmware and the middleware must produce identical provenance chains.

A Cardputer logs events to SD while offline; the Pi verifies that log on sync
using `ProvenanceLog`. If the two ever disagree on canonical JSON — key order,
string escaping, integer formatting — every field record becomes unverifiable,
and it fails silently, because a wrong hash looks exactly like a tampered one.

This test compiles `firmware/test/conformance_main.c` with the host compiler and
recomputes each record's digest in Python. It is skipped, not failed, where no C
compiler exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rudestorm.governance import GENESIS, ProvenanceLog

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
CORE = FIRMWARE / "lib" / "rudestorm_core"
HARNESS = FIRMWARE / "test" / "conformance_main.c"

pytestmark = pytest.mark.skipif(
    shutil.which("cc") is None, reason="no host C compiler available"
)


@pytest.fixture(scope="module")
def chain(tmp_path_factory) -> list[dict]:
    """Compile and run the firmware harness; return its emitted records."""
    out = tmp_path_factory.mktemp("fwconf") / "conformance"
    sources = [str(HARNESS), *(str(p) for p in sorted(CORE.glob("*.c")))]
    compile_cmd = ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                   f"-I{CORE}", "-o", str(out), *sources]

    proc = subprocess.run(compile_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"firmware core failed to compile:\n{proc.stderr}"

    run = subprocess.run([str(out)], capture_output=True, text=True)
    assert run.returncode == 0, f"harness failed:\n{run.stderr}"

    records, head = [], None
    for line in run.stdout.strip().splitlines():
        parts = line.split("\t")
        if parts[0] == "HEAD":
            head = parts[1]
            continue
        records.append({
            "index": int(parts[0]),
            "action": parts[1],
            "payload_json": parts[2],
            "timestamp": parts[3],
            "hash": parts[4],
        })
    assert head is not None, "harness did not emit a HEAD line"
    assert records, "harness emitted no records"
    records[-1]["head"] = head
    return records


class TestCanonicalJson:
    def test_firmware_payloads_are_canonical(self, chain):
        """Every payload must equal Python's canonical rendering of itself."""
        for rec in chain:
            parsed = json.loads(rec["payload_json"])
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            assert rec["payload_json"] == canonical, (
                f"record {rec['index']} ({rec['action']}) is not canonical:\n"
                f"  firmware: {rec['payload_json']}\n"
                f"  python:   {canonical}"
            )

    def test_keys_are_sorted_not_insertion_ordered(self, chain):
        """The boot record is inserted out of order on purpose."""
        boot = next(r for r in chain if r["action"] == "node_boot")
        keys = list(json.loads(boot["payload_json"]).keys())
        assert keys == sorted(keys)
        assert keys[0] == "boot_count"  # inserted third

    def test_escaping_matches_python(self, chain):
        rogue = next(r for r in chain if r["action"] == "rogue_ap")
        payload = json.loads(rogue["payload_json"])
        assert payload["ssid"] == 'Guest "WiFi"\\Lobby'
        assert payload["note"] == "line1\nline2\tend\x01"
        # \x01 has no short form; json.dumps emits .
        assert "\\u0001" in rogue["payload_json"]

    def test_large_and_negative_integers_round_trip(self, chain):
        sync = next(r for r in chain if r["action"] == "clock_sync")
        payload = json.loads(sync["payload_json"])
        assert payload["offset_ns"] == -9007199254740993
        assert payload["seq"] == 4294967295


class TestChainEquivalence:
    def test_each_record_digest_matches_python(self, chain):
        prev = GENESIS
        for rec in chain:
            expected = ProvenanceLog._digest(
                rec["index"],
                rec["timestamp"],
                rec["action"],
                json.loads(rec["payload_json"]),
                prev,
            )
            assert rec["hash"] == expected, (
                f"digest divergence at record {rec['index']} ({rec['action']})"
            )
            prev = rec["hash"]

    def test_final_head_matches(self, chain):
        assert chain[-1]["head"] == chain[-1]["hash"]

    def test_python_verifies_a_firmware_written_chain(self, chain):
        """Replay the firmware's records into a ProvenanceLog and verify()."""
        log = ProvenanceLog()
        for rec in chain:
            log.append(rec["action"], json.loads(rec["payload_json"]))
        assert log.verify()

    def test_a_tampered_firmware_record_is_detected(self, chain):
        """Changing one byte of a payload must break the chain."""
        prev = GENESIS
        first = chain[0]
        tampered = json.loads(first["payload_json"])
        tampered["boot_count"] = 8  # was 7
        digest = ProvenanceLog._digest(
            first["index"], first["timestamp"], first["action"], tampered, prev
        )
        assert digest != first["hash"]
