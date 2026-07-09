# Design decisions

The original writeup for this project was addressed to the instructor who designed its scope, so it justified compliance rather than choices. This document is the inverse: it assumes no knowledge of the assignment and explains why the system is shaped the way it is — including a few things I would do differently, and two bugs that the reconstruction process found in my own code.

## Security model on the AWS side: three independent layers

The database and the weather service ran on a single EC2 instance and were reachable only through a WireGuard tunnel terminating there. Three mechanisms enforced that, each sufficient on its own:

**Security group.** The instance's SG admitted exactly one thing from the internet: UDP 51820, WireGuard's listen port. Ports 3306 and 5001 were not opened. Even a total failure of everything below, the packets never arrive.

**WireGuard itself.** Traffic only appears on `wg0` if it decrypts against a configured peer key, and WireGuard drops any packet whose inner source address falls outside the peer's `AllowedIPs` (the OpenStack `/29`). Authentication and anti-spoofing are properties of the tunnel, not rules I had to write.

**Bind addresses.** Both services bound exclusively to the tunnel address, `172.17.35.50` — MariaDB via a `bind.cnf` baked into the image, app2 hardcoded in `app.run()`. This is stronger than firewalling: the services aren't *filtered* on the public interface, they aren't *listening* on it. A process on the same host couldn't reach them over loopback either. And it fails closed — if `wg0` isn't up, the address doesn't exist, and neither service can start. Both containers ran with restart policies, so on boot they simply crash-looped until the tunnel came up, which amounts to a free ordering guarantee.

Each layer covers a different failure of the others: a fat-fingered SG rule, a leaked peer key, a rogue local process. None of them covers a compromise of the tunnel endpoint itself, which is the honest limit of the design.

A corollary of trusting the tunnel: nothing else encrypts. The MySQL protocol runs plain over WireGuard (`ssl_disabled=True` in the connection pool), and app1 → app2 is plain HTTP. Adding TLS inside an authenticated, encrypted tunnel between two hosts I control would have been cost without benefit. The tradeoff is stated rather than hidden: transport security on that path is exactly as strong as the tunnel, no more.

## TLS terminates at the edge

The public entry point was NGINX on the router, with a Let's Encrypt certificate and an unconditional 80 → 443 redirect. Behind it, NGINX load-balanced plain HTTP to the two app1 replicas.

The unencrypted leg is deliberate and conventional. That traffic never left the isolated `/29` segment: the docker VMs had DHCP disabled and no route in from outside, and the router's nftables policy (below) made NGINX the only ingress. Terminating TLS at the edge and speaking HTTP to backends on a private network is how most production deployments work — the interesting part is being able to say precisely *why* it's safe here, which is the isolation, not luck.

app1 uses Werkzeug's `ProxyFix` middleware to consume `X-Forwarded-For/Proto/Host` from NGINX, so the application still knows the original client and scheme despite sitting behind the proxy.

## The firewall

Recovered from development notes, the router's input policy:

```
chain input {
    type filter hook input priority filter; policy drop;
    iif lo accept
    ct state established,related accept
    ct state invalid drop
    iifname "ens3" tcp dport { 22, 53, 80, 443 } accept
    iifname "ens3" udp dport 53 accept
    iifname "ens4" accept
}
```

Default drop; the WAN interface exposes SSH, DNS, and the web tier and nothing else; the internal interface is trusted. DNS is open on both TCP and UDP because BIND answers large responses (DNSSEC, anything over 512 bytes) over TCP — UDP-only is a classic source of intermittent resolution failures. SSH to the internal machines worked via `ProxyJump` through the router, so nothing internal needed exposure.

## Routing to AWS: the transit gateway

The most non-obvious piece of the network. AWS (`.50`) was not on the local segment — it was the far end of a tunnel whose near end lived on docker2 (`.52`). docker2 ran the WireGuard client with **no client-side IP** on the interface and IP forwarding enabled: it wasn't a peer participating in the network so much as a pipe through it.

Getting the other hosts' packets *to* docker2 took two pieces on the router: a static route for `.50/32` via `.52`, and proxy ARP enabled on the internal interface. When docker1 ARPed for `.50` (an address on its own subnet, as far as it could tell), the router answered with its own MAC, accepted the frame, and forwarded it per the route — through docker2, into the tunnel. Return traffic was covered by the server-side `AllowedIPs` containing the whole `/29`. No NAT anywhere; source addresses survived end to end.

