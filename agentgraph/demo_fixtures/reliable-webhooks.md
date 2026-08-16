# Reliable Webhooks: Idempotency and Replay

Nadia Okafor, August 4, 2026

Treat every webhook as an at-least-once delivery. Correctness starts with a stable event ID and an idempotent consumer.

## Deduplicate at the boundary

Persist the provider's event ID before applying a state change. If the same event arrives again, return success without repeating the work. Keep the deduplication record longer than the provider's maximum retry window.

## Make replay ordinary

Store the original payload and processing outcome so operators can replay an event after a bug fix. A replay should use the same validation and idempotency path as live delivery rather than a privileged bypass.

## Treat ordering as a domain rule

Do not assume network arrival order. Carry a source sequence or version where possible, reject stale transitions explicitly, and surface gaps for investigation.

## Operate the failure path

Measure delivery lag, duplicate rate, retry count, and terminal failures. Pair automatic retry with a dead-letter workflow and enough context for a human to decide whether replay is safe.
