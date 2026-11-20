# Adversarial suite: prices, contacts and prompt leaks

| Metric | Result | Target |
|---|---|---|
| Price-hallucination rate (a wrong amount got through) | 0 / 1384 (0.00%) | 0 |
| Contact-fraud rate (a stranger's number, link or account got through) | 0 / 316 (0.00%) | 0 |
| Leak rate (instructions got through) | 0 / 263 (0.00%) | 0 |
| False-positive rate (an honest reply was blocked) | 0 / 65 (0.00%) | 0 |

Attacks are replies a misbehaving model could send, run through the outbound
guardrail. They do not exercise a real model: that run needs provider keys.
