# ADR-017: SSH closed by default, a deploy preflight, and a thinner image

Status: Accepted (2026-09-30). Amends ADR-008 (firewall, deploy flow, image).

## Context

A security and resource review of the droplet on 2026-09-30 found login already key-only with a
single authorised key, but port 22 open to the whole internet (616 failed attempts in 24 hours).
Nothing stopped a secret being committed to this public repository, and `grype` never failed a
deploy. The image was pinned to `python:3.12.8-slim`, which had received no OS patches since
February 2025. The disk was 77% full: 9 GB of build cache that nothing pruned, because every
code-only deploy rewrote a 240 MB layer.

## Decision

1. **The firewall has no inbound rule.** `infrastructure/ssh-gate.sh` adds a `/32` rule for the
   operator's current address through the DigitalOcean API, runs a command, and removes every
   tcp/22 rule again. It reads `DO_API_KEY` from `.env`; the token never leaves the operator's
   machine. `ssh_allowed_cidrs` stays as a static break-glass list, empty by default.
2. **`deploy.sh` runs inside the gate.** It re-executes itself under `ssh-gate.sh run`. Every
   other SSH command in the docs goes through `ssh-gate.sh ssh` or `ssh-gate.sh run`.
3. **Preflight before the gate opens.** `tools/check_secrets.sh` (trufflehog, offline: git history
   plus staged files), a trufflehog scan of exactly the files rsync would ship, and
   `grype dir:. --only-fixed`, which now fails on High (`.grype.yaml`). The same secrets check is
   a pre-commit and pre-push hook. `SKIP_PREFLIGHT=1` skips it.
4. **Floating base image.** `python:3.12-slim`, pulled on every build, so Debian and CPython
   patch releases arrive with the next deploy.
5. **Image and cache.** uv and its download cache are build-time mounts, the user is created
   before the dependencies, and `/app` stays root-owned (the container root is read-only). The
   layers went from about 860 MB to about 380 MB, and a code-only deploy writes about 3 MB instead
   of 245 MB and takes under a minute. `deploy.sh` tags the image that was running as
   `maxi_bot:previous` when the new one differs in its layers (the image id changes on every
   build, so it is not the test), and prunes build cache older than a day.
6. **Host.** sshd refuses agent forwarding and remote forwarding and allows three attempts; the
   journal is capped at 100 MB; multipathd, ModemManager, udisks2 and fwupd are off. The droplet
   was changed by hand, and `cloud-init.yml` carries the same settings for a reprovision.

## Consequences

+ No SSH surface on the internet. Access needs the SSH key and the DigitalOcean token together.
+ A secret or a High vulnerability stops a commit, a push and a deploy.
+ Disk use fell from 18 GB to under 7 GB of 24 GB.
- Every deploy calls the DigitalOcean API and an address-echo service (`checkip.amazonaws.com`,
  then `api.ipify.org`).
- Builds are no longer byte-reproducible: the base tag floats.
- The DigitalOcean web Droplet Console cannot connect while the port is closed. Break-glass:
  `ssh-gate.sh open`, or `terraform apply -var 'ssh_allowed_cidrs=["<ip>/32"]'`, or the firewall
  page in the control panel.
- trufflehog and grype are now required on the operator's machine, and trufflehog on a
  contributor's.
- A `terraform apply` while a gate is open closes it, since the state holds no inbound rule.
