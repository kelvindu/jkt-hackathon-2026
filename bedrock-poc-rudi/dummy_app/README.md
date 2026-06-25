# dummy_app

Demo application fixtures used by the Bedrock investigation agent.

## Live demo (one command)

From the project root:

```bash
python demo.py
```

This runs `alerts/demo_live.json` which maps to `services/orders.py`.

## Incident alignment

| Incident ID | Bug in code | Alert file |
|---|---|---|
| **inc_43** | `requests.get()` with no `timeout=` | `alerts/demo_live.json` |
| **inc_13** | N+1 HTTP loop — one call per order | `alerts/demo_live.json` |

## Intentional bugs in `services/orders.py`

- **Missing HTTP timeouts** on every `requests.get()` call (inc_43)
- **N+1 query pattern** — `get_orders_with_details()` loops one HTTP request per order (inc_13)

## Expected agent fix

1. Add `timeout=5` (or similar) to all `requests.get()` calls
2. Batch line-item fetches instead of looping per order
3. Open a GitHub PR via `create_github_pr`
4. Include PR URL in the RCA summary
