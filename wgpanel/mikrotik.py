import routeros_api
import threading
import time
from config import MT_HOST, MT_USER, MT_PASS, MT_PORT

# ── Connection pool ────────────────────────────────────────────
_lock = threading.Lock()
_api  = None
_last_connect = 0

def get_connection():
    global _api, _last_connect
    with _lock:
        try:
            if _api:
                # تست اینکه connection زنده‌ست
                _api.get_resource('/system/identity').get()
                return _api
        except:
            _api = None

        pool = routeros_api.RouterOsApiPool(
            MT_HOST, username=MT_USER, password=MT_PASS,
            port=MT_PORT, plaintext_login=True
        )
        _api = pool.get_api()
        _last_connect = time.time()
        return _api

# ── Cache لایه ────────────────────────────────────────────────
_cache = {}
_cache_lock = threading.Lock()

def cached(key, ttl=10):
    """decorator-style cache با TTL ثانیه"""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            with _cache_lock:
                entry = _cache.get(key)
                if entry and time.time() - entry['t'] < ttl:
                    return entry['v']
            result = fn(*args, **kwargs)
            with _cache_lock:
                _cache[key] = {'v': result, 't': time.time()}
            return result
        return wrapper
    return decorator

def invalidate(key):
    with _cache_lock:
        _cache.pop(key, None)

# ── Interfaces ────────────────────────────────────────────────
@cached('interfaces', ttl=30)
def get_interfaces():
    return get_connection().get_resource('/interface/wireguard').get()

# ── Peers ─────────────────────────────────────────────────────
@cached('peers', ttl=8)
def get_peers():
    return get_connection().get_resource('/interface/wireguard/peers').get()

def get_peer(peer_id):
    for p in get_peers():
        if p.get('id') == peer_id:
            return p
    return None

@cached('pools', ttl=60)
def get_ip_pools():
    return get_connection().get_resource('/ip/pool').get()

def get_next_ip_from_pool(pool_name):
    pools = get_ip_pools()
    pool  = next((p for p in pools if p.get('name') == pool_name), None)
    if not pool:
        return None

    peers    = get_peers()
    used_ips = set()
    for p in peers:
        addr = p.get('allowed-address', '')
        if addr:
            used_ips.add(addr.split('/')[0])

    for r in pool.get('ranges', '').split(','):
        r = r.strip()
        if '-' in r:
            start, end = r.split('-')
            sp = list(map(int, start.strip().split('.')))
            ep = list(map(int, end.strip().split('.')))
            for i in range(sp[3], ep[3] + 1):
                ip = f"{sp[0]}.{sp[1]}.{sp[2]}.{i}"
                if ip not in used_ips:
                    return ip + '/32'
    return None

def add_peer(interface, allowed_address, comment='', endpoint_address='',
             endpoint_port='', persistent_keepalive='', public_key='',
             preshared_key='', disabled='false'):
    import subprocess
    if not public_key:
        priv = subprocess.check_output(['wg', 'genkey']).decode().strip()
        pub  = subprocess.check_output(['wg', 'pubkey'], input=priv.encode()).decode().strip()
    else:
        priv = ''
        pub  = public_key

    params = {
        'interface':     interface,
        'allowed-address': allowed_address,
        'public-key':    pub,
        'comment':       comment,
        'disabled':      disabled,
    }
    if preshared_key:        params['preshared-key']        = preshared_key
    if endpoint_address:     params['endpoint-address']     = endpoint_address
    if endpoint_port:        params['endpoint-port']        = endpoint_port
    if persistent_keepalive: params['persistent-keepalive'] = persistent_keepalive

    get_connection().get_resource('/interface/wireguard/peers').add(**params)
    invalidate('peers')
    return pub, priv

def remove_peer(peer_id):
    get_connection().get_resource('/interface/wireguard/peers').remove(id=peer_id)
    invalidate('peers')

def enable_peer(peer_id):
    get_connection().get_resource('/interface/wireguard/peers').set(id=peer_id, disabled='false')
    invalidate('peers')

def disable_peer(peer_id):
    get_connection().get_resource('/interface/wireguard/peers').set(id=peer_id, disabled='true')
    invalidate('peers')

def update_peer(peer_id, **kwargs):
    get_connection().get_resource('/interface/wireguard/peers').set(id=peer_id, **kwargs)
    invalidate('peers')

@cached('traffic', ttl=8)
def get_peers_traffic():
    peers = get_peers()
    result = []
    for p in peers:
        result.append({
            'public_key':      p.get('public-key', ''),
            'interface':       p.get('interface', ''),
            'tx':              int(p.get('tx', 0) or 0),
            'rx':              int(p.get('rx', 0) or 0),
            'last_handshake':  p.get('last-handshake', ''),
            'allowed_address': p.get('allowed-address', ''),
            'comment':         p.get('comment', ''),
            'disabled':        p.get('disabled', 'false'),
            'mt_id':           p.get('id', ''),
        })
    return result
