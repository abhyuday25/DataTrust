# DataTrust scripted evaluation

Run: 2026-10-03T19:34:20.196505+00:00
Benchmark: 253880c2ac32
Dataset version: 01247c3b67387872c493e52832371b53e50eceb7815c453ff103b770bf0d39d2
Schema hash: 50e4747e0a5b29add772db13a49142147764fa998741ed492d7ffb825cdf10ce

Measures pipeline controls with scripted model outputs, not Ollama answer quality

## Summary

- cases: 19
- execution_accuracy: 1.0
- result_accuracy: 1.0
- schema_accuracy: 1.0
- security_rejection_rate: 1.0
- false_block_rate: 0.0
- cache_hit_rate: 0.09090909090909091
- repair_success_rate: 1.0
- p50_latency_ms: 106.98
- p95_latency_ms: 363.66

## Categories

- easy: 4/4 passed
- medium: 3/3 passed
- hard: 1/1 passed
- repair: 1/1 passed
- schema: 1/1 passed
- out_of_domain: 1/1 passed
- ambiguous: 1/1 passed
- adversarial: 4/4 passed
- multi_turn: 2/2 passed
- cache: 1/1 passed

## Failures

- Failed cases: none
- Security failures: none
- False blocks: none
- Repair outcomes: 1/1 recovered
