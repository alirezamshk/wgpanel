from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
from functools import wraps
from datetime import datetime
import time

import db, db_users, mikrotik, scheduler, config_gen, queue_worker
import config
from auth import hash_password, verify_password
from config import SECRET_KEY, ADMIN_USER, ADMIN_PASS

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

db.init_db()
db_users.init_users_db()

def import_existing_peers():
    try:
        mt_peers = mikrotik.get_peers_traffic()
        for p in mt_peers:
            if not db.get_peer_by_pubkey(p['public_key']):
                db.upsert_peer(mt_id=p['mt_id'], public_key=p['public_key'],
                    private_key='', interface=p['interface'],
                    allowed_address=p['allowed_address'], comment=p['comment'])
        print(f"[startup] Synced {len(mt_peers)} peers")
    except Exception as e:
        print(f"[startup] {e}")

# اگه setup قبلاً انجام شده، مستقیم راه‌اندازی کن
import setup_wizard as _sw
if _sw.is_setup_complete():
    import_existing_peers()
    scheduler.start()
    queue_worker.start()

# ── Brute force ────────────────────────────────────────────────
FAILED = {}
MAX_ATTEMPTS = 5
LOCKOUT = 300

def check_brute(ip):
    e = FAILED.get(ip, {'count':0,'until':0})
    if e['until'] > time.time():
        return False, int(e['until']-time.time())
    return True, 0

def record_fail(ip):
    e = FAILED.get(ip, {'count':0,'until':0})
    e['count'] += 1
    if e['count'] >= MAX_ATTEMPTS:
        e['until'] = time.time() + LOCKOUT
        e['count'] = 0
    FAILED[ip] = e

def record_ok(ip):
    FAILED.pop(ip, None)

# ── Decorators ─────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if time.time() - session.get('last_active',0) > 3600:
            session.clear()
            return redirect(url_for('login'))
        session['last_active'] = time.time()
        return f(*a, **kw)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Access denied.', 'error')
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return d

# ── Helpers ────────────────────────────────────────────────────
def is_admin():
    return session.get('role') == 'admin'

def current_uid():
    return session.get('user_id', 0)

def get_allowed_interfaces():
    if is_admin():
        try: return mikrotik.get_interfaces()
        except: return []
    perms = db_users.get_permissions(current_uid())
    allowed = {p['interface'] for p in perms}
    try: return [i for i in mikrotik.get_interfaces() if i.get('name') in allowed]
    except: return []

# ── Auth ───────────────────────────────────────────────────────

# ══════════════════════════════════════════════
# Setup Wizard
# ══════════════════════════════════════════════
import setup_wizard

@app.before_request
def check_setup():
    """اگه setup نشده، redirect به wizard"""
    if request.endpoint in ('setup', 'wizard_test', 'static'):
        return
    if not setup_wizard.is_setup_complete():
        return redirect(url_for('setup'))

