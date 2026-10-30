# Munim — Ubiquitous Language

Last updated: 30 October 2026.

## Purpose and scope

This document defines the vocabulary used when discussing, designing, implementing
and testing Munim. Business owners, staff and project contributors should use these
terms consistently in requirements, conversations, dashboard labels, code and tests.
Here, the **domain** is customer enquiry and sales assistance for small Indian businesses.

Munim answers enquiries from business knowledge, collects requirements, prepares
GST-aware quotations, tracks leads, supports staff handoffs and provides owner insights.
The current requirement categories are printing, photography, interior design, repair
and electronics. All examples below are fictional.

[BUILD_PLAN.md](BUILD_PLAN.md) is the authoritative product specification;
[DECISIONS.md](DECISIONS.md) records implementation decisions and
[PROGRESS.md](PROGRESS.md) records verification and pending acceptance. This glossary
explains those concepts without changing their rules. It is a maintained project
document; group members should review and agree on terminology as the domain evolves.

## Business workspace and people

| Preferred term              | Definition                                                                                                                                                                                | Example and relationships                                                                                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Business workspace / Tenant | The isolated account representing one business, including its catalogue, settings, users and customer records. “Business workspace” is the user-facing phrase; `tenant` is the code term. | A printing press and a photographer have separate workspaces. Their records must never be mixed.                                                               |
| Owner                       | A business user with authority to configure the workspace, approve quotations and manage sensitive owner actions.                                                                         | The printing press owner updates GST details and approves a quotation.                                                                                         |
| Staff                       | A business user who handles permitted operational work, such as conversations and leads, within the workspace.                                                                            | A staff member takes over a customer conversation. Staff permissions are distinct from owner permissions.                                                      |
| Customer                    | A person contacting a business about its products or services. A record may initially be anonymous.                                                                                       | A website visitor asking about visiting cards is a customer, even before providing a name.                                                                     |
| Lead                        | A tracked sales opportunity linked to a customer and conversation. It contains requirements, stage, score and follow-up information.                                                      | The visiting-card enquiry becomes a lead for a possible printing job. A customer and a lead are different records; a customer may have multiple opportunities. |

Implementation references: [workspace](backend/app/db/models/tenant.py),
[users](backend/app/db/models/user.py), [customers](backend/app/db/models/conversation.py)
and [leads](backend/app/db/models/lead.py).

## Catalogue and business knowledge

| Preferred term     | Definition                                                                                                                             | Example and relationships                                                                                                                     |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Catalogue item     | A structured product or service offered by the business, with an identity, selling unit, base price, tax rate and relevant attributes. | “Visiting cards, pack of 100” is one catalogue item. Code uses `CatalogItem` / `catalog_items`.                                               |
| SKU                | The business's identifier for a catalogue item, unique within its workspace.                                                           | `CARD-100` identifies the visiting-card pack. The same SKU may exist independently in another workspace.                                      |
| Selling unit       | The unit in which a catalogue item is priced and quoted.                                                                               | A pack, day or hour. A request for 500 cards must be mapped correctly to packs of 100.                                                        |
| Pricing rule       | A configured rule applied by the pricing engine to determine an allowed charge or adjustment.                                          | A quantity tier, add-on, minimum order or seasonal rule. A model cannot invent a rule.                                                        |
| Knowledge document | Business-provided information ingested as a source for answers.                                                                        | An uploaded PDF policy or a saved FAQ answer. Current upload types include PDF, DOCX and TXT.                                                 |
| FAQ                | A business-supplied question and answer used as knowledge.                                                                             | “What artwork do you accept?” → “Print-ready PDF artwork.”                                                                                    |
| Knowledge chunk    | A searchable portion of an ingested knowledge document.                                                                                | A delivery-policy paragraph with a reference to its source document.                                                                          |
| Citation           | A reference linking an answer to the catalogue item or document chunk supporting it.                                                   | A price answer cites `CARD-100`; an artwork answer cites the saved FAQ.                                                                       |
| Grounded answer    | An answer supported by retrieved business facts or deterministic tool results.                                                         | The reply repeats the catalogue's verified price and cites its source. Plausible model output alone is insufficient.                          |
| Knowledge gap      | A recorded question for which the available business knowledge does not support an answer.                                             | “Do you print on recycled bamboo paper?” is logged for the owner to resolve if no source answers it.                                          |
| Ingestion          | Processing business documents or FAQs into searchable knowledge.                                                                       | A document progresses from pending to processing and then ready or failed. Catalogue import separately previews and confirms structured rows. |