The compose translation keeps the invariant and swaps the mechanism: locally, app2 simply *is* `.50` on the bridge, so no transit is needed; the planned hybrid profile reintroduces a WireGuard container at `.52` with an explicit route on the app1 containers — an explicit route where proxy ARP used to be, since inside compose I control the routing tables directly and don't need the L2 trick.

## Isolation: mechanism versus invariant

OpenStack enforced "workloads are unreachable except through the front door" with no-DHCP interfaces and the router being the only path. Docker can't reproduce that mechanism, but it can enforce the same invariant: every service lives on an internal bridge, and NGINX is the only container that publishes a port. `curl localhost:3306` against the running stack gets connection-refused — not because a firewall dropped it, but because nothing is there.

This is the general pattern for the whole reconstruction: the security properties are portable, the enforcement mechanisms are substrate-specific. `infra/` documents the original mechanisms; the compose file demonstrates the invariants.

## Seeding as an endpoint

The project spec imagined a standalone `seed.py`. I implemented seeding as the `POST /api/admin/reset-demo-data` endpoint instead: the demo becomes resettable over the API with no shell access to any machine, which mattered in a deployment where the database lived behind a tunnel on another cloud. The schema image ships completely empty; the API is the only writer.

Re-verification turned up a property of this design I hadn't engineered: the endpoint is accidentally atomic. When a mid-seed failure aborted the request (see the first bug below), the deletes were never committed — Flask's teardown returned the pooled connection, the pool's session reset rolled the transaction back, and the previous demo data survived untouched. The connection pool, added for ordinary performance-hygiene reasons, quietly provided failure semantics the seeding code never earned. I'm keeping the fix *and* the anecdote: deliberate architecture sometimes covers for undeliberate bugs, and it's worth knowing which of your safety nets are load-bearing.

## Two bugs the reconstruction found

Recovering the code was step one; exercising every endpoint against the spec, including failure paths, was step two — and it caught two latent bugs that had survived the entire original deployment.

**The demo seeder assumed its own ids.** `reset-demo-data` deleted all rows, inserted three locations, then inserted trips referencing `location_id` 1 and 2 — hardcoded. `DELETE FROM` does not rewind InnoDB's `AUTO_INCREMENT` counter, so the *second* reset against the same database created locations 4–6 while the trips still pointed at 1 and 2: foreign-key violation, unhandled, HTTP 500. It passed grading because the demo was only ever seeded onto a fresh database. The fix captures `cursor.lastrowid` after each location insert and builds trips from the captured ids — the code stops assuming what the database will assign, which also makes it robust to someone adding a fourth demo location. (An unshipped draft of the standalone `seed.py` had the identical flaw, so the bug was in how the demo data was conceived, not a one-off slip.)

**The uniqueness requirement was never enforced.** app1 dutifully catches MariaDB error 1062 and returns `409 fail-name must be unique` — but the schema declared `name VARCHAR(255) NOT NULL` with no `UNIQUE` constraint, so the database never raised the error and the handler was dead code. Duplicate locations inserted silently all semester. Found by an adversarial test in the endpoint walk (`POST` the same name twice, expect 409, got 201). The fix adds `UNIQUE` to `locations.name` and `trips.title`, at which point the existing handler came alive and the transcript shows the 409. The lesson generalizes: validation that delegates to the database is only as real as the schema behind it.

Both fixes are separate commits with the evidence quoted in the messages. The repository history is the honest version of the project — recovered, exercised, found wanting in two places, corrected.

## Schema: translating the suggested design

The spec suggested an SQLite-flavored schema (`AUTOINCREMENT`, `TEXT` for everything including dates). The deployed target was MariaDB, so the shipped schema translates: `AUTO_INCREMENT`, `DOUBLE` for coordinates, real `DATE`/`DATETIME` types with `CURRENT_TIMESTAMP` defaults, InnoDB explicitly (required for the foreign key to be enforced at all). Typed date columns are also why trip responses serialize dates through `str()` — the driver returns `datetime.date` objects, not strings.

## Things I'd change in a hardening pass

Both apps run Flask's built-in development server (`python wsgi.py`) — fine for the course's traffic, and the recovered artifact is preserved as-is, but a production pass would front them with gunicorn. The local compose profile overrides the database image's bind address with a runtime argument (`command: --bind-address=0.0.0.0`) rather than modifying the image, so the recovered artifact stays byte-identical; the override exists only where the tunnel address genuinely can't. TLS between NGINX and the replicas remains unnecessary for the reasons above, but is the first thing I'd revisit if the backends ever left a network I control.