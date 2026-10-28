# Pilot operations

This runbook prepares a single-server pilot. Configuration and image checks do not
prove a public deployment, certificate issuance, object-store delivery or alert delivery.
Complete [the launch checklist](PILOT_CHECKLIST.md) before inviting customers.

## Server and configuration

Use a Linux server with Docker Compose, sufficient disk for PostgreSQL, uploads and
one temporary backup, and a domain pointing to it. Allow inbound TCP 80/443 (UDP 443
is optional HTTP/3); keep PostgreSQL, Redis, API and Docker management private. Choose
hosting and storage regions consistent with the business's data handling commitments.

Copy `.env.production.example` to `.env.production`, restrict its permissions to the
operator, and populate every required value. Generate independent random signing and
privacy keys (at least 48 and 32 characters respectively) and a Fernet key with
`make channel-key`. Retain the privacy HMAC key across restores: rotating it without
migrating tombstones breaks historical replay/erasure matching. Back up all encryption
keys separately in the operator's secret manager. Never paste them into logs or chat.

Set `DATABASE_URL` to the internal `postgres` service, with the URL-encoded password
matching `POSTGRES_PASSWORD`. Set `PUBLIC_API_URL=https://<domain>`,
`WIDGET_SCRIPT_URL=https://<domain>/widget.js` and explicit HTTPS `CORS_ORIGINS` for
the dashboard and business websites embedding the widget. Configure real model and
embedding providers/models; leave `ALLOW_FAKE_MODELS_IN_PROD=false`. Production
startup validates keys, URLs, model configuration and mandatory rate limits.

Run from the repository root:

```sh
make prod-config
make prod-build
make prod-up
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Caddy obtains and renews certificates using `APP_DOMAIN` and `TLS_EMAIL`; DNS and
reachable ports are necessary. Persistent Caddy volumes retain certificate state.
Verify HTTPS, `/health`, `/ready`, login, the widget on the actual business origin,
worker health and migrations. Keep API proxy trust behind the private Caddy network.
Use an external uptime probe as well: the internal monitor cannot report a whole-server
or network outage. Apply OS/security updates and rebuild pinned application dependencies
through review; commit and retain the deployed revision for rollback.

## Daily backups and alerts

Create a private S3-compatible bucket, disable public access, require encryption, and
configure a documented retention/lifecycle policy including old object versions. Prefer
a workload IAM role; otherwise scope credentials to this bucket/prefix with upload
permissions. Keep restore/read/delete permissions separately controlled. The default
SSE is AES256; `BACKUP_SSE=aws:kms` additionally needs a key and appropriate KMS access.
Custom endpoints must support HTTPS and the configured SSE arguments.

The backup service runs at startup and daily at 20:30 UTC (02:00 IST), retrying failures
after 15 minutes. `make backup` requests a backup now. It coordinates database/file
writes using a PostgreSQL advisory barrier and uploads `database.dump`, `uploads.tar.gz`,
`erasures.csv` and a SHA-256 `manifest.json`, with the completion manifest last. A prefix
without a complete manifest is unusable. Temporary local files are private and removed
after the attempt. Monitor free disk and backup runtime; the barrier temporarily delays
file mutations, so schedule outside busy hours.

Set `ALERT_WEBHOOK_URL` to a private HTTPS receiver accepting
`{"event":"…","service":"munim"}`. The monitor checks API readiness and a backup age
under 26 hours every minute, alerts after three failures, and reports recovery. Backup
failures also emit an alert. No customer content is included. Without a receiver events
only appear in container logs. Test delivery by an intentional, supervised staging
failure and recovery; checking configuration alone does not verify notification delivery.

## Restore drill and customer erasure

`make restore-check` verifies real PostgreSQL custom-format dump/restore in a disposable
testcontainer. Before launch, also restore an actual encrypted object-store backup to an
isolated server with outbound messaging, workers and model credentials disabled:

1. Select a complete prefix, download its files and verify every manifest checksum.
2. Create a fresh PostgreSQL 16 database with pgvector available. Restore with
   `pg_restore --no-owner --no-acl --dbname=<isolated-db> database.dump`.
3. Inspect the archive before extraction; restore uploads into a fresh isolated storage
   directory, preserving the application UID/GID 10001 ownership. Restore the matching
   encryption/HMAC keys from the secret manager. Run migrations to the chosen revision.
4. Reconcile **all erasures since that backup** before enabling customer access: use the
   latest privacy ledger and the original stable HMAC key to identify restored customer
   UUIDs/channel identifiers. Reapply deletion through the owner privacy workflow and
   remove corresponding files. The ledger inside an old backup alone is insufficient.
5. Verify tenant isolation, catalogue paise values, PDF access and a test owner login;
   record recovery time, backup timestamp and data loss window. Enable workers/channel
   delivery only after reviewing queued/uncertain sends to prevent unintended replays.

The current erasure endpoint removes the selected customer graph, linked documents and
all quote PDF versions; it invalidates derived summaries/audits and keeps only HMAC
tombstones and operational metadata. Pending file cleanup remains visible and retryable.
The owner must review legal retention before confirming. Independently uploaded business
documents, exports, screenshots, provider-held data and retained backups need a separate
retention/deletion process. Contact channel/model providers where required; apply bucket
lifecycle and post-restore reconciliation rather than claiming old backups are erased.
Protect the latest erasure ledger as sensitive operational data, despite its HMAC values.

## Release and pilot gates

Run `make test lint build eval e2e`, migration/drift checks and the restore drill. The
default eval report uses scripted FakeLLM and cannot establish real-model groundedness.
To measure configured models, explicitly set `EVAL_USE_REAL_LLM=1` and a dedicated,
disposable `EVAL_DATABASE_URL`, then run `make eval`; never point it at production.
Synthetic fixtures and audit rows remain in that evaluation database for inspection.

Complete the signed live WhatsApp enquiry → requirements → owner-approved PDF test,
duplicate replay, expired-window and STOP checks using a configured Meta test recipient.
Measure BUILD_PLAN §15 targets over the actual pilot: response latency, AI resolution,
follow-up coverage, knowledge gap closure, conversion and owner-reported time saved.
Record real evidence separately from offline contract reports. Instagram and owner
WhatsApp/email notifications are optional and remain deferred.
