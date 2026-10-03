# Repair loop

The initial SQL is guarded and executed. Only repairable execution errors (syntax, schema or type) trigger Repair Agent. At most `MAX_REPAIR_ATTEMPTS` repairs are generated, default 2. Each candidate passes the same guard before execution. A guard rejection stops immediately, including for repaired SQL. Timeout, policy rejection and internal errors do not trigger repair. The API exposes the final SQL, validation result, safe error and repair count; stage timings include each repair and validation.

```text
Generated SQL → SQL Guard → ApprovedQuery → Execute
                                       failure: classify
                                       repairable → Repair Agent → SAME SQL Guard → Execute
                                       maximum two repairs → safe final failure
```

Repairable categories are syntax, schema, type and aggregation errors. The repair prompt receives the question, plan, bounded evidence, failed SQL, safe error code and attempt number. It does not receive a policy override or a raw database traceback. Tests cover successful first and second repairs, exhausted repairs, and an unsafe repair rejected by the same guard.
