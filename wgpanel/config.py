import os

VERSION = '1.1.1'

MT_HOST = os.environ.get('MT_HOST', '')
MT_USER = os.environ.get('MT_USER', 'admin')
MT_PASS = os.environ.get('MT_PASS', '')
MT_PORT = int(os.environ.get('MT_PORT', 8728))
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', '')
SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24).hex())
WG_SERVER_ENDPOINT = os.environ.get('WG_SERVER_ENDPOINT', '')
WG_SERVER_DNS = os.environ.get('WG_SERVER_DNS', '8.8.8.8')
COLLECT_INTERVAL = int(os.environ.get('COLLECT_INTERVAL', 300))
DB_PATH = os.environ.get('DB_PATH', '/data/wgpanel.db')
