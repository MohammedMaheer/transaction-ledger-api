# Hostinger VPS deployment

The public assessment demo runs as a separate Docker Compose project behind the VPS's
existing Nginx installation. Other projects and their proxy configuration are independent.

- Interactive API: <https://ledger-api.187.127.162.233.sslip.io/docs>
- Health: <https://ledger-api.187.127.162.233.sslip.io/health>
- OpenAPI: <https://ledger-api.187.127.162.233.sslip.io/openapi.json>
- Source: <https://github.com/MohammedMaheer/transaction-ledger-api>

This is a public assessment sandbox with fictional accounts. Authentication remains
outside the assessment scope. Do not put personal, sensitive, or real financial data in
the shared demo. The source repository contains no deployment secrets or private keys.

## Initial setup

Requires an Ubuntu VPS with Docker Engine, Compose v2, Nginx, and the Certbot Nginx plugin.
Choose an unused loopback API port and a dedicated hostname resolving to the VPS. The
included Nginx configuration uses `ledger-api.187.127.162.233.sslip.io` and port 18765.
The hostname uses [sslip.io](https://sslip.io/) to resolve the embedded public IP without
changing an existing website's DNS. It can be replaced with a custom domain.

As a VPS administrator:

```bash
git clone https://github.com/MohammedMaheer/transaction-ledger-api.git /opt/transaction-ledger
cd /opt/transaction-ledger
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
path = Path('.env.production')
with path.open('x') as file:
    file.write(f'POSTGRES_PASSWORD={secrets.token_hex(32)}\nAPI_PORT=18765\n')
path.chmod(0o600)
PY
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d --wait
curl --fail http://127.0.0.1:18765/health
install -m 644 deploy/nginx.conf /etc/nginx/sites-available/transaction-ledger
ln -s /etc/nginx/sites-available/transaction-ledger /etc/nginx/sites-enabled/transaction-ledger
nginx -t
systemctl reload nginx
certbot --nginx --cert-name transaction-ledger-api \
  -d ledger-api.187.127.162.233.sslip.io --non-interactive --agree-tos --redirect
curl --fail https://ledger-api.187.127.162.233.sslip.io/health
```

Certbot uses an existing ACME account when available. For a first-time Certbot installation,
also provide `--email YOUR_EMAIL` for certificate notices. Keep its automatic renewal timer
enabled. Verify with `systemctl status certbot.timer` and `certbot certificates`.

The API port is loopback-only and PostgreSQL has no host port. The API runs as a non-root
user with a read-only filesystem, dropped Linux capabilities, bounded memory/processes,
and a temporary `/tmp`. Only the trusted Nginx path can reach its published host port, so
Uvicorn trusts forwarded headers. Migrations must succeed before the API starts.

## Updates, logs, and verification

```bash
cd /opt/transaction-ledger
git pull --ff-only
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d --wait
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
docker compose --env-file .env.production -f docker-compose.production.yml logs --tail 100 api migrate
```

Run the same source in a separate test project and ephemeral database:

```bash
docker compose --project-name transaction-ledger-verification --env-file .env.production \
  --profile test run --build --rm tests
docker compose --project-name transaction-ledger-verification --env-file .env.production \
  --profile test down
```

The test profile uses the development Compose file, a separate database named `ledger_test`,
and port 5433; it never points tests at the live ledger. Ensure this host port is unused.
Do not use `down --volumes` on the production project unless deliberately deleting its data.

## Database backup

```bash
cd /opt/transaction-ledger
umask 077
docker compose --env-file .env.production -f docker-compose.production.yml \
  exec -T db pg_dump -U ledger -d ledger -Fc > ledger-backup.dump
```

Store backups outside the repository. Keep `.env.production` outside any public archive.