Implementation references: [knowledge models](backend/app/db/models/knowledge.py),
[ingestion](backend/app/ingestion/documents.py) and
[knowledge agent](backend/app/agents/knowledge.py).

## Enquiries and conversations

| Preferred term     | Definition                                                                                                                                        | Example and relationships                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Enquiry            | A customer's question or expression of interest. In enquiry analytics, one new enquiry is counted at the first inbound message of a conversation. | Several messages in one conversation do not each count as a new enquiry in the overview.                                  |
| Channel            | The medium through which customer messages arrive and replies are delivered.                                                                      | The website widget or WhatsApp.                                                                                           |
| Channel account    | A business's configured connection to an external messaging channel.                                                                              | Its verified WhatsApp number and encrypted connection credentials.                                                        |
| Conversation       | A customer interaction within a workspace and channel, containing messages, a mode and an open/closed status.                                     | One web conversation contains the visiting-card question, requirements and quotation reply.                               |
| Message            | One recorded inbound or outbound communication within a conversation.                                                                             | A customer question is inbound; an AI or staff reply is outbound. Sender type and direction are separate concepts.        |
| Intent             | The classified purpose of a customer message.                                                                                                     | Pricing, quotation request, policy question, complaint or request for a person. Intent informs deterministic routing.     |
| Conversation mode  | The rule governing who prepares and releases replies: `ai`, `assist` or `human`.                                                                  | Assist mode prepares a private draft for staff approval.                                                                  |
| Handoff            | A recorded transfer of a conversation for human attention, including its reason and summary.                                                      | A complaint creates an open handoff and stops normal AI replies. A handoff can later be resolved.                         |
| Assist draft       | A private proposed reply that staff must review and approve before release.                                                                       | A staff member edits or approves an answer while the conversation is in assist mode.                                      |
| Delivery           | The tracked transport of an outbound message to a channel provider. It has a lifecycle separate from quotation or lead status.                    | A WhatsApp send may be queued, sent, delivered, read, failed or uncertain.                                                |
| Uncertain delivery | A send whose outcome cannot be safely determined after a possible provider acceptance.                                                            | A network timeout occurs after submission. The owner reconciles it before any resend; the system must not assume failure. |

Implementation references: [conversations](backend/app/db/models/conversation.py),
[channel delivery](backend/app/db/models/channel.py) and
[handoffs and drafts](backend/app/db/models/lead.py).

## Requirements, quotations and money

| Preferred term      | Definition                                                                                                                                                                      | Example and relationships                                                                                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Requirement         | A customer-provided detail needed to understand and price a requested product or service.                                                                                       | Printing quantity, paper, sides and deadline.                                                                                                                        |
| Requirement schema  | The category-specific definition of required details, allowed values, defaults and follow-up questions.                                                                         | Photography asks for event details; repair asks for device and issue details.                                                                                        |
| Slot                | One named field within a requirement schema.                                                                                                                                    | `quantity` is a slot; `500` is its collected value. Slot filling means collecting missing requirements without repeating completed questions.                        |
| Quotation / Quote   | A priced offer prepared for a customer's requirements, with line items, taxes, validity, terms and a workflow status. These words describe the same concept; code uses `Quote`. | An offer for 500 visiting cards. Acceptance records agreement to the offer; it does not record payment.                                                              |
| Quote line item     | A priced or owner-pricing-required entry within a quotation.                                                                                                                    | Five packs of visiting cards, with quantity, selling unit, unit price and GST rate. Code uses `QuoteItem`.                                                           |
| Pricing engine      | The deterministic calculation component that obtains configured prices and rules and calculates monetary results.                                                               | It calculates taxable amounts, discounts, GST split, rounding and total. The language model may propose a mapping but cannot calculate or change money.              |
| Paise               | The integer storage unit for INR money: 100 paise equals one rupee.                                                                                                             | ₹450.00 is stored as `45000` paise. Monetary calculations use Decimal and persisted amounts use integer paise.                                                       |
| GST                 | Goods and Services Tax represented by the catalogue's configured tax rate and calculated tax components.                                                                        | The engine applies the configured rate; it does not let the model choose one. This describes application behaviour, not tax advice.                                  |
| CGST / SGST / IGST  | The tax components produced by the pricing engine using supplier and customer state information.                                                                                | The current engine splits same-state tax into CGST and SGST and uses IGST for different states; an unknown customer state follows the documented same-state default. |
| Owner approval      | The owner's authorization to release a reviewed quotation or follow-up.                                                                                                         | A quotation normally waits in `pending_approval` until reviewed. Configured quotation auto-send is a separate, bounded policy.                                       |
| Needs owner pricing | A flag indicating that a quote line cannot be fully priced from the configured catalogue and rules.                                                                             | An unlisted custom finish keeps the quote pending until the owner supplies valid pricing.                                                                            |
| Quote number        | The business's unique quotation reference within its Indian financial-year numbering sequence.                                                                                  | `Q/2026-27/0001`. The financial year runs April–March.                                                                                                               |

