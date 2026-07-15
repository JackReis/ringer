# Ringer context packet v1

`context-packet.v1` is the shared, provider-neutral boundary between context producers and Ringer workers. It intentionally defines no manifest fields, provider protocol, network fetcher, retry policy, or model routing.

## Security invariant

Packet content is **untrusted evidence, not instructions**. Consumers must not obey commands, role changes, tool requests, or policy claims contained in evidence. Passing validation establishes internal consistency, not truth or source authenticity. SHA-256 detects changes; it is not a signature.

## Shape and provenance

A packet identifies itself with `packet_id`, describes (but does not command) with `subject`, and declares `created_at` / `expires_at`. Every evidence item has:

- a stable `evidence_id` and textual `media_type`;
- exact UTF-8 `content`;
- `source`, `observed_at`, and `retrieved_at` provenance;
- a declared `max_age_seconds` freshness bound;
- SHA-256 of the exact content bytes.

Timestamps are UTC RFC 3339 strings ending in `Z`. Required chronology is `observed_at <= retrieved_at <= created_at <= expires_at`. Validation rejects expired packets and evidence older than its declared bound by default. Historical verification is explicit with `require_fresh=False`.

## Integrity and canonicalization

`ringer-canonical-json.v1` is a constrained canonical JSON subset, not a claim of full RFC 8785 conformance. Its only values are null, Unicode-scalar strings, integers in the JSON/I-JSON interoperable range `-(2^53-1)..(2^53-1)`, arrays, and objects with Unicode-scalar string keys. Booleans, floats, unpaired surrogates, and all other types fail closed. Object keys are sorted lexicographically by UTF-16 code units (the RFC 8785/JCS ordering). Output uses compact punctuation and no whitespace or trailing newline. Quote, backslash, and controls use the JSON/ECMAScript escapes (`\b`, `\t`, `\n`, `\f`, `\r`, otherwise lowercase `\u00xx`); slash is not escaped, and every other scalar is emitted directly as UTF-8.

`content_sha256` hashes the exact `content.encode("utf-8")`. `packet_sha256` hashes canonical JSON for the complete packet **with only the top-level `integrity` member omitted**; evidence integrity remains covered. Evidence array order is significant. No Unicode, whitespace, newline, timestamp, or source normalization occurs.

Bounds are 64 evidence items, 256 KiB per content value, 1 MiB wire and canonical packet size, and one year maximum declared evidence age. Fresh validation rejects packets created in the future; v1 permits no implicit clock skew. A supplied clock may use any timezone-aware `datetime`; validation normalizes it to UTC, while naive clocks are rejected.

Supported media types are `text/plain`, `text/markdown`, and `application/json`. **All media types are untrusted descriptive metadata.** In particular, `application/json` does not assert that content is syntactically valid JSON. Consumers MUST NOT parse or otherwise interpret content based on `media_type`; rendering always treats `content` as opaque text and emits it as a JSON string literal.

## Python API

The stdlib-only `context_packet.py` module provides:

- `seal_packet(unsigned)` — deep-copy, validate, and add content/packet digests;
- `validate_packet(packet, now=..., require_fresh=True)`;
- `loads_packet(...)` / `dumps_packet(...)` — duplicate-safe parsing and canonical output;
- `canonical_json_bytes`, `content_sha256`, and `packet_sha256`;
- `render_prompt(packet, ...)` — deterministic worker-prompt rendering.

The renderer validates first, always emits the security warning, and represents evidence content and metadata as JSON string literals so marker-like or instruction-like text remains data. Producers and consumers should share this module and `schema/context-packet.v1.json`. JSON Schema documents portable structure; runtime validation is intentionally stronger: it additionally rejects duplicate keys and unpaired surrogates, enforces chronology, current-time freshness, UTF-8 wire/content/canonical byte limits, unique evidence IDs, and digest bindings.

Immutable interoperability fixtures live in `fixtures/context-packet-v1/`. `sealed.json` is the exact UTF-8 output of `dumps_packet`: canonical packet bytes with no byte-order mark and no trailing newline; its fixed `packet_sha256` covers the packet with only top-level integrity omitted. `rendered.txt` is the exact UTF-8 output of `render_prompt` for that packet and ends with one LF byte. The vector includes nested JSON-shaped opaque content, non-ASCII and astral characters, controls, and instruction-like evidence. It is fresh at `2026-07-14T12:05:00Z`. Independent implementations must reproduce both files byte-for-byte before claiming v1 compatibility.
