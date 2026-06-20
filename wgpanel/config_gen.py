import qrcode, io, base64
import mikrotik as mt
from config import WG_SERVER_DNS

def get_interface_info(interface_name):
    """public key و listen port رو از اینترفیس مشخص بخون"""
    interfaces = mt.get_interfaces()
    iface = next((i for i in interfaces if i.get('name') == interface_name), None)
    if not iface:
        return '', '51820'
    return iface.get('public-key', ''), iface.get('listen-port', '51820')

def get_peer_endpoint(interface_name):
    """endpoint رو بساز — IP از config، port از خود اینترفیس"""
    from config import WG_SERVER_ENDPOINT
    _, listen_port = get_interface_info(interface_name)
    
    # اگه endpoint داخل config شامل پورت هست، پورت اینترفیس رو جایگزین کن
    if ':' in WG_SERVER_ENDPOINT:
        server_ip = WG_SERVER_ENDPOINT.rsplit(':', 1)[0]
    else:
        server_ip = WG_SERVER_ENDPOINT
    
    return f"{server_ip}:{listen_port}"

def generate_config(peer):
    import keygen

    # اگه private key نداره، keypair جدید بساز
    if not peer.get('private_key') or peer['private_key'].startswith('#'):
        pub, priv = keygen.regenerate_keypair(peer['id'])
        peer['private_key'] = priv

    # public key و port رو از همون اینترفیسی که peer روشه بخون
    server_pubkey, listen_port = get_interface_info(peer['interface'])
    endpoint = get_peer_endpoint(peer['interface'])

    cfg = f"""[Interface]
PrivateKey = {peer['private_key']}
Address = {peer['allowed_address']}
DNS = {WG_SERVER_DNS}

[Peer]
PublicKey = {server_pubkey}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}
PersistentKeepalive = 25
"""
    return cfg

def generate_qr_base64(config_text):
    qr = qrcode.QRCode(box_size=12, border=3)
    qr.add_data(config_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()