Implementation references: [requirement schemas](backend/app/schemas/requirements.py),
[quote models](backend/app/db/models/quote.py), [pricing engine](backend/app/pricing/engine.py),
[GST calculation](backend/app/pricing/gst.py) and
[quote numbering](backend/app/pricing/quote_number.py).

## Lead management and owner insights

| Preferred term  | Definition                                                                                                          | Example and relationships                                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Lead stage      | The sales opportunity's current business position, distinct from a quote's status.                                  | An engaged enquiry becomes qualified after enough requirements are collected. Manual stage overrides take precedence over automatic updates. |
| Lead score      | A bounded prioritisation score from 0 to 100, based on recorded signals and a bounded model-assessed buying signal. | A complete enquiry with a quotation may receive higher priority. The score is not a probability or guaranteed sale.                          |
| Follow-up       | A planned contact associated with a lead, normally drafted for owner approval.                                      | A no-reply check, quotation-expiry reminder or dormant-lead re-engagement. Scheduling a draft does not send it.                              |
| Insight         | An owner-facing answer or chart derived from the fixed, tenant-scoped analytics tools.                              | “Who hasn't responded this week?” returns scoped records and counts. The model cannot submit arbitrary SQL or alter numbers.                 |
| Analytics event | A recorded business action used for activity tracking and metrics.                                                  | An inbound message, released quotation or lead marked won. Retried processing must not create duplicate events.                              |
| Weekly digest   | A persisted summary of the preceding IST week, made available on Monday at 09:00 IST.                               | The owner reads the summary in the dashboard. Optional email/WhatsApp delivery is deferred.                                                  |

Implementation references: [lead lifecycle](backend/app/db/models/lead.py),
[analytics models](backend/app/db/models/analytics.py),
[analytics tools](backend/app/tools/analytics.py) and
[insights service](backend/app/analytics/service.py).

## Automation, consent and privacy

| Preferred term    | Definition                                                                                                                            | Example and relationships                                                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent             | A narrowly scoped AI component with typed input/output and an explicit tool allow-list.                                               | The Knowledge agent answers from facts; the Quotation agent maps requirements to catalogue lines.                                                        |
| Orchestrator      | The deterministic application workflow that routes a message and coordinates agent execution.                                         | It routes a complaint to handoff. Agents do not independently choose or call one another.                                                                |
| Guardrail         | A deterministic validation rule applied before releasing customer messages.                                                           | A price not present in the current turn's allowed tool results is blocked. Unsupported promises and private information must also be blocked.            |
| Agent run         | An audit record of a model operation, including its outcome and operational metadata.                                                 | An owner inspects a redacted trace to understand a failed answer. It is separate from the customer-visible message.                                      |
| Consent           | Recorded permission for a specified interaction or communication purpose.                                                             | Starting public web chat requires agreement to the current notice. WhatsApp template opt-in is a separate permission; web consent does not establish it. |
| Customer erasure  | An owner-confirmed workflow removing a selected customer's linked records and files after identity and retention review.              | Messages, leads, quotes and quote PDF versions are removed; incomplete file cleanup remains pending and retryable.                                       |
| Erasure tombstone | Minimal HMAC-based metadata retained to recognise an erased identity or historical channel replay without storing its raw identifier. | A signed old WhatsApp webhook must not recreate the erased conversation.                                                                                 |

Implementation references: [agents](backend/app/agents/base.py),
[orchestrator](backend/app/orchestrator/), [guardrails](backend/app/agents/guardrails.py),
[audit records](backend/app/db/models/agent_run.py) and
[privacy service](backend/app/core/privacy.py).

## Lifecycle language

These names match the current model values. They describe available states, not a
requirement that every record visit every state in order.

- **Conversation status:** `open`, `closed`. Status is separate from mode.
- **Conversation mode:** `ai` prepares automatic replies, `assist` prepares private
  drafts for human approval, and `human` leaves replies to staff after handoff.
- **Lead stage:** `new`, `engaged`, `qualified`, `quoted`, `negotiating`, `won`, `lost`,
  `dormant`. Stages can branch or be manually overridden.
