# Atlas Platform Operations: Delivery Retry Guidance

Revision 3, effective August 8, 2026

## Required retry schedule

Retry non-2xx deliveries with exponential backoff and full jitter. Do not retry permanent 4xx responses other than 408 and 429.

| Attempt | Maximum delay | Action |
| --- | --- | --- |
| 1-3 | 30 seconds | Automatic retry |
| 4-7 | 15 minutes | Automatic retry and warning metric |
| 8 | 1 hour | Move to dead-letter queue and alert the owner |

## Idempotency

Every delivery includes an `Atlas-Event-Id`. Consumers must safely accept the same ID more than once and return a successful response for already-applied events.

## Recovery

Dead-letter records retain the original payload, event ID, last response, and attempt history for 30 days. Operators may replay them after the receiving system is repaired.
