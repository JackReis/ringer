# Provider Protocol v1

`provider-protocol.v1` is a closed, external transport envelope around an untouched, sealed `context-packet.v1`. The packet remains independently validated by `context_packet.validate_packet`; envelope metadata is never inserted into, stripped from, or used to reseal the packet.

Required metadata comprises `envelope_id`, `provider_id`, `model_id`, and `request_id`. Each is a 1–128 character identifier matching `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. Transport authentication, provider SDKs, networking, credentials, and arbitrary provider options are out of scope.

Use `make_envelope`, `validate_envelope`, `loads_envelope`, and `dumps_envelope`. `refresh_envelope` historically validates an old envelope, invokes a `ProviderAdapter` exactly once with an isolated previous-packet copy, then fresh-validates and isolates the returned sealed packet. Adapter failures produce `ProviderProtocolAdapterError` with the cause chained; there is no retry or partial result.

The wire limit is 1,310,720 bytes and is checked before parsing. Parsing rejects duplicate keys at every depth, malformed UTF-8/JSON, floating/non-finite numbers, surrogates, and non-object roots. Dumps are deterministic Ringer canonical JSON and intentionally disable freshness while retaining structural and integrity checks.

## CLI

```sh
python3 provider_protocol.py validate ENVELOPE.json \
  --envelope-id ENV --provider-id PROVIDER --model-id MODEL \
  --request-id REQUEST --now 2026-07-14T12:05:00Z
```

The command independently validates the nested packet and fails nonzero with a diagnostic if any expected identifier differs.
