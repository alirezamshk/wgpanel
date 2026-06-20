from db import get_db

def init_users_db():
    with get_db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS panel_users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT DEFAULT 'reseller',
            full_name   TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            disabled    INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS reseller_permissions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES panel_users(id),
            interface      TEXT NOT NULL,
            ip_range_start TEXT DEFAULT '',
            ip_range_end   TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS reseller_wallet (
            user_id    INTEGER PRIMARY KEY REFERENCES panel_users(id),
            balance_gb REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            type       TEXT NOT NULL,
            amount_gb  REAL NOT NULL,
            note       TEXT DEFAULT '',
            admin_id   INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        try:
            conn.execute('ALTER TABLE peers ADD COLUMN owner_id INTEGER DEFAULT NULL')
        except:
            pass

def get_panel_user(username):
    with get_db() as conn:
        return conn.execute('SELECT * FROM panel_users WHERE username=?', (username,)).fetchone()

def get_panel_user_by_id(uid):
    with get_db() as conn:
        return conn.execute('SELECT * FROM panel_users WHERE id=?', (uid,)).fetchone()

def get_all_panel_users():
    with get_db() as conn:
        return conn.execute('''
            SELECT u.*, COALESCE(w.balance_gb,0) as balance_gb,
                   (SELECT COUNT(*) FROM peers WHERE owner_id=u.id) as peer_count
            FROM panel_users u
            LEFT JOIN reseller_wallet w ON w.user_id=u.id
            ORDER BY u.created_at DESC
        ''').fetchall()

def create_panel_user(username, password_hash, role, full_name=''):
    with get_db() as conn:
        conn.execute('INSERT INTO panel_users (username,password,role,full_name) VALUES (?,?,?,?)',
                     (username, password_hash, role, full_name))
        uid = conn.execute('SELECT id FROM panel_users WHERE username=?', (username,)).fetchone()['id']
        conn.execute('INSERT OR IGNORE INTO reseller_wallet (user_id,balance_gb) VALUES (?,0)', (uid,))
        return uid

def update_panel_user(uid, full_name, disabled):
    with get_db() as conn:
        conn.execute('UPDATE panel_users SET full_name=?,disabled=? WHERE id=?',
                     (full_name, disabled, uid))

def change_password(uid, password_hash):
    with get_db() as conn:
        conn.execute('UPDATE panel_users SET password=? WHERE id=?', (password_hash, uid))

def delete_panel_user(uid):
    with get_db() as conn:
        conn.execute('DELETE FROM reseller_permissions WHERE user_id=?', (uid,))
        conn.execute('DELETE FROM wallet_transactions WHERE user_id=?', (uid,))
        conn.execute('DELETE FROM reseller_wallet WHERE user_id=?', (uid,))
        conn.execute('UPDATE peers SET owner_id=NULL WHERE owner_id=?', (uid,))
        conn.execute('DELETE FROM panel_users WHERE id=?', (uid,))

def set_permissions(uid, perms):
    with get_db() as conn:
        conn.execute('DELETE FROM reseller_permissions WHERE user_id=?', (uid,))
        for p in perms:
            conn.execute('''INSERT INTO reseller_permissions
                (user_id,interface,ip_range_start,ip_range_end,allowed_pool) VALUES (?,?,?,?,?)''',
                (uid, p['interface'], p.get('start',''), p.get('end',''), p.get('pools','')))

def get_permissions(uid):
    with get_db() as conn:
        return conn.execute('SELECT * FROM reseller_permissions WHERE user_id=?', (uid,)).fetchall()

def get_balance(uid):
    with get_db() as conn:
        r = conn.execute('SELECT balance_gb FROM reseller_wallet WHERE user_id=?', (uid,)).fetchone()
        return float(r['balance_gb']) if r else 0.0

def charge_wallet(uid, amount_gb, admin_id, note=''):
    with get_db() as conn:
        conn.execute('UPDATE reseller_wallet SET balance_gb=balance_gb+? WHERE user_id=?', (amount_gb, uid))
        conn.execute('INSERT INTO wallet_transactions (user_id,type,amount_gb,note,admin_id) VALUES (?,?,?,?,?)',
                     (uid, 'charge', amount_gb, note, admin_id))

def deduct_wallet(uid, amount_gb, note=''):
    bal = get_balance(uid)
    if bal < amount_gb:
        raise ValueError(f"Insufficient balance ({bal:.1f} GB available, {amount_gb:.1f} GB needed)")
    with get_db() as conn:
        conn.execute('UPDATE reseller_wallet SET balance_gb=balance_gb-? WHERE user_id=?', (amount_gb, uid))
        conn.execute('INSERT INTO wallet_transactions (user_id,type,amount_gb,note) VALUES (?,?,?,?)',
                     (uid, 'deduct', amount_gb, note))

def get_transactions(uid, limit=50):
    with get_db() as conn:
        return conn.execute('''
            SELECT t.*, u.username as admin_name
            FROM wallet_transactions t
            LEFT JOIN panel_users u ON u.id=t.admin_id
            WHERE t.user_id=? ORDER BY t.created_at DESC LIMIT ?
        ''', (uid, limit)).fetchall()

def get_peers_by_owner(uid):
    with get_db() as conn:
        return conn.execute('SELECT * FROM peers WHERE owner_id=? ORDER BY created_at DESC', (uid,)).fetchall()

def ip_in_range(ip_str, start_str, end_str):
    try:
        ip    = list(map(int, ip_str.split('/')[0].split('.')))
        start = list(map(int, start_str.split('.')))
        end   = list(map(int, end_str.split('.')))
        return start <= ip <= end
    except:
        return False

def is_ip_allowed(uid, ip_str, interface):
    perms = get_permissions(uid)
    for p in perms:
        if p['interface'] != interface:
            continue
        if not p['ip_range_start'] or not p['ip_range_end']:
            return True
        if ip_in_range(ip_str, p['ip_range_start'], p['ip_range_end']):
            return True
    return False

def get_allowed_pools(uid):
    """pool هایی که reseller مجاز به استفاده‌شونه"""
    with get_db() as conn:
        return conn.execute('''
            SELECT DISTINCT allowed_pool FROM reseller_permissions
            WHERE user_id=? AND allowed_pool IS NOT NULL AND allowed_pool != ''
        ''', (uid,)).fetchall()

def init_pool_column():
    """اضافه کردن ستون allowed_pool اگه نبود"""
    with get_db() as conn:
        try:
            conn.execute('ALTER TABLE reseller_permissions ADD COLUMN allowed_pool TEXT DEFAULT ""')
        except:
            pass
