# MunimBench datasheet

MunimBench is an open benchmark of customer enquiries sent to small Indian businesses, written in
English, Hindi (Devanagari), Gujarati (script), Hinglish and Gujlish (romanised Hindi and
Gujarati). It tests whether an assistant answers from a shop's own data without inventing prices.

**Status:** version 0.1, 100 items (Phase 1). It grows to 300 to 500 items plus audio in Phase 4.

## What is in it

`items/*.yaml`, one list per vertical. Each item:

| Field | Meaning |
|---|---|
| `id`, `vertical` | `printing` or `photography` |
| `language`, `script` | how the customer wrote it |
| `text` | the customer's message |
| `intent` | the gold intent (same labels as the Router agent) |
| `terms` | product names a router should extract, in Latin letters |
| `expect.grounded` | can the shop's data answer it? If not, the right reply is "I'll confirm with the team" |
| `expect.skus` / `expect.faq` | the catalogue items or FAQ a correct answer is based on |
| `expect.price_paise` | the only rupee amounts a reply may contain (integer paise) |
| `handoff` | should a human take over (complaints, haggling, asking for the owner)? |
| `semantic` | the answer can only be found with multilingual embeddings, not word overlap |
| `note` | `injection` marks prompt-injection and price-manipulation attempts |

The shop data the items refer to is in `backend/seeds/data.py`. It is entirely invented.

## Metrics

- **price accuracy**: every amount in a reply is in `expect.price_paise`; a pricing reply shows all
  of them. Must be 100%. `hallucinated_amounts` counts amounts that were not allowed. Must be 0.
- **handoff accuracy**: the conversation was handed to a human exactly when `handoff` says so.
- **groundedness**: the bot answered when it could and said it would check when it could not.
- **retrieval hit rate**: the evidence given to the model contained the expected SKUs or FAQ.
- **intent accuracy**: the router's intent equals the gold intent (real models only).

## How the items were made

Written and checked by the project team from common enquiry patterns for print shops and
photographers. Phrasings are templated per language in this first version, so they are cleaner
than real customer messages. Version 0.2 will add messier, real-style text.

## Known limits and biases

- Two verticals only. Gujarati and Hindi phrasing is limited to what the authors wrote.
- No real customer messages were used. Never add any: the benchmark must contain no personal data.
- The `oracle` run (used in CI) answers from the gold labels, so it checks the system around the
  model, not model quality. Compare models with `make eval LLM=real EMB=local`.

## Licence

Items and this datasheet: CC BY 4.0.
