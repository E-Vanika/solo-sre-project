# Architecture — Solo-SRE

## Naming
Project name: **Solo-SRE** — one small, internet-facing, self-monitored
node, run and defended on its own. Fits a single free-tier VM better
than anything implying a fleet or a cluster.

## Design principle
Everything CPU/memory-heavy runs OFF the e2.micro (free GitHub Actions
runners, free-tier hosted metrics backend). The VM only runs what
absolutely must be on it: the app, the reverse proxy, and lightweight
metric shippers.

## The application
Python — a FastAPI app (`app/main.py`) served by `uvicorn`, instrumented
with `prometheus_client` for the RED metrics. It's the only piece of
this project that's actual application code; everything else is
infrastructure and operations around it.

---

## Networking: browser → OCI → VM, step by step

This is OCI (Oracle Cloud Infrastructure), not AWS — the equivalent of
an EC2 instance here is a **Compute Instance** sitting in a **VCN**
(Virtual Cloud Network, OCI's equivalent of a VPC). Your `main.tf`
already builds all of this; here's what each piece does to a request.

```
Browser
  │  1. DNS lookup: your-domain -> VM public IP
  ▼
Public Internet
  │  2. Packet arrives at OCI's edge for your tenancy
  ▼
Internet Gateway  (oci_core_internet_gateway.e2_micro_igw)
  │  attached to the VCN, is the only path in/out to 0.0.0.0/0
  ▼
Route Table  (oci_core_route_table.e2_micro_route_table)
  │  rule: 0.0.0.0/0 -> Internet Gateway
  │  this is what makes the subnet "public" at all
  ▼
VCN  e2-micro-sre-vcn  (10.0.0.0/16)
  └── Subnet  e2-micro-sre-subnet  (10.0.1.0/24)
        │  3. Security List evaluated (stateful firewall, subnet-level)
        │     - allow 22/tcp  ONLY from your_allowed_ssh_cidr
        │     - allow 80/tcp  from 0.0.0.0/0
        │     - allow 443/tcp from 0.0.0.0/0
        │     - allow ICMP inside 10.0.0.0/16 only
        │     - everything else: implicit deny
        ▼
      VNIC  (public IP assigned directly - assign_public_ip = true)
        │  4. UFW evaluated (host-level firewall, Ansible-managed)
        │     same allow-list, enforced again at the OS - this is
        │     the second layer of defense-in-depth: if the Security
        │     List were ever misconfigured, UFW is still there
        ▼
      Caddy container  (ports 80/443 published to the host)
        │  5. TLS terminated here (see ACME section below)
        │  6. request routed by path (handle_path /metrics*, etc.)
        │  7. rate limiting / auth / circuit breaking applied here
        ▼
      Docker internal bridge network ("internal", NOT published to host)
        │  8. Caddy resolves "app" via Docker's embedded DNS -
        │     this is the project's service discovery: no hardcoded
        │     IP anywhere, the container name is the address
        ▼
      app container  (FastAPI/uvicorn, port 8000 - never bound to the
                       host, only reachable from inside "internal")
```

### Why the app is never exposed directly
`app` has no `ports:` mapping in `docker-compose.yml` — only `expose:`.
That means even if someone found the VM's IP and port-scanned it, port
8000 isn't listening on the host at all. The only public door is Caddy
on 80/443. Compromising Caddy doesn't hand over a direct route to the
app's other internals, because there isn't a host-level route to them
to begin with.

### There's no load balancer in front
`assign_public_ip = true` puts a public IP directly on the instance's
VNIC. That's a deliberate, honest limitation to name out loud: one
VM, one public IP, one point of failure. A real production setup
would put a load balancer (or at least a floating/reserved IP that
can move) in front of ≥2 instances. On the Always Free tier that's
not available, so the SRE story here is "here's what I built inside
that constraint," not "this is production-grade HA."

---

## TLS: how certificate issuance and verification actually happen

Caddy handles this automatically via **ACME** (the same protocol
Let's Encrypt / ZeroSSL use) — no certificate is ever manually
generated or uploaded.

1. Caddy sees `your-domain.example.com` as a site block and knows it
   needs a cert for it.
2. Caddy asks Let's Encrypt for a certificate for that domain.
3. Let's Encrypt has to verify you actually control that domain before
   it issues anything. It does this with a **challenge** — Caddy
   supports two, and picks automatically:
   - **HTTP-01**: Let's Encrypt makes an HTTP request to
     `http://your-domain/.well-known/acme-challenge/<token>` on port
     80. Caddy answers it. If the response matches what Let's Encrypt
     expects, domain ownership is proven — because only whoever
     controls the server that DNS points to could have answered it.
   - **TLS-ALPN-01**: same idea, but over port 443 during the TLS
     handshake itself, no separate HTTP request needed.
4. Once verified, Let's Encrypt issues a short-lived certificate
   (90 days). Caddy stores it in the `caddy_data` volume.
5. Caddy auto-renews it in the background well before expiry — this
   is why there's no cron job or manual step for renewal anywhere in
   this project.

**This is exactly why a bare IP can't get a real TLS certificate** —
Let's Encrypt validates a *domain name*, not an IP address, so there's
nothing for the ACME challenge to verify. The `:80` fallback block in
the Caddyfile is plain HTTP, explicitly for testing before you point a
real domain at the VM.

### Do you need to keep `your-domain.example.com`?
No — replace it with a domain that actually resolves to your VM's
public IP. Two free options if you don't want to buy one for a demo
project:
- **DuckDNS** (duckdns.org) — free subdomain like
  `solo-sre-demo.duckdns.org`, points at your VM's IP, works fine with
  Let's Encrypt.
- **nip.io** — wildcard DNS that resolves `<any-ip>.nip.io` straight
  to that IP with zero signup, useful for quick testing (Let's Encrypt
  will still issue a cert for it since it's a real resolvable
  hostname, not a bare IP).

Once you have the real hostname, swap it into `Caddyfile`,
`sonar-project.properties`, and anywhere else `your-domain.example.com`
appears.

---

## Metrics path
```
app /metrics + node-exporter :9100
   -> vmagent (local, scrapes + remote_write)
   -> Grafana Cloud / VictoriaMetrics Cloud free tier (storage + dashboards + alerting)
```

## CI/CD path
```
git push -> GitHub Actions CI (lint, test, Trivy scan, SonarCloud, build, push to GHCR)
         -> GitHub Actions CD (SSH to VM, pull new tag, health check, auto-rollback on failure)
```
