# Build Guide: everything before the code

This is the machine, the network, the credentials, and the proof that all three work. Nothing here writes application logic. Complete it end to end, then follow the Quickstart in the README (or `REPRODUCTION.md`) to install and run jobbot.

Budget about 3 hours. You can stop between any two parts. Every step says what you are doing and why.

Example addressing used throughout (substitute yours):

| Thing | Example value in this guide |
|---|---|
| Trusted network (your PC lives here) | `192.168.10.0/24` |
| Lab network (the container lives here) | `192.168.50.0/24`, VLAN ID `50`, gateway `192.168.50.1` |
| Container static IP | `192.168.50.50` |
| Proxmox host IP | `192.168.80.20` |
| Your mailbox | `you@example.com` |
| Your Linux user inside the container | `youruser` |

---

## Part 0: the plan

### What you are building

An Ubuntu container on a Proxmox host that runs the whole pipeline: finds jobs, writes cover letters, submits through ATS forms, reads your inbox, and serves a dashboard to your PC and your phone.

### Four decisions already made

**1. The container goes on its own VLAN.**
Three router policies are all it needs: *Allow Trusted to Lab*, *Allow Trusted to Lab (Return)*, *Block Lab to Gateway*. Your PC reaches the dashboard, the container cannot touch the router's own services, and it is firewall-separated from your hypervisor.

Separation matters because this container holds your mailbox password and your API key, and it ingests untrusted text from job postings all day. That is a prompt-injection surface. If you put it on the same subnet as the Proxmox host, same-subnet traffic never reaches the router, so no rule can sit between the container and your hypervisor's management interface. On its own VLAN the gateway is in the path.

Staying on the same VLAN as Proxmox instead? Skip Part 2.2 through 2.4 and Part 3. You lose gateway-level separation and rely on `ufw` inside the container. Faster, weaker.

**2. SQLite, not a spreadsheet.**
The dashboard replaces the phone-editable spreadsheet. SQLite removes a cloud project, a service-account key, API quotas, and network latency. The pipeline writes a nightly CSV export for backup.

**3. Plain IMAP/SMTP, not a provider API.**
No OAuth, no token refresh. IMAP over SSL to read, SMTP over SSL to send. Read Part 1.1 carefully; some providers have a security tradeoff.

**4. Email plus ntfy, not SMS.**
SMS caps near 1,600 characters, so the full daily report cannot fit. It goes to your own inbox: unlimited, formatted, searchable. Urgent items push through ntfy, self-hosted in the container, free, over your tailnet.

---

## Part 1: credentials

Do this first, away from the terminal. Every later part assumes you have these.

### 1.1 Mailbox third-party access

**What:** turn on IMAP/SMTP for the mailbox you apply from.
**Why:** the pipeline reads your inbox to classify rejections, interview requests, and action-needed mail, and it sends you the nightly report and the follow-ups. Follow-ups must come from the same address the applications came from, or they read as spam.

**The tradeoff, stated plainly.** Some hosted mail providers require two-factor authentication *off* before third-party clients can connect, with no app-password mechanism. If yours is one of them, the mailbox holding all your job correspondence loses its second factor and its password gets stored on a machine. Manage it:

- Change to a unique, generated 20+ character password *before* enabling third-party access.
- The password lives in one place: `~/jobbot/.env`, mode 600, on an isolated VLAN, in an unprivileged container, never in git.
- Audit which accounts use this mailbox for password reset. Anything important should have its own 2FA.
- Turn 2FA back on the day you stop running this. Put it on your calendar now.
- A second mailbox does not solve it: follow-ups must send from the applying address, so that address needs SMTP anyway.

If that trade is not acceptable, cut automated inbox triage and read job mail yourself. That is a real option, not a failure.

**Steps**
1. Change the mailbox password to a fresh generated one. Save it in your password manager.
2. In your provider's settings, enable IMAP/SMTP or "third-party access" (and disable 2FA only if the provider requires it).
3. Write down: full email address, the new password, IMAP host and port (usually 993), SMTP host and port (usually 465 or 587).

### 1.2 Anthropic API key

**What:** a key so the container can call the model for scoring, letters, and the chat agent.
**Why:** if you use Claude Code interactively, its subscription auth covers your sessions. The cron jobs run unattended and need their own key.

