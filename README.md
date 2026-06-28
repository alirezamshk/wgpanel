# Mikrotik WireGuard Panel v1.1.1

A lightweight web-based management panel for WireGuard peers on MikroTik routers.
Built with Flask + SQLite. Runs as a Docker container or directly inside a MikroTik Alpine container.

**Design & Developed by Alireza.Msh**

---

## Features

- 📊 Live dashboard with online users monitoring
- 👥 Full peer management — add, edit, delete, enable/disable
- 📦 Traffic monitoring with history graphs
- 🔒 Quota & expiry date enforcement (auto-disable)
- 📱 QR code & `.conf` file generation per peer
- 🔑 IP Pool integration with auto IP assignment
- 👤 Multi-user reseller system with data wallet
- ⚙️ First-run setup wizard — no config files needed
- 🔐 Brute-force login protection

---

## Quick Start

### Option 1 — Docker Run (simplest)

```bash
docker run -d \
  --name wgpanel \
  --restart always \
  -p 5050:5050 \
  -v wgpanel_data:/data \
  alirezamsh/wgpanel:latest
```

Open `http://YOUR_SERVER_IP:5050` — the setup wizard will guide you through configuration.

### Option 2 — Docker Compose (recommended)

```bash
curl -O https://raw.githubusercontent.com/alirezamshk/wgpanel/main/docker-compose.yml
docker compose up -d
```

---

## First-Run Setup Wizard

On first launch, the panel shows a 4-step setup wizard:

1. **MikroTik** — host, port, username, password, timezone
2. **WireGuard** — public server endpoint, client DNS
3. **Admin Account** — panel username and password
4. **Confirm** — review and launch

No environment variables needed — everything is configured through the UI.

After setup, all settings can be changed from the **Settings** page inside the panel.

---

## MikroTik Prerequisites

### 1. Enable API

```routeros
/ip service enable api
/ip service set api port=8728
```

### 2. Create dedicated API user (recommended)

```routeros
/user group add name=wgpanel policy=read,write,api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!password,!sensitive,!sniff,!test,!web
/user add name=wgpanel password=STRONG_PASSWORD group=wgpanel
```

### 3. WireGuard interface

```routeros
/interface wireguard add name=wg0 listen-port=51820 mtu=1420
/ip address add address=10.0.0.1/24 interface=wg0
```

### 4. IP Pool (optional but recommended)

```routeros
/ip pool add name=wg-pool ranges=10.0.0.2-10.0.0.254
```

### 5. Firewall rules

```routeros
# Allow WireGuard UDP
/ip firewall filter add chain=input protocol=udp dst-port=51820 action=accept comment="WireGuard"

# Allow API only from panel server IP
/ip firewall filter add chain=input src-address=PANEL_SERVER_IP dst-port=8728 protocol=tcp action=accept comment="WireGuard Panel API"
```

---

## Running Inside MikroTik Container

If you want to run directly inside a MikroTik Alpine container:

### 1. Setup container

```routeros
/system/device-mode/update container=yes
# (confirm with reset button on physical device)

/interface/veth/add name=veth1 address=172.17.0.2/24 gateway=172.17.0.1
/interface/bridge/add name=containers
/ip/address/add address=172.17.0.1/24 interface=containers
/interface/bridge/port/add bridge=containers interface=veth1
/ip/firewall/nat/add chain=srcnat action=masquerade src-address=172.17.0.0/24

/container/add remote-image=alpine:latest interface=veth1 \
  root-dir=disk1/containers/alpine \
  cmd="/bin/sh -c 'while true; do sleep 3600; done'" \
  logging=yes
/container/start 0
```

### 2. Install inside container

```sh
/container/shell 0

apk add python3 py3-pip wireguard-tools libqrencode-tools
pip install --break-system-packages flask routeros-api "qrcode[pil]" pillow

mkdir -p /app /data
wget https://github.com/YOUR_USERNAME/wgpanel/releases/latest/download/wgpanel.tar.gz
tar xzf wgpanel.tar.gz -C /app/
python3 /app/app.py &
```

### 3. Forward port on MikroTik

```routeros
/ip/firewall/nat/add chain=dstnat action=dst-nat \
  dst-port=5050 protocol=tcp \
  to-addresses=172.17.0.2 to-ports=5050
```

---

## Data Persistence

All data is stored in `/data/` volume:

| File | Description |
|------|-------------|
| `/data/wgpanel.db` | SQLite database (peers, users, traffic logs) |
| `/data/.setup_complete` | Setup completion flag |

**Backup:**
```bash
docker cp wgpanel:/data/wgpanel.db ./backup-$(date +%Y%m%d).db
```

**Restore:**
```bash
docker cp ./backup.db wgpanel:/data/wgpanel.db
docker restart wgpanel
```

**Reset setup wizard:**
```bash
docker exec wgpanel rm /data/.setup_complete
docker restart wgpanel
```

---

## Reseller System

Admin can create reseller accounts with:
- **Interface permissions** — which WireGuard interfaces they can use
- **IP range restrictions** — which IP range they can assign to peers
- **Data wallet** — pre-allocated GB balance that gets deducted per peer created
- **Auto-refund** — unused quota is returned to wallet when a peer is deleted

---

## Update

```bash
docker pull alirezamsh/wgpanel:latest
docker compose down && docker compose up -d
```

Data is preserved in the volume.

---

## Security Recommendations

1. Use a **reverse proxy** (nginx) with HTTPS in production
2. **Restrict API access** on MikroTik firewall to panel IP only
3. Create a **dedicated MikroTik user** with minimal permissions
4. **Regular backups** of the `/data` volume

---

## License

MIT License — Free to use and modify.

*Design & Developed by Alireza.Msh*

---

## Support the Project

If you find WireGuard Panel useful, consider supporting development:

| Network | Address |
|---------|---------|
| USDT (BSC / BEP20) | `0x42A49E14dc723f7C6ba9EC007F1B78683F5C91E6` |
| TRX (Tron) | `TMqSDBmotKjVrx3sdPYHswF98pd2mzwP4Q` |
| USDT (TRC20) | `TMqSDBmotKjVrx3sdPYHswF98pd2mzwP4Q` |

⭐ Also consider starring the repo on GitHub — it helps a lot!
