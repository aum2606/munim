# MunimBench datasheet

MunimBench is an open benchmark of customer enquiries sent to small Indian businesses, written in
English, Hindi (Devanagari), Gujarati (script), Hinglish and Gujlish (romanised Hindi and
Gujarati). It tests whether an assistant answers from a shop's own data without inventing prices.

**Status:** version 0.2, 367 items in 5 languages (101 English, 72 Hinglish, 67 Hindi, 66 Gujlish, 61 Gujarati) over two shops. Audio clips and quote conversations are not in yet.

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
- **route accuracy**: the router's intent sends the message to the same place as the gold intent
  (real models only). Several intents (policy, availability, product_info, general_faq, pricing)
  lead to the same place, so this is what the customer experiences; intent accuracy is stricter.
- **intent accuracy**: the router's intent equals the gold intent (real models only).
- **unrequested prices**: real catalogue prices a reply shows that the question did not ask for
  (not hallucinations, but imprecise). `hallucinated_amounts` counts only amounts the shop never
  charged.
- **model errors**: items where a model call failed (rate limit, bad output). Not the model's
  judgement; a run with many is not a fair measurement.

## How the items were made

Version 0.1 (items 001-100 per shop) was written by the project team from common enquiry
patterns. Version 0.2 adds 267 items made by `benchmark/generate_items.py`: a price question for
every catalogue item in every language, every FAQ asked another way, availability questions, things
the shop does not sell, greetings, order-status questions, complaints, requests for a person,
haggling, off-topic and spam, and prompt-injection attempts. The wording is written by hand in
that script and the gold labels (SKUs, prices, FAQ titles) are attached from the seed data, so a
label cannot disagree with the shop. Phrasings are still cleaner than real customer messages.

**The Hindi, Gujarati and romanised wording was drafted by an AI and has not been reviewed by a
native speaker.** Review it before relying on the per-language numbers.

## Known limits and biases

- Two verticals only, and the photography shop has fewer items (97) than the print shop (270).
- Quote conversations (several turns) and voice notes are not covered yet.
- FAQ re-wordings are marked `semantic` (they share no keywords with the FAQ), so CI, which uses a
  fake embedder, skips them; run with `--embedder local` to include them.
- No real customer messages were used. Never add any: the benchmark must contain no personal data.
- The `oracle` run (used in CI) answers from the gold labels, so it checks the system around the
  model, not model quality. Compare models with `make eval LLM=real EMB=local`.

## Licence

Items and this datasheet: CC BY 4.0.