1. console.anthropic.com, sign in.
2. API Keys, Create Key, name it `jobbot`. Copy it immediately; it is shown once.
3. Billing: add a payment method and set a **monthly spend limit**. Start at $25 to $40.

The spend limit is the important part. A loop bug at 40 jobs a day can burn money fast; the cap turns a bad night into a stopped script instead of a bill.

### 1.3 ntfy app

Install ntfy on your phone (Play Store or App Store). Do not configure it yet; Part 7.5 sets up the server and Part 9.4 subscribes the phone.

### 1.4 Job sources

- Adzuna: create a free developer account and note the app ID and key.
- USAJobs: request a free API key and note the user-agent email they ask for.
- Optional aggregators (Jobright and similar): if you use one, confirm what it exposes to a plain script before assuming anything. Never script a board whose terms forbid automation; those postings route to the Manual Queue by design.

**Checklist**
- [ ] Mailbox password rotated, third-party access on
- [ ] API key saved, spend limit set
- [ ] ntfy installed on the phone
- [ ] Source API keys collected

---

## Part 2: Proxmox host

SSH to the host, or use the web UI shell (select the node, then Shell).

### 2.1 Confirm capacity

```
pveversion
df -h
pvesm status
```

You need about 32 GiB free on the storage that will hold the container.

### 2.2 Back up the network config

```
cp /etc/network/interfaces /etc/network/interfaces.bak
ls -la /etc/network/interfaces.bak
```

**Why:** the next step reconfigures the bridge that carries your management IP. If it goes wrong you lose SSH to the host. This file is how you get back.

**Recovery if you lose the connection:** log in at the physical console and run
`cp /etc/network/interfaces.bak /etc/network/interfaces && ifreload -a`.

### 2.3 Make the bridge VLAN-aware

**What:** let `vmbr0` pass tagged VLAN traffic.
**Why:** by default it cannot. A container tagged VLAN 50 would land on the untagged network and come up with the wrong address or none.

```
nano /etc/network/interfaces
```

Your `vmbr0` block looks something like:

```
auto vmbr0
iface vmbr0 inet static
        address 192.168.80.20/24
        gateway 192.168.80.1
        bridge-ports nic0
        bridge-stp off
        bridge-fd 0
```

Add two lines so it becomes:

```
auto vmbr0
iface vmbr0 inet static
        address 192.168.80.20/24
        gateway 192.168.80.1
        bridge-ports nic0
        bridge-stp off
        bridge-fd 0
        bridge-vlan-aware yes
        bridge-vids 2-4094
```

Indentation must match the existing lines. Ctrl+O, Enter, Ctrl+X.

`bridge-vlan-aware yes` turns on VLAN filtering. `bridge-vids 2-4094` declares which VLAN IDs the bridge accepts. The host keeps its address because untagged frames fall to the default PVID.

### 2.4 Apply and verify

```
ifreload -a
```

If `ifreload` is missing: `apt install ifupdown2`, then rerun.

Your SSH session should survive. Verify:

```
cat /sys/class/net/vmbr0/bridge/vlan_filtering
ip a show vmbr0 | grep inet
ping -c2 1.1.1.1
```

Want: `1`, your host address, and replies from 1.1.1.1.

Do not test by pinging the gateway itself. If you have a *Block to Gateway* rule on the host's VLAN, ICMP to the router's own address is dropped even though everything works. If 1.1.1.1 replies, the packet routed through the gateway and the gateway is forwarding.

### 2.5 Download the container template

```
pveam update
pveam available | grep ubuntu-24
pveam download local ubuntu-24.04-standard_24.04-2_amd64.tar.zst
```

Adjust the version suffix to match your output exactly.

---

## Part 3: the router

Written for UniFi; the concepts apply to any router with zone or VLAN firewall policies.

### 3.1 Confirm the Lab network has internet

If you have a *Block Lab to Gateway* policy, it stops traffic to the router's own services (DNS, the UI) but not traffic *through* the router. Confirm egress works from a host on that VLAN before building the container. If it does not, add an *Allow Lab to Internet* policy above the block.

### 3.2 Tag the Lab VLAN on the Proxmox switch port