@app.route('/wizard/test', methods=['POST'])
def wizard_test():
    """تست اتصال به MikroTik از wizard"""
    import routeros_api
    data = request.get_json()
    try:
        pool = routeros_api.RouterOsApiPool(
            data['host'], username=data['user'], password=data['pass'],
            port=int(data.get('port', 8728)), plaintext_login=True
        )
        api = pool.get_api()
        ifaces = api.get_resource('/interface/wireguard').get()
        pool.disconnect()
        return jsonify({'ok': True, 'interfaces': len(ifaces)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if setup_wizard.is_setup_complete():
        return redirect(url_for('dashboard'))

    step  = int(request.form.get('current_step', 1))
    data  = {k: request.form.get(k, '') for k in [
        'mt_host','mt_port','mt_user','mt_pass',
        'endpoint','dns','admin_user','admin_pass','timezone'
    ]}
    error = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'next':
            # validation per step
            if step == 1:
                if not data['mt_host'] or not data['mt_pass']:
                    error = 'MikroTik host and password are required.'
                else:
                    step = 2
            elif step == 2:
                if not data['endpoint']:
                    error = 'Server endpoint is required.'
                else:
                    step = 3
            elif step == 3:
                if not data['admin_user'] or not data['admin_pass']:
                    error = 'Admin username and password are required.'
                elif len(data['admin_pass']) < 6:
                    error = 'Password must be at least 6 characters.'
                else:
                    step = 4

        elif action == 'back':
            step = max(1, step - 1)

        elif action == 'finish':
            try:
                import os, importlib

                # اعمال تنظیمات به environment
                setup_wizard.apply_to_env(data)

                # آپدیت مستقیم config module
                import config
                config.MT_HOST            = os.environ.get('MT_HOST', '')
                config.MT_USER            = os.environ.get('MT_USER', 'admin')
                config.MT_PASS            = os.environ.get('MT_PASS', '')
                config.MT_PORT            = int(os.environ.get('MT_PORT', 8728))
                config.ADMIN_USER         = os.environ.get('ADMIN_USER', 'admin')
                config.ADMIN_PASS         = os.environ.get('ADMIN_PASS', '')
                config.WG_SERVER_ENDPOINT = os.environ.get('WG_SERVER_ENDPOINT', '')
                config.WG_SERVER_DNS      = os.environ.get('WG_SERVER_DNS', '8.8.8.8')

                # reset mikrotik connection cache
                mikrotik._api = None

                # آپدیت app secret key
                app.secret_key = os.urandom(24).hex()

                # init db
                db.init_db()
                db_users.init_users_db()

                # import peers از MikroTik
                try:
                    mt_peers = mikrotik.get_peers_traffic()
                    for p in mt_peers:
                        if not db.get_peer_by_pubkey(p['public_key']):
                            db.upsert_peer(mt_id=p['mt_id'], public_key=p['public_key'],
                                private_key='', interface=p['interface'],
                                allowed_address=p['allowed_address'], comment=p['comment'])
                except:
                    pass

                # start scheduler
                scheduler.start()
                queue_worker.start()

                # mark complete
                setup_wizard.mark_setup_complete()
                return redirect(url_for('login'))
            except Exception as e:
                error = f'Setup failed: {e}'
                step  = 4

    return render_template('setup.html', step=step, data=data, error=error)


# ══════════════════════════════════════════════
# Setup Wizard

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username','')
        password = request.form.get('password','')
        ip = request.remote_addr
        ok, wait = check_brute(ip)
        if not ok:
            error = f'Too many attempts. Wait {wait}s.'
        elif username == config.ADMIN_USER and password == config.ADMIN_PASS:
            record_ok(ip)
            session.permanent = True
            session.update({'logged_in':True,'role':'admin',
                'username':username,'user_id':0,'last_active':time.time()})
            return redirect(url_for('dashboard'))
        else:
            user = db_users.get_panel_user(username)
            if user and not user['disabled'] and verify_password(password, user['password']):
                record_ok(ip)
                session.permanent = True
                session.update({'logged_in':True,'role':user['role'],
                    'username':username,'user_id':user['id'],'last_active':time.time(),
                    'wallet_balance': db_users.get_balance(user['id'])})
                return redirect(url_for('dashboard'))
            else:
                record_fail(ip)
                cnt = FAILED.get(ip,{}).get('count',0)
                error = f'Invalid credentials. {max(0,MAX_ATTEMPTS-cnt)} attempts left.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Dashboard ──────────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    uid = current_uid()
    if is_admin():
        peers = db.get_all_peers()
        wallet_balance = None
        transactions   = []
    else:
        peers          = db_users.get_peers_by_owner(uid)
        wallet_balance = db_users.get_balance(uid)
        transactions   = db_users.get_transactions(uid, limit=100)
    try: interfaces = mikrotik.get_interfaces()
    except: interfaces = []
    return render_template('dashboard.html',
        peers=peers, interfaces=interfaces,
        total_peers=len(peers),
        active_peers=sum(1 for p in peers if not p['disabled']),
        total_tx=sum(p['total_tx'] or 0 for p in peers),
        total_rx=sum(p['total_rx'] or 0 for p in peers),
        wallet_balance=wallet_balance,
        transactions=transactions)

# ── Interfaces ─────────────────────────────────────────────────
@app.route('/interfaces')
@login_required
def interfaces():
    try: ifaces = mikrotik.get_interfaces()
    except: ifaces = []
    return render_template('interfaces.html', interfaces=ifaces)

# ── Peers ──────────────────────────────────────────────────────
@app.route('/peers')
@login_required
def peers_list():
    uid = current_uid()
    try: mt_map = {p['public_key']: p for p in mikrotik.get_peers_traffic()}
    except: mt_map = {}

    if is_admin():
        db_peers = db.get_all_peers()
        # اضافه کردن اسم owner برای admin
        all_users = {u['id']: u['username'] for u in db_users.get_all_panel_users()}
    else:
        db_peers = db_users.get_peers_by_owner(uid)
        all_users = {}

    try: all_pools = mikrotik.get_ip_pools()
    except: all_pools = []
    ifaces = get_allowed_interfaces()

    # فقط pool های مجاز برای reseller
    if not is_admin():
        perms = db_users.get_permissions(current_uid())
        allowed_pool_names = set()
        for p in perms:
            if p['allowed_pool']:
                for pname in p['allowed_pool'].split(','):
                    if pname.strip():
                        allowed_pool_names.add(pname.strip())
        pools = [p for p in all_pools if p.get('name') in allowed_pool_names]
    else:
        pools = all_pools

    today  = datetime.now().strftime('%Y-%m-%d')

    combined = []
    for p in db_peers:
        mt = mt_map.get(p['public_key'], {})
        owner_name = all_users.get(p['owner_id'], '—') if p['owner_id'] else 'Admin'
        combined.append({**dict(p),
            'live_tx': mt.get('tx',0), 'live_rx': mt.get('rx',0),
            'last_handshake': mt.get('last_handshake',''),
            'owner_name': owner_name})

    return render_template('peers.html', peers=combined,
        interfaces=ifaces, pools=pools, today=today,
        wallet_balance=db_users.get_balance(uid) if not is_admin() else None)

@app.route('/api/pool/next-ip')
@login_required
def api_next_ip():
    pool = request.args.get('pool')
    ip = mikrotik.get_next_ip_from_pool(pool) if pool else None
    return jsonify({'ip': ip})

@app.route('/peers/add', methods=['POST'])
@login_required
def add_peer():
    uid          = current_uid()
    interface    = request.form['interface']
    allowed_addr = request.form['allowed_address']
    comment      = request.form.get('comment','')
    quota_gb     = float(request.form.get('quota_gb',0) or 0)
    expiry_date  = request.form.get('expiry_date') or None
    public_key   = request.form.get('public_key','').strip()
    psk          = request.form.get('preshared_key','').strip()
    keepalive    = request.form.get('keepalive','').strip()
    quota_bytes  = int(quota_gb * 1024**3) if quota_gb else 0

    if not is_admin():
        # چک interface permission
        perms = db_users.get_permissions(uid)
        if interface not in [p['interface'] for p in perms]:
            flash('You are not allowed to use this interface.', 'error')
            return redirect(url_for('peers_list'))
        # چک IP range
        if not db_users.is_ip_allowed(uid, allowed_addr, interface):
            flash('IP address is outside your allowed range.', 'error')
            return redirect(url_for('peers_list'))
        # quota اجباری
        if quota_gb <= 0:
            flash('Resellers must set a quota for each peer.', 'error')
            return redirect(url_for('peers_list'))
        # کسر از wallet
        try:
            db_users.deduct_wallet(uid, quota_gb, note=f'Peer: {comment} ({allowed_addr})')
            session['wallet_balance'] = db_users.get_balance(uid)
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('peers_list'))

    try:
        pub, priv = mikrotik.add_peer(interface=interface, allowed_address=allowed_addr,
            comment=comment, public_key=public_key, preshared_key=psk,
            persistent_keepalive=keepalive)
        mt_list = mikrotik.get_peers_traffic()
        mt_id   = next((p['mt_id'] for p in mt_list if p['public_key']==pub), None)

        with db.get_db() as conn:
            conn.execute('''
                INSERT INTO peers (mt_id,public_key,private_key,interface,allowed_address,
                                   comment,quota_bytes,expiry_date,owner_id)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(public_key) DO UPDATE SET
                    mt_id=excluded.mt_id, comment=excluded.comment
            ''', (mt_id, pub, priv, interface, allowed_addr,
                  comment, quota_bytes, expiry_date, uid if uid!=0 else None))

        flash(f'Peer "{comment}" created.', 'success')
    except Exception as e:
        # اگه peer ساخته نشد، wallet رو برگردون
        if not is_admin() and quota_gb > 0:
            db_users.charge_wallet(uid, quota_gb, 0, note=f'Refund: failed peer {comment}')
            session['wallet_balance'] = db_users.get_balance(uid)
        flash(f'Error: {e}', 'error')
    return redirect(url_for('peers_list'))

@app.route('/peers/<int:peer_id>')
@login_required
def peer_detail(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer:
        flash('Peer not found.', 'error')
        return redirect(url_for('peers_list'))
    # reseller فقط پیرهای خودش
    if not is_admin() and peer['owner_id'] != current_uid():
        flash('Access denied.', 'error')
        return redirect(url_for('peers_list'))
    history = db.get_traffic_history(peer_id, limit=48)
    try:
        ifaces  = mikrotik.get_interfaces()
        mt_list = mikrotik.get_peers()
        mt_peer = next((p for p in mt_list if p.get('id')==peer['mt_id']), None)
    except:
        ifaces  = []
        mt_peer = None
    return render_template('peer_detail.html', peer=peer,
        history=history, interfaces=ifaces, mt_peer=mt_peer)

@app.route('/peers/<int:peer_id>/update', methods=['POST'])
@login_required
def update_peer(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer: return redirect(url_for('peers_list'))
    if not is_admin() and peer['owner_id'] != current_uid():
        flash('Access denied.', 'error')
        return redirect(url_for('peers_list'))
    comment     = request.form.get('comment','')
    quota_gb    = float(request.form.get('quota_gb',0) or 0)
    expiry_date = request.form.get('expiry_date') or None
    quota_bytes = int(quota_gb * 1024**3) if quota_gb else 0
    db.update_peer_settings(peer_id, comment, quota_bytes, expiry_date)
    if peer['mt_id']:
        queue_worker.enqueue('update_peer', mt_id=peer['mt_id'], comment=comment)
    flash('Settings saved.', 'success')
    return redirect(url_for('peers_list'))

@app.route('/peers/<int:peer_id>/toggle', methods=['POST'])
@login_required
def toggle_peer(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer: return jsonify({'error':'not found'}), 404
    if not is_admin() and peer['owner_id'] != current_uid():
        return jsonify({'error':'access denied'}), 403
    new_state = not peer['disabled']
    db.set_peer_disabled(peer_id, new_state)
    queue_worker.enqueue('disable_peer' if new_state else 'enable_peer', mt_id=peer['mt_id'])
    return jsonify({'disabled': new_state})

@app.route('/peers/<int:peer_id>/delete', methods=['POST'])
@login_required
def delete_peer(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer: return redirect(url_for('peers_list'))
    if not is_admin() and peer['owner_id'] != current_uid():
        flash('Access denied.', 'error')
        return redirect(url_for('peers_list'))

    # محاسبه و برگشت مانده quota به wallet
    owner_id = peer['owner_id']
    if owner_id:
        quota_bytes = peer['quota_bytes'] or 0
        used_bytes  = (peer['total_tx'] or 0) + (peer['total_rx'] or 0)
        refund_bytes = max(0, quota_bytes - used_bytes)
        if refund_bytes > 0:
            refund_gb = refund_bytes / (1024**3)
            used_gb   = used_bytes / (1024**3)
            quota_gb  = quota_bytes / (1024**3)
            note = f"Refund: peer '{peer['comment'] or peer['allowed_address']}' deleted — used {used_gb:.2f}/{quota_gb:.1f} GB"
            db_users.charge_wallet(owner_id, refund_gb, 0, note=note)
            # آپدیت session اگه خودشه
            if owner_id == current_uid():
                session['wallet_balance'] = db_users.get_balance(owner_id)
            flash(f'Peer deleted. {refund_gb:.2f} GB refunded to wallet.', 'success')
        else:
            flash('Peer deleted. No quota remaining to refund.', 'success')
    else:
        flash('Peer deleted.', 'success')

    if peer['mt_id']:
        queue_worker.enqueue('delete_peer', mt_id=peer['mt_id'])
    db.delete_peer_db(peer_id)
    return redirect(url_for('peers_list'))

@app.route('/peers/<int:peer_id>/reset_traffic', methods=['POST'])
@admin_required
def reset_traffic(peer_id):
    with db.get_db() as conn:
        conn.execute('UPDATE peers SET total_tx=0,total_rx=0,last_tx=0,last_rx=0 WHERE id=?',(peer_id,))
        conn.execute('DELETE FROM traffic_log WHERE peer_id=?',(peer_id,))
    flash('Traffic reset.', 'success')
    return redirect(url_for('peer_detail', peer_id=peer_id))

@app.route('/peers/<int:peer_id>/config')
@login_required
def download_config(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer: return redirect(url_for('peers_list'))
    if not is_admin() and peer['owner_id'] != current_uid():
        flash('Access denied.', 'error')
        return redirect(url_for('peers_list'))
    cfg  = config_gen.generate_config(dict(peer))
    name = (peer['comment'] or 'peer').replace(' ','_')
    return Response(cfg, mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename={name}.conf'})

@app.route('/peers/<int:peer_id>/qr')
@login_required
def show_qr(peer_id):
    peer = db.get_peer_by_id(peer_id)
    if not peer: return jsonify({'error':'not found'}), 404
    if not is_admin() and peer['owner_id'] != current_uid():
        return jsonify({'error':'access denied'}), 403
    cfg    = config_gen.generate_config(dict(peer))
    qr_b64 = config_gen.generate_qr_base64(cfg)
    return jsonify({'qr': qr_b64, 'config': cfg})

# ── Users (admin only) ─────────────────────────────────────────
@app.route('/users')
@admin_required
def users_list():
    users = db_users.get_all_panel_users()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['POST'])
@admin_required
def add_user():
    username  = request.form.get('username','').strip()
    password  = request.form.get('password','')
    full_name = request.form.get('full_name','')
    role      = request.form.get('role','reseller')
    if not username or not password:
        flash('Username and password required.', 'error')
        return redirect(url_for('users_list'))
    try:
        uid = db_users.create_panel_user(username, hash_password(password), role, full_name)
        perms = _parse_perms(request)
        if perms: db_users.set_permissions(uid, perms)
        flash(f'User "{username}" created.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    return redirect(url_for('users_list'))

@app.route('/users/<int:uid>')
@admin_required
def user_detail(uid):
    user = db_users.get_panel_user_by_id(uid)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('users_list'))
    try:
        ifaces = mikrotik.get_interfaces()
        pools  = mikrotik.get_ip_pools()
    except:
        ifaces = []
        pools  = []
    return render_template('user_detail.html',
        user=user,
        perms=db_users.get_permissions(uid),
        txns=db_users.get_transactions(uid, 30),
        peers=db_users.get_peers_by_owner(uid),
        balance=db_users.get_balance(uid),
        interfaces=ifaces,
        pools=pools)

@app.route('/users/<int:uid>/update', methods=['POST'])
@admin_required
def update_user(uid):
    db_users.update_panel_user(uid,
        request.form.get('full_name',''),
        1 if request.form.get('disabled') else 0)
    db_users.set_permissions(uid, _parse_perms(request))
    if request.form.get('new_password'):
        db_users.change_password(uid, hash_password(request.form['new_password']))
    flash('User updated.', 'success')
    return redirect(url_for('user_detail', uid=uid))

@app.route('/users/<int:uid>/charge', methods=['POST'])
@admin_required
def charge_wallet(uid):
    amount = float(request.form.get('amount_gb',0) or 0)
    if amount <= 0:
        flash('Amount must be > 0.', 'error')
    else:
        db_users.charge_wallet(uid, amount, current_uid(), request.form.get('note',''))
        flash(f'{amount:.1f} GB charged.', 'success')
    return redirect(url_for('user_detail', uid=uid))

@app.route('/users/<int:uid>/delete', methods=['POST'])
@admin_required
def delete_user(uid):
    db_users.delete_panel_user(uid)
    flash('User deleted.', 'success')
    return redirect(url_for('users_list'))

def _parse_perms(req):
    perms = []
    for iface in req.form.getlist('interfaces'):
        pools = req.form.getlist(f'pool_{iface}')
        perms.append({'interface': iface,
            'start': req.form.get(f'ip_start_{iface}',''),
            'end':   req.form.get(f'ip_end_{iface}',''),
            'pools': ','.join(pools)})
    return perms

# ── Settings ───────────────────────────────────────────────────
CONFIG_FILE = '/wgpanel/config.py'

def read_config():
    cfg = {}
    with open(CONFIG_FILE) as f: exec(f.read(), cfg)
    return cfg

def write_config_value(key, value):
    with open(CONFIG_FILE) as f: lines = f.readlines()
    out, found = [], False
    for line in lines:
        if line.startswith(key+' =') or line.startswith(key+'='):
            if isinstance(value, str) and not value.lstrip('-').isdigit():
                out.append(f"{key} = '{value}'\n")
            else:
                out.append(f"{key} = {value}\n")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key} = '{value}'\n")
    with open(CONFIG_FILE,'w') as f: f.writelines(out)

@app.route('/settings', methods=['GET','POST'])
@admin_required
def settings():
    tab = request.args.get('tab','mikrotik')
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'mikrotik':
                write_config_value('MT_HOST', request.form['mt_host'])
                write_config_value('MT_USER', request.form['mt_user'])
                write_config_value('MT_PORT', request.form['mt_port'])
                if request.form.get('mt_pass'):
                    write_config_value('MT_PASS', request.form['mt_pass'])
                mikrotik._api = None
            elif action == 'wireguard':
                write_config_value('WG_SERVER_ENDPOINT', request.form['endpoint'])
                write_config_value('WG_SERVER_DNS', request.form['dns'])
            elif action == 'panel':
                write_config_value('ADMIN_USER', request.form['admin_user'])
                write_config_value('COLLECT_INTERVAL', request.form['interval'])
                if request.form.get('admin_pass'):
                    write_config_value('ADMIN_PASS', request.form['admin_pass'])
            flash('Settings saved.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'error')
        return redirect(url_for('settings', tab=action or tab))
    return render_template('settings.html', cfg=read_config(), tab=tab)

# ── API ────────────────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def api_stats():
    uid = current_uid()
    peers = db.get_all_peers() if is_admin() else db_users.get_peers_by_owner(uid)
    return jsonify({'total':len(peers), 'active':sum(1 for p in peers if not p['disabled']),
        'total_tx':sum(p['total_tx'] or 0 for p in peers),
        'total_rx':sum(p['total_rx'] or 0 for p in peers)})

@app.route('/api/online')
@login_required
def api_online():
    import re
    def is_online(hs):
        if not hs or hs in ('never',''): return False
        try:
            total = sum(int(v)*{'s':1,'m':60,'h':3600,'d':86400,'w':604800}[u]
                        for v,u in re.findall(r'(\d+)([smhdw])', hs))
            return total < 180
        except: return False
    try:
        mt_peers = mikrotik.get_peers_traffic()
        uid = current_uid()
        db_map = {p['public_key']: dict(p) for p in
                  (db.get_all_peers() if is_admin() else db_users.get_peers_by_owner(uid))}
        online = [{'name': db_map.get(p['public_key'],{}).get('comment') or p.get('comment') or '—',
                   'address': p['allowed_address'], 'interface': p['interface'],
                   'last_handshake': p['last_handshake'], 'tx': p['tx'], 'rx': p['rx']}
                  for p in mt_peers if is_online(p.get('last_handshake',''))
                  and (is_admin() or p['public_key'] in db_map)]
        return jsonify({'count': len(online), 'peers': online})
    except Exception as e:
        return jsonify({'count':0, 'peers':[], 'error': str(e)})

@app.route('/api/peers/<int:peer_id>/history')
@login_required
def api_peer_history(peer_id):
    return jsonify([dict(h) for h in db.get_traffic_history(peer_id, 48)])

# ── Filters ────────────────────────────────────────────────────
@app.template_filter('humanize')
def humanize(n):
    n = n or 0
    for u in ['B','KB','MB','GB','TB']:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

@app.template_filter('quota_pct')
def quota_pct(peer):
    if not peer['quota_bytes']: return 0
    return min(100, int(((peer['total_tx'] or 0)+(peer['total_rx'] or 0))/peer['quota_bytes']*100))


@app.route('/api/reseller/available-ips')
@login_required
def api_available_ips():
    """IPs آزاد داخل range مجاز reseller برای یه interface خاص"""
    uid       = current_uid()
    interface = request.args.get('interface','')
    if not interface:
        return jsonify({'ips': []})

    # اگه admin بود، چیزی برنگردون (admin از pool استفاده میکنه)
    if is_admin():
        return jsonify({'ips': []})

    perms = db_users.get_permissions(uid)
    perm  = next((p for p in perms if p['interface'] == interface), None)
    if not perm or not perm['ip_range_start'] or not perm['ip_range_end']:
        return jsonify({'ips': [], 'error': 'No IP range defined for this interface'})

    # همه peerهای موجود روی این interface
    try:
        mt_peers = mikrotik.get_peers()
        used_ips = set()
        for p in mt_peers:
            if p.get('interface') == interface:
                addr = p.get('allowed-address','')
                if addr:
                    used_ips.add(addr.split('/')[0])
    except:
        used_ips = set()

    # تولید لیست IP های آزاد
    def ip_to_int(ip):
        parts = list(map(int, ip.split('.')))
        return (parts[0]<<24)+(parts[1]<<16)+(parts[2]<<8)+parts[3]

    def int_to_ip(n):
        return f"{(n>>24)&255}.{(n>>16)&255}.{(n>>8)&255}.{n&255}"

    try:
        start = ip_to_int(perm['ip_range_start'])
        end   = ip_to_int(perm['ip_range_end'])
        free_ips = []
        for n in range(start, end+1):
            ip = int_to_ip(n)
            if ip not in used_ips:
                free_ips.append(ip + '/32')
            if len(free_ips) >= 50:  # حداکثر 50 تا نشون بده
                break
        return jsonify({'ips': free_ips, 'total_free': len(free_ips)})
    except Exception as e:
        return jsonify({'ips': [], 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)
