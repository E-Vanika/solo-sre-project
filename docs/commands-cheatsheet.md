# Command reference

Every command actually used to build, debug, and operate Solo-SRE,
organized by task. Written from real troubleshooting sessions, not
theoretical - if a command looks oddly specific, it's because it
fixed a real problem once.

## SSH access
```bash
ssh -i C:\Users\Admin\.ssh\id_ed25519 ubuntu@<VM_PUBLIC_IP>
ssh-keygen -R <VM_IP>   # clear a stale known_hosts entry after VM recreation
```

## Docker / Compose - daily operations
```bash
docker ps                              # running containers
docker ps -a                           # include stopped/exited
docker logs <container> --tail 50      # recent logs
docker logs <container> --since 1m     # only the last minute (avoids stale log confusion)
docker logs <container> -f             # follow live
docker inspect <container> --format '{{.HostConfig.NetworkMode}}'   # confirm actual network mode
docker exec <container> <cmd>          # run something inside a running container
docker compose config                  # validate + print fully-resolved compose file
docker compose up -d                   # start everything
docker compose up -d --build           # start, rebuilding any local Dockerfile-based service
docker compose up -d --no-deps <svc>   # restart just one service
docker compose up -d --force-recreate --no-deps <svc>   # force a real recreate, not a no-op
docker compose pull <svc>              # pull latest image for one service
docker network ls
docker network inspect <name> | grep Subnet
```

## Ansible bootstrap
```bash
ansible-playbook -i inventory.ini playbook.yml
cloud-init status --wait      # block until first-boot setup is truly done (avoids apt lock races)
cloud-init status             # check current status
```

## UFW (host firewall)
```bash
sudo ufw status verbose
sudo ufw allow from <subnet> to any port <port> proto tcp   # scoped, not blanket
sudo ufw delete allow from <subnet> to any port <port> proto tcp
sudo fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock   # check who's holding the apt lock
```

## Networking diagnostics
```bash
hostname -I                          # real interface IPs (capital -I, not -i)
ip route get 1.1.1.1 | awk '{print $7; exit}'   # outbound-facing IP, alternate method
nslookup <domain>                    # confirm DNS resolves where expected
curl.exe -v https://<domain>/health  # verbose - shows TLS handshake, connect timing, exact failure point
curl.exe -i https://<domain>/error   # -i shows response headers/status without verbose noise
```

## TLS / Caddy
```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'YourPassword'
docker logs caddy --tail 50 | grep -i certificate
curl.exe -u 'monitor:YourPassword' https://<domain>/metrics    # single-quote in PowerShell - avoids $ interpretation
```

## Metrics / vmagent
```bash
docker logs vmagent --since 1m
cat vmagent/scrape.yml                # always verify the file on disk before assuming an edit landed
wc -l vmagent/scrape.yml               # quick sanity check against expected line count
```

## Deployment / rollback
```bash
docker compose pull app app-2 greeting-service
docker compose up -d --no-deps app app-2 greeting-service
./scripts/rollback.sh
cat .last_good_tag
```

## Chaos engineering
```bash
chmod +x scripts/chaos-test.sh scripts/rollback.sh   # fix lost executable bit after scp/git transfer
bash scripts/chaos-test.sh kill-app
bash scripts/chaos-test.sh oom
sudo apt install -y stress-ng
bash scripts/chaos-test.sh cpu-spike
```

## Load testing
```bash
sudo apt install -y apache2-utils
ab -n 300 -c 20 https://<domain>/slow
watch -n 1 'docker stats --no-stream'   # live resource view in a second SSH session
```

## PowerShell-specific gotchas
```powershell
# curl.exe explicitly - PowerShell aliases `curl` to Invoke-WebRequest otherwise
curl.exe -v https://example.com

# single quotes for anything with special characters (e.g. passwords with $)
curl.exe -u 'monitor:Pass$word' https://example.com

# base64-encode a string (for OTLP Basic Auth headers)
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('userid:token'))
```