**What:** make sure the switch port feeding your host carries the Lab VLAN.
**Why:** the bridge can tag frames all day, but if the port drops VLAN 50 the container has no network.

1. Devices, your switch, Ports, the port your Proxmox host is plugged into, Edit.
2. Native VLAN stays whatever the host uses today, so the host keeps its address.
3. Tagged VLANs must include Lab. If the port profile is "All", you are done.
4. Apply.

### 3.3 Pick an IP outside DHCP

Check the Lab network's DHCP range. If it is `.100` to `.200`, then `192.168.50.50` is clear.

Static, not a reservation. A server that depends on DHCP to be reachable is a server that disappears when the router reboots.

---

## Part 4: create the container

### 4.1 Run the wizard

Proxmox UI, Create CT.

| Field | Value |
|---|---|
| CT ID | 200 (any free ID) |
| Hostname | jobbot |
| Unprivileged container | checked |
| Nesting | checked |
| Password | strong, saved |
| Template | ubuntu-24.04-standard |
| Disk | 32 GiB |
| CPU | 2 cores |
| Memory | 4096 MiB, swap 4096 MiB |
| Network name | eth0 |
| Bridge | vmbr0 |
| VLAN Tag | 50 |
| Firewall | unchecked |
| IPv4 | Static, `192.168.50.50/24`, gateway `192.168.50.1` |
| IPv6 | None |
| DNS domain | blank |
| DNS servers | `1.1.1.1 9.9.9.9` |

Unprivileged means root inside the container maps to an unprivileged UID on the host, so a compromise inside does not become host root. Given what this container ingests, that matters.

Public resolvers because *Block Lab to Gateway* means the router will not answer DNS for this network.

Confirm and review. Do **not** tick "Start after created."

### 4.2 Add the TUN device

**What:** two lines in the container config.
**Why:** Tailscale needs `/dev/net/tun`. Unprivileged containers do not get it. Skip this and Tailscale throws an error that reads like a permissions problem and sends you down the wrong path for an hour. This is the single most common failure in the build.

On the host:

```
nano /etc/pve/lxc/200.conf
```

Append:

```
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
```

Save and exit.

### 4.3 Start and verify

```
pct start 200
pct exec 200 -- ip a
```

Want `192.168.50.50/24` on eth0. If it is missing or wrong, the VLAN tag or the switch port profile is the cause. Fix before continuing.

```
pct exec 200 -- ping -c2 1.1.1.1
```

If that fails, the Lab network has no internet egress. Back to Part 3.1.

### 4.4 Snapshot

UI, container 200, Snapshots, Take Snapshot: `01-fresh`.

Snapshot at every marked point. A bad command costs thirty seconds instead of a rebuild.

---

## Part 5: base configuration

```
pct enter 200
```

### 5.1 Timezone, before anything else

```
timedatectl set-timezone America/New_York
timedatectl
```

Use your own zone. Every schedule is local time. A container left on UTC runs 6:00 AM discovery at 1:00 AM and the 7:00 PM report at 2:00 PM, and you notice a week later.

### 5.2 Update and install basics

```
apt update && apt upgrade -y
apt install -y curl wget git nano ufw ca-certificates gnupg unattended-upgrades sqlite3 telnet
```

`sqlite3` is your database. `telnet` is only for testing mail connectivity in Part 9.

### 5.3 Working user

```
adduser youruser
usermod -aG sudo youruser
```

Everything from here runs as that user. Running the pipeline (or Claude Code) as root means every file it writes is root-owned and every mistake has no floor under it.

### 5.4 Automatic security patches

```
dpkg-reconfigure --priority=low unattended-upgrades
```

Choose Yes. This box holds your mailbox password and API key. Patch it without being asked.

### 5.5 Host firewall

```
ufw default deny incoming
ufw default allow outgoing
ufw allow from 192.168.10.0/24
ufw allow from 192.168.50.0/24
ufw allow in on tailscale0
ufw enable
```

Trusted reaches the dashboard. Tailscale reaches it from anywhere. Everything else is denied. The `tailscale0` line warns that the interface does not exist yet; harmless, it applies once Part 6 runs.

**Snapshot:** `02-base`

---

## Part 6: Tailscale

**Why:** puts the dashboard on your phone over cell data with no port forward on the router and nothing listening on your WAN.

