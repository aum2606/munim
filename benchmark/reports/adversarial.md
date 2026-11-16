# Adversarial price suite

| Metric | Result | Target |
|---|---|---|
| Price-hallucination rate (wrong amount got through) | 0 / 1384 (0.00%) | 0 |
| Leak rate (instructions got through) | 0 / 100 (0.00%) | 0 |
| False-positive rate (honest reply blocked) | 0 / 51 (0.00%) | 0 |

Attacks are replies a misbehaving model could send, run through the outbound guardrail.
They do not exercise a real model: that run needs provider keys (`make eval`).
