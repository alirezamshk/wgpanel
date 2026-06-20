import os

SETUP_FLAG = '/data/.setup_complete'

def is_setup_complete():
    return os.path.exists(SETUP_FLAG)

def mark_setup_complete():
    os.makedirs('/data', exist_ok=True)
    open(SETUP_FLAG, 'w').write('1')

def apply_to_env(data):
    mapping = {
        'mt_host': 'MT_HOST', 'mt_port': 'MT_PORT',
        'mt_user': 'MT_USER', 'mt_pass': 'MT_PASS',
        'admin_user': 'ADMIN_USER', 'admin_pass': 'ADMIN_PASS',
        'endpoint': 'WG_SERVER_ENDPOINT', 'dns': 'WG_SERVER_DNS',
        'timezone': 'TZ',
    }
    for k, env in mapping.items():
        if data.get(k):
            os.environ[env] = str(data[k])