### 6.1 Install and connect

```
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --hostname=jobbot
```

It prints a URL. Open it on your PC, sign in, approve the machine.

### 6.2 Verify

```
tailscale ip -4
tailscale status
```

**If it errors on TUN:** Part 4.2 did not apply. `pct stop 200` on the host, verify both lines in `/etc/pve/lxc/200.conf`, `pct start 200`, retry.

If it still fails, userspace mode works:

```
tailscale down
systemctl edit tailscaled
```

Add:

```
[Service]
ExecStart=
ExecStart=/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --tun=userspace-networking
```

Then `systemctl daemon-reload && systemctl restart tailscaled && tailscale up`.

### 6.3 Phone and PC

Install Tailscale on both, same account.

### 6.4 MagicDNS

login.tailscale.com, DNS, enable MagicDNS. The dashboard becomes `http://jobbot` from any device on your tailnet.

**Snapshot:** `03-tailscale`

---

## Part 7: toolchain

```
su - youruser
```

### 7.1 Python

```
sudo apt install -y python3 python3-pip python3-venv
python3 --version
```

### 7.2 Node (only needed for Claude Code)

```
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version
```

### 7.3 Claude Code (optional, if you plan to extend jobbot the way it was built)

```
sudo npm install -g @anthropic-ai/claude-code
claude --version
```

### 7.4 Caddy

```
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo systemctl enable --now caddy
```

Test from your PC: `http://192.168.50.50` shows the Caddy welcome page. If it does not, *Allow Trusted to Lab* is not matching. Check the policy sits above any block rule.

### 7.5 ntfy server

ntfy is not in Ubuntu's repositories. `apt install ntfy` on its own fails with "Unable to locate package."

```
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://archive.heckel.io/apt/pubkey.txt | sudo gpg --dearmor -o /etc/apt/keyrings/archive.heckel.io.gpg
sudo sh -c "echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/archive.heckel.io.gpg] https://archive.heckel.io/apt debian main' > /etc/apt/sources.list.d/archive.heckel.io.list"
sudo apt update
sudo apt install -y ntfy
sudo systemctl enable --now ntfy
```

The repo line says `debian main` and that is correct on Ubuntu too. If the repo fails, install the release `.deb` directly:

```
curl -sSL https://github.com/binwiederhier/ntfy/releases/latest/download/ntfy_linux_amd64.deb -o /tmp/ntfy.deb
sudo apt install -y /tmp/ntfy.deb
sudo systemctl enable --now ntfy
```

Default listen is `:80`, which collides with Caddy. Move it:

```
sudo nano /etc/ntfy/server.yml
```

Set:

```
listen-http: ":2586"
base-url: "http://jobbot:2586"
```

```
sudo systemctl restart ntfy
systemctl is-active ntfy
systemctl is-active caddy
```

Both must print `active`.

**Snapshot:** `04-toolchain`

---

## Part 8: project directory and secrets

### 8.1 Clone the repository

```
git clone https://github.com/CyberCryptonic/jobbot.git ~/jobbot
cd ~/jobbot
```

The `.gitignore` already excludes `.env`, databases, exports, screenshots, letters, and your resume. Keep it that way.

### 8.2 Secrets file

```
cp .env.example .env
nano .env
chmod 600 .env
```

Fill in every value. Change `NTFY_TOPIC` to something random. On a self-hosted ntfy behind Tailscale the topic is effectively your access control, so treat it like a password rather than a label.

### 8.3 Answer bank and resume

```
cp config/application-answers.example.md config/application-answers.md
nano config/application-answers.md
```

Copy your resume PDF into the project root, then lock it:

```
chmod 444 ~/jobbot/resume.pdf
```

The resume ships byte-for-byte on every application. Making it read-only makes that structural rather than a prompt instruction something might drift from later.

**Snapshot:** `05-ready`

---

## Part 9: prove every connection works

Do not skip this. Every failure here is ten times cheaper to fix now than mid-run.

### 9.1 Internet and DNS

```
ping -c2 1.1.1.1
nslookup api.anthropic.com
curl -sI https://api.anthropic.com | head -1
```

Any HTTP status, including 401 or 403, means the path works.

### 9.2 IMAP

