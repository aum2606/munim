# Privacy notice (template)

A starting point for a business that uses Munim to answer customers on WhatsApp. **It is not legal
advice.** Fill in the brackets, have someone who knows India's Digital Personal Data Protection Act
2023 (DPDP) and its rules check it, and show it to customers (for example as a link in your first
reply or on your WhatsApp Business profile).

## Who we are

[Business name], [address]. Questions about your data: [email or phone].

## What we collect, and why

| Data | Why | Where it comes from |
|---|---|---|
| Your WhatsApp number and profile name | To reply to you | WhatsApp |
| What you write or say (text and voice notes, as text) | To answer your questions and prepare quotations | You |
| The requirements you give for a quotation, and the quotation itself | To quote and follow up | You, our team |

We do not ask for or store payment card details, Aadhaar, or other identity numbers in this tool.

## Who else handles it

- **WhatsApp / Meta** carries the messages.
- **An AI model provider** [name the provider you configured] receives your message text, and the
  shop's catalogue and FAQs, to draft answers. Some free tiers may use prompts to improve their
  products: check your provider's terms, and use a local model if that is not acceptable.
- **Our hosting** [where the server runs] stores the conversation.
- Voice notes are turned into text on our own server and the audio is not kept.

## How long we keep it

[For example: conversations for 12 months after the last message.] Ask us to delete yours at any
time.

## Your rights

You can ask us for a copy of what we hold about you, or to delete it. Contact [contact above]. We
will find you by your phone number.

## For the business owner (how to answer such a request)

In the dashboard's API (owner login required):

- `GET /api/v1/customers?q=<phone or name>` finds the customer.
- `GET /api/v1/customers/<id>/export` returns everything held about them as JSON.
- `DELETE /api/v1/customers/<id>` permanently deletes the customer, their conversations and
  messages, leads, quotations (and the stored PDFs), follow-up drafts, the model traces that
  contain their words, and any "unanswered question" that quotes them. It cannot be undone.

Things deletion does **not** reach, which you must handle yourself:

- Anything you copied elsewhere: your phone's WhatsApp history, exports, backups taken before the
  deletion (see the backup retention in the self-host guide), invoices you must keep for tax law.
- What WhatsApp / Meta and your model provider keep under their own policies.
- If the customer messages you again, a new record is created.
