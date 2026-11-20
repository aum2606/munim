# Self-hosting Munim

One small server (a 2 GB VPS or an old PC is enough), Docker, and a free Cloudflare account. The stack:
Postgres (data, search and job queue), the API, a worker (AI, voice, delivery), the dashboard behind
nginx, a nightly backup, and optionally a Cloudflare Tunnel so you open no ports.

```
Customer -> WhatsApp -> Meta -> Cloudflare Tunnel -> nginx -> api -> Postgres <- worker
                                       Owner browser -> nginx (dashboard)
```

Only nginx listens on the host, on `127.0.0.1:8080`. Postgres and the API are never published.

## 1. Get the code and make your secrets

```bash
git clone <this repo> munim && cd munim
cp .env.example .env
```

Edit `.env`. These are required in production (the stack refuses to start without them):

| Variable | What to put |
|---|---|
| `SECRET_KEY` | 32+ random characters: `openssl rand -hex 32` |
| `CREDENTIALS_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back this up with your other secrets**: without it saved WhatsApp tokens cannot be read |
| `POSTGRES_PASSWORD` | a random password |
| `ALLOW_REGISTRATION` | closed by default in production: set `true` only until you have created your own account, then remove it or set `false` |
| `LLM_SMALL_CHAIN`, `LLM_LARGE_CHAIN`, `GROQ_API_KEY` (or `GEMINI_API_KEY` / `OPENROUTER_API_KEY`) | see `.env.example`. Without a model key the app works but hands every chat to a person |
| `WHATSAPP_VERIFY_TOKEN` | any random string; you will type the same one into Meta |
| `WHATSAPP_APP_SECRET` | from your Meta app (App settings, Basic) |

Never commit `.env`. Check each AI provider's current free-tier limits and data-use terms: some free tiers
use prompts to improve their products, and customer messages are personal data.

## 2. Start it

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # everything should become healthy
```

Open `http://127.0.0.1:8080`, register your own account (this is your business), then set
`ALLOW_REGISTRATION=false` in `.env` and run `docker compose -f docker-compose.prod.yml up -d` again.

The first voice note downloads the speech model (a few hundred MB) into a volume; it is kept after that.

## 3. Put it on the internet with a Cloudflare Tunnel

1. In Cloudflare Zero Trust: Networks, Tunnels, create a tunnel, copy its **token**.
2. Add `CLOUDFLARE_TUNNEL_TOKEN=<token>` to `.env`.
3. In the tunnel's public hostname, point `munim.yourdomain.com` to **`http://web:80`**.
4. `docker compose -f docker-compose.prod.yml --profile tunnel up -d`

`TRUSTED_PROXY_HEADER` defaults to `CF-Connecting-IP` in this file so rate limits see the real visitor
and not the tunnel. Only keep it if all traffic comes through the tunnel (it does here: no port is open).

## 4. Connect WhatsApp

In the Meta developer dashboard (app with the WhatsApp product):

1. Webhook callback URL: `https://munim.yourdomain.com/webhooks/whatsapp`, verify token: your
   `WHATSAPP_VERIFY_TOKEN`. Subscribe to `messages`.
2. In the Munim dashboard, Settings, WhatsApp: paste the **phone number ID** and a **permanent access
   token** (a System User token, not the 24-hour test token).
3. Send a test message from your phone. It appears in the Inbox.

Meta's rules (the 24-hour window, templates, test numbers) are in the
[WhatsApp Cloud API docs](https://developers.facebook.com/docs/whatsapp/cloud-api); check them, they change.

## 5. Backups

The `backup` container writes to `./backups` on the host: a Postgres dump and a copy of uploaded files
(quotation PDFs, documents) every night at 02:00 India time (20:30 UTC), and one at first start. It keeps
14 days (`BACKUP_KEEP_DAYS`). It checks each dump can be read back, and its health check fails if none was
made in the last 26 hours (`docker compose -f docker-compose.prod.yml ps`).

**Backups contain customer conversations.** Keep `./backups` private (the container writes owner-only files; check the folder's permissions on your host),
copy it off the machine (another disk, `rclone` to a cloud bucket, encrypted), and delete old copies on
the same schedule as your privacy notice: erasing a customer in the dashboard does not erase them from
backups you already took.

**Test a restore before you need one** (a drill into a scratch database that does not touch your data):

```bash
deploy/restore.sh backups/munim-YYYYmmdd-HHMMSS.dump munim_check
docker compose -f docker-compose.prod.yml exec postgres psql -U munim -d munim_check -c '\dt'
docker compose -f docker-compose.prod.yml exec postgres dropdb -U munim munim_check
```

To restore for real: stop the api and worker, run `deploy/restore.sh <dump>` (no second argument), start
them again. For uploaded files: `tar -xzf backups/uploads-<stamp>.tgz -C <path of the app_files volume>`.

## 6. Updating

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build   # migrations run on start
```

Take a backup first: `docker compose -f docker-compose.prod.yml exec backup bash /backup.sh once`.

## What is and is not protected

- Rate limits, signed and idempotent webhooks, encrypted WhatsApp tokens, owner-only data export and
  erasure, no published ports, containers without extra privileges, security headers and a content
  security policy on the dashboard.
- Not covered: updating the host's operating system, firewalling the host, monitoring and alerting, and
  offsite backups: those are yours.
- Rate limits are counted per API process; run one API container.