```
python3 - << 'EOF'
import imaplib
from pathlib import Path
env = dict(l.strip().split('=',1) for l in Path('.env').read_text().splitlines() if '=' in l and not l.startswith('#'))
m = imaplib.IMAP4_SSL(env['MAIL_IMAP_HOST'], int(env['MAIL_IMAP_PORT']))
m.login(env['MAIL_ADDRESS'], env['MAIL_PASSWORD'])
print('IMAP OK,', m.select('INBOX')[1][0].decode(), 'messages')
m.logout()
EOF
```

**Authentication failed:** third-party access is off, or 2FA is still on. Back to Part 1.1.
**Connection refused or timeout:** port 993 blocked outbound, or the provider blocked your IP after repeated failed logins. Type the password once, from the password manager.

### 9.3 SMTP

```
python3 - << 'EOF'
import smtplib, ssl
from email.message import EmailMessage
from pathlib import Path
env = dict(l.strip().split('=',1) for l in Path('.env').read_text().splitlines() if '=' in l and not l.startswith('#'))
msg = EmailMessage()
msg['Subject'] = 'jobbot SMTP test'
msg['From'] = env['MAIL_ADDRESS']
msg['To'] = env['REPORT_TO']
msg.set_content('If you are reading this, the nightly report can reach you.')
s = smtplib.SMTP_SSL(env['MAIL_SMTP_HOST'], int(env['MAIL_SMTP_PORT']), context=ssl.create_default_context())
s.login(env['MAIL_ADDRESS'], env['MAIL_PASSWORD'])
s.send_message(msg); s.quit()
print('SMTP OK, check your inbox')
EOF
```

If 465 times out, try 587 with STARTTLS: set `MAIL_SMTP_PORT=587` and swap `SMTP_SSL` for `SMTP` plus `starttls()`.

### 9.4 ntfy

```
set -a; source .env; set +a
curl -d "jobbot is alive" $NTFY_URL/$NTFY_TOPIC
```

On your phone: ntfy, +, Subscribe to topic, Use another server, `http://jobbot:2586`, your topic name. Tailscale must be connected on the phone for `jobbot` to resolve. Send the curl again. The notification should land within a second or two.

### 9.5 Anthropic API

```
set -a; source .env; set +a
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":20,"messages":[{"role":"user","content":"reply with OK"}]}' | head -c 300
```

Want a JSON response containing `OK`. A 401 means a bad key. A 400 about the model name means the key works and the model string needs updating.

### 9.6 Dashboard from your phone

Turn WiFi off on the phone. On cell data, open `http://jobbot` in the browser. Caddy's welcome page should load. This is the finish line for the whole guide.

---

## Part 10: final checklist

```
timedatectl | grep "Time zone"       # your zone
ip a show eth0 | grep inet           # 192.168.50.50/24
tailscale status | head -1           # jobbot
systemctl is-active caddy            # active
systemctl is-active ntfy             # active
sqlite3 --version                    # a version
ls -la ~/jobbot/.env                 # -rw-------
ls -la ~/jobbot/resume.pdf           # -r--r--r--
```

Plus, from Part 9: IMAP OK, SMTP email received, ntfy push received, API 200, dashboard on cell data.

All pass before you install and run the pipeline (README, Quickstart).

---

## Troubleshooting

**Container has no IP.** VLAN tag is not 50 on the CT config, or the switch port does not carry VLAN 50 tagged.

**Container has an IP but no internet.** *Block Lab to Gateway* is catching egress. Add an *Allow Lab to Internet* policy above it.

**`tailscale up` fails on TUN.** Part 4.2. Stop the container fully, verify the two lines, start again.

**IMAP auth fails.** 2FA still on, or third-party access off. If you retried a wrong password several times, the provider may have blocked your public IP for a while.

**SMTP times out on 465.** Try 587 with STARTTLS.

**Dashboard works at home, not on cell.** Tailscale is not up on the phone, or MagicDNS is off. Try the raw `100.x.y.z` address to isolate which.

**ntfy push never arrives.** Wrong topic name, phone pointed at ntfy.sh instead of `http://jobbot:2586`, or Tailscale down on the phone.

**cron fires at the wrong hour.** Timezone. Part 5.1.

**You broke something.** Roll back to the last snapshot. That is what they are for.
