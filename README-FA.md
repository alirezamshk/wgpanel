# WireGuard Panel نسخه ۱.۱.۱

پنل مدیریت وب برای پیرهای WireGuard روی روتر MikroTik.
ساخته شده با Flask + SQLite. قابل اجرا به عنوان Docker container یا مستقیماً داخل MikroTik container.

**طراحی و توسعه توسط Alireza.Msh**

---

## ویژگی‌ها

- 📊 داشبورد لایو با نمایش کاربران آنلاین
- 👥 مدیریت کامل پیرها — ساخت، ویرایش، حذف، فعال/غیرفعال
- 📦 مانیتورینگ ترافیک با نمودار تاریخچه
- 🔒 اعمال خودکار حجم مجاز و تاریخ انقضا
- 📱 تولید QR code و فایل کانفیگ برای هر پیر
- 🔑 انتخاب IP از Pool با تخصیص خودکار
- 👤 سیستم ریسلر چندکاربره با کیف داده
- ⚙️ ویزارد راه‌اندازی اولیه — بدون نیاز به فایل کانفیگ
- 🔐 حفاظت در برابر brute-force

---

## راه‌اندازی سریع

### روش ۱ — Docker Run (ساده‌ترین)

```bash
docker run -d \
  --name wgpanel \
  --restart always \
  -p 5050:5050 \
  -v wgpanel_data:/data \
  alirezamsh/wgpanel:latest
```

آدرس `http://IP_سرور:5050` را در مرورگر باز کنید — ویزارد راه‌اندازی شما را راهنمایی می‌کند.

### روش ۲ — Docker Compose (توصیه شده)

```bash
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/wgpanel/main/docker-compose.yml
docker compose up -d
```

---

## ویزارد راه‌اندازی اولیه

در اولین اجرا، پنل یک ویزارد ۴ مرحله‌ای نشان می‌دهد:

1. **MikroTik** — آدرس، پورت، نام کاربری، پسورد، منطقه زمانی
2. **WireGuard** — آدرس عمومی سرور، DNS کلاینت
3. **حساب ادمین** — نام کاربری و پسورد پنل
4. **تأیید** — بررسی نهایی و راه‌اندازی

نیازی به تنظیم متغیرهای محیطی نیست — همه چیز از طریق رابط کاربری تنظیم می‌شود.

بعد از راه‌اندازی، تمام تنظیمات از صفحه **Settings** داخل پنل قابل تغییر است.

---

## پیش‌نیازهای MikroTik

### ۱. فعال‌سازی API

```routeros
/ip service enable api
/ip service set api port=8728
```

### ۲. ساخت یوزر اختصاصی (توصیه شده)

```routeros
/user group add name=wgpanel policy=read,write,api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!password,!sensitive,!sniff,!test,!web
/user add name=wgpanel password=STRONG_PASSWORD group=wgpanel
```

### ۳. ساخت اینترفیس WireGuard

```routeros
/interface wireguard add name=wg0 listen-port=51820 mtu=1420
/ip address add address=10.0.0.1/24 interface=wg0
```

### ۴. IP Pool (اختیاری اما توصیه شده)

```routeros
/ip pool add name=wg-pool ranges=10.0.0.2-10.0.0.254
```

### ۵. قوانین فایروال

```routeros
# اجازه WireGuard UDP
/ip firewall filter add chain=input protocol=udp dst-port=51820 action=accept comment="WireGuard"

# اجازه API فقط از IP سرور پنل
/ip firewall filter add chain=input src-address=IP_سرور_پنل dst-port=8728 protocol=tcp action=accept comment="WireGuard Panel API"
```

---

## اجرا داخل MikroTik Container

### ۱. راه‌اندازی container

```routeros
/system/device-mode/update container=yes

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

### ۲. نصب داخل container

```sh
/container/shell 0

apk add python3 py3-pip wireguard-tools libqrencode-tools
pip install --break-system-packages flask routeros-api "qrcode[pil]" pillow

mkdir -p /app /data
wget https://github.com/YOUR_USERNAME/wgpanel/releases/latest/download/wgpanel.tar.gz
tar xzf wgpanel.tar.gz -C /app/
python3 /app/app.py &
```

### ۳. Forward پورت روی MikroTik

```routeros
/ip/firewall/nat/add chain=dstnat action=dst-nat \
  dst-port=5050 protocol=tcp \
  to-addresses=172.17.0.2 to-ports=5050
```

---

## نگهداری داده‌ها

همه داده‌ها در volume `/data/` ذخیره می‌شوند:

| فایل | توضیح |
|------|-------|
| `/data/wgpanel.db` | دیتابیس SQLite (پیرها، یوزرها، ترافیک) |
| `/data/.setup_complete` | علامت تکمیل راه‌اندازی |

**پشتیبان‌گیری:**
```bash
docker cp wgpanel:/data/wgpanel.db ./backup-$(date +%Y%m%d).db
```

**بازیابی:**
```bash
docker cp ./backup.db wgpanel:/data/wgpanel.db
docker restart wgpanel
```

**ریست ویزارد راه‌اندازی:**
```bash
docker exec wgpanel rm /data/.setup_complete
docker restart wgpanel
```

---

## سیستم ریسلر

ادمین می‌تواند حساب‌های ریسلر با موارد زیر بسازد:
- **مجوز اینترفیس** — کدام اینترفیس‌های WireGuard قابل استفاده باشند
- **محدودیت IP** — کدام رنج IP قابل تخصیص باشد
- **کیف داده** — موجودی GB که به ازای هر پیر ساخته شده کسر می‌شود
- **برگشت خودکار** — حجم مصرف نشده هنگام حذف پیر به کیف برمی‌گردد

---

## آپدیت

```bash
docker pull alirezamsh/wgpanel:latest
docker compose down && docker compose up -d
```

داده‌ها در volume حفظ می‌شوند.

---

## نکات امنیتی

1. در محیط production از **reverse proxy** (nginx) با HTTPS استفاده کنید
2. دسترسی API را در فایروال MikroTik **فقط به IP پنل محدود** کنید
3. یک **یوزر اختصاصی MikroTik** با حداقل دسترسی بسازید
4. **پشتیبان‌گیری منظم** از volume داده انجام دهید

---

## لایسنس

MIT License — آزاد برای استفاده و تغییر.

*طراحی و توسعه توسط Alireza.Msh*