- **Quote status:** `draft`, `pending_approval`, `sent`, `viewed`, `accepted`,
  `rejected`, `expired`. A recorded status alone does not prove a customer action.
  In the current workflow, `sent` means released for channel delivery; consult the
  separate delivery record for actual WhatsApp provider outcomes.
- **Follow-up status:** `scheduled`, `sent`, `cancelled`, `skipped`. In the channel
  workflow, release and provider delivery remain separate facts.
- **Handoff status:** `open`, `resolved`.
- **Knowledge document status:** `pending`, `processing`, `ready`, `failed`.
- **Customer erasure status:** `pending_files`, `complete`. Completion covers the
  application's documented erasure scope, not every external copy of data.

## Shared business rules

1. Every customer operation belongs to one business workspace. Access to another
   workspace's customers, prices, conversations or analytics is prohibited.
2. Prices and monetary adjustments come from catalogue data and configured pricing
   rules through the pricing engine. Models cannot invent prices, discounts or taxes.
   Every outbound monetary amount must match an allowed tool result from that turn.
3. Unsupported answers create a knowledge gap and use the confirmation fallback.
   When a generated reply violates guardrails, the system permits one regeneration
   before handoff.
4. Requirements collection asks at most two questions in a turn and does not repeat
   already filled slots. Quote readiness depends on the relevant schema and valid pricing.
5. Owner approval is the normal quotation release path. Auto-send requires explicit
   configuration and satisfaction of its limits; unpriced lines cannot bypass review.
6. A handoff stops normal automatic replies. Human and assist modes retain human
   control over subsequent customer messages.
7. Follow-up drafting, approval, message release and provider delivery are separate
   actions. Retries must not duplicate business records; uncertain external delivery
   requires reconciliation.
8. Web notice consent, WhatsApp template opt-in and legal-retention review serve
   different purposes. Customer erasure does not automatically remove provider-held
   data, independent uploads, exports or retained backups; see the
   [operations runbook](deploy/README.md).

## Terms that must stay distinct

| Terms                                                        | Agreed distinction                                                                                                                           |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Customer / lead                                              | A person contacting a business / a tracked sales opportunity.                                                                                |
| Quotation / invoice / payment                                | An offer / a billing document / settlement of money. Munim's current quotation workflow does not implement invoicing or payment collection.  |
| Lead stage / quote status / delivery status                  | Sales progress / offer workflow / message transport outcome. None substitutes for another.                                                   |
| Closed conversation / won lead                               | An interaction has ended / a sales opportunity is marked successful. Closing a chat does not prove a sale.                                   |
| Catalogue / knowledge document                               | Structured offerings and prices / supporting business information such as FAQs and policies.                                                 |
| Approved / delivered / accepted                              | Authorized for release / confirmed transport outcome / recorded agreement to an offer.                                                       |
| Grounded / fluent                                            | Supported by business evidence / expressed naturally. Fluency does not establish factual support.                                            |
| Catalogue / catalog; quotation / quote; follow-up / followup | Use the first spelling in explanatory prose; existing code identifiers retain their established spelling. “Quote” is an accepted short form. |

## Example business conversation

1. A **customer** opens the website **widget**, agrees to its notice and starts a
   **conversation** asking for 500 visiting cards.
2. Munim identifies a **quotation request** and collects missing **requirements**
   according to the printing **requirement schema**. The opportunity is tracked as a **lead**.
3. The request maps to five packs of the appropriate **catalogue item**. The
   **pricing engine** applies the configured prices, rules and tax components.
4. A **quotation** with **quote line items** waits for **owner approval**. The owner
   reviews it and releases the PDF; channel **delivery** is tracked separately.
5. If the customer goes silent, a **follow-up** is drafted under the business's policy.
   If the customer complains, a **handoff** transfers attention to staff.
6. The owner uses **insights** and the **weekly digest** to review recorded activity.

## Supported scope and maintenance

Web chat and WhatsApp have implementations. Live WhatsApp acceptance and public
deployment remain pending as recorded in PROGRESS.md. Instagram and optional owner
WhatsApp/email alerts are deferred; describing them in a plan does not mean they are live.
Scripted evaluation results do not establish real-model quality or live business outcomes.

When a domain term changes, update this document alongside affected requirements,
labels, code and tests. Record material model or workflow decisions in DECISIONS.md.
Use precise business names instead of ambiguous substitutes such as “item”, “record”
or “status” when the specific concept is known.
