# Deployment

This setup packages a single app instance with persistent SQLite storage for a
small course or private demo. Hosting and HTTPS must be configured before public
access. It is not a high-availability service. The container build has not yet
been verified on Docker.

## Zero-budget hosting strategy

Prefer an existing university-managed Linux VM and university subdomain if your
department can provide them at no cost. Run the dashboard and submission API
there; students run their editing models on their own compute. General semantic
evaluation may require separate lab GPU resources, depending on the evaluator.

If institutional hosting is unavailable, Oracle Always Free is a possible
fallback. As checked on 2026-10-13, its A1 allowance totals 2 OCPUs and 12 GB RAM,
with 200 GB combined boot/block storage. Provision only Always Free-eligible
resources in the home region and verify the console's cost estimate. Capacity
can be unavailable, and Oracle may reclaim idle instances; keep off-host backups
and a recovery plan. These limits do not provide GPU inference.
See [Oracle's current terms](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Render's free web service cannot attach a persistent disk, so it cannot safely
host this application's SQLite submissions unchanged. See
[Render's free-service limits](https://render.com/docs/free).

Actual deployment still requires a server/account, a hostname and HTTPS setup,
the real benchmark data and evaluator, team roster, deadline, and expected class
size. Do not announce a scored challenge while the synthetic demo is installed.

## Start a fresh private demo

On a Linux server with Docker Engine and the Compose plugin, from this repository:

```bash
docker compose build --pull
docker compose run --rm app init-demo
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8000/ > /dev/null
```

Initialization generates fresh credentials in the persistent volume and refuses
to overwrite an existing configuration. The local `.challenge` directory and
its credentials are excluded from the build. Do not reuse local demo tokens for
production. Retrieve only the team token over your private SSH session:

```bash
docker compose exec app python -c 'import json; print(json.load(open("/data/config.json"))["teams"]["team_demo"])'
```

Until HTTPS is configured, use an SSH tunnel from your laptop:

```bash
ssh -L 18000:127.0.0.1:8000 USER@SERVER
```

Then open http://127.0.0.1:18000. Replace USER and SERVER with your server details.

## Issue student tokens

From the deployment directory, run these commands one at a time:

```bash
docker compose run --rm --no-deps app add-team team_01
docker compose run --rm --no-deps app add-team team_02
docker compose restart app
```

Each command prints a new team token and saves it in `/data/config.json` in the persistent volume. Existing team IDs are rejected without replacing credentials. Give each team only its own token and the server URL. Students enter the token in the dashboard or send `Authorization: Bearer TOKEN` with API requests. Restart the app after adding teams because credentials are loaded at startup. Tokens belong in the private data volume, not `.env` or the Caddyfile.

## Public access

The included Caddy proxy provides automatic certificates, certificate renewal,
and HTTP-to-HTTPS redirects. It forwards to `app:8000` over the private Docker
network. Only the proxy publishes public ports; the app's host port remains on
loopback. Request bodies are limited to 32 MiB, headers to a 10-second receive
window, and bodies to a 60-second receive window.

On the server, first ensure:

- The app dataset is initialized or provisioned as described above/below.
- Your domain's A record points to the server's public IPv4 address. Publish an
  AAAA record only if IPv6 reaches the same server.
- TCP ports 80 and 443 are allowed in the cloud security group/security list and
  host firewall. If behind a router, forward those ports to the server. Do not
  expose port 8000. On Oracle, check both OCI ingress rules and the host firewall.
- No existing service occupies ports 80 or 443. If one does, integrate with its
  existing proxy configuration instead of stopping it blindly.

Create `.env` from `.env.example` if you do not already have one, and set
`CHALLENGE_DOMAIN` to the real public hostname (no scheme or path). Then run from
the repository root, using the same directory/project name as the existing app
so that its data volume is reused:

```bash
docker compose -f compose.yaml -f compose.https.yaml config --quiet
docker compose -f compose.yaml -f compose.https.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose -f compose.yaml -f compose.https.yaml up -d --build
docker compose -f compose.yaml -f compose.https.yaml logs --tail=100 proxy
```

From another machine, substitute your hostname and verify the redirect, valid
certificate, dashboard response, and unauthenticated API rejection:

```bash
curl -I http://challenge.example.org/
curl --fail -sS -o /dev/null -w '%{http_code}\n' https://challenge.example.org/
curl -sS -o /dev/null -w '%{http_code}\n' https://challenge.example.org/api/config
```

Expect an HTTP redirect to HTTPS, then 200 for the dashboard and 401 for the API.
Do not use `curl -k`; certificate verification is part of the check. Log in and
verify a validation submission before inviting students. Caddy's certificate
state persists in `caddy_data`; keep this volume across updates. Do not use
`down -v`. Use both Compose files for subsequent updates and proxy operations.
After changing the hostname or Caddyfile, recreate/restart the proxy; its admin
API is disabled. An existing `.env` hostname change requires recreation.

This config uses public DNS certificates. A bare IP or private hostname requires
a different certificate/trust setup. If issuance fails, inspect proxy logs and
check DNS, CAA restrictions, firewalls, and port forwarding before retrying.
See [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).

Restrict SSH to administrators. For a private course, configure institutional
access or a VPN; API clients must support that access method too. Per-client rate
limits and class-size load testing are separate from this HTTPS configuration.

## Real challenge data

Before initializing the app database, provision `/data/config.json`,
`/data/tasks.json`, images, and reference masks using the schema in CHALLENGE.md.
Files must be accessible to container UID/GID 10001, with the data directory
writable and config permissions restricted. Give every team its own token.
Do not start from the demo results database when replacing the benchmark.

Licensed data, verified masks, a calibrated edit evaluator, compute budgets,
submission limits, and a deadline are still required for a scored challenge.
The current app does not enforce a calendar deadline: close submissions through
the proxy or stop the service at the announced time. Custom evaluator modules
and optional ML dependencies must be included in a separately tested image.

## Backups and updates

Back up the entire `/data` directory to private off-host storage, including its
configuration, images, masks, and SQLite files. Stop the app while taking a file
backup so that the database and WAL files are consistent. For example:

```bash
mkdir -p backups
chmod 700 backups
docker compose stop app
docker compose run --rm --no-deps --entrypoint tar app -C /data -czf - . > backups/challenge.tar.gz
docker compose start app
chmod 600 backups/challenge.tar.gz
```

Check that the archive command succeeded before treating it as a backup. Copy
archives off the server, retain multiple dated versions, and test restoration
into a separate volume before opening submissions. Archives contain credentials
and private test annotations. Never publish them.

Rebuild and recreate the app to update it; the volume survives:

```bash
docker compose up -d --build
docker compose logs --tail=100 app
```

Do not run `docker compose down -v`: that deletes the data volume. Keep one app
instance; do not distribute SQLite over a shared network filesystem. Configure
external uptime and disk-space monitoring. A failed healthcheck reports an
unhealthy container; it does not itself trigger a restart.

Container options follow the [Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
and [Compose service reference](https://docs.docker.com/reference/compose-file/services/).
