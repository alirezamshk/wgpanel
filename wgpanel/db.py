import sqlite3
import os
from datetime import datetime

DB_PATH = '/wgpanel/data/wgpanel.db'

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS peers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mt_id           TEXT UNIQUE,
            public_key      TEXT UNIQUE NOT NULL,
            private_key     TEXT,
            interface       TEXT NOT NULL,
            allowed_address TEXT,
            comment         TEXT DEFAULT '',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

            -- quota & expiry
            quota_bytes     INTEGER DEFAULT 0,    -- 0 = unlimited
            expiry_date     DATE,                 -- NULL = no expiry
            disabled        INTEGER DEFAULT 0,

            -- cumulative traffic (updated by scheduler)
            total_tx        INTEGER DEFAULT 0,
            total_rx        INTEGER DEFAULT 0,
            last_tx         INTEGER DEFAULT 0,    -- last raw value from MT
            last_rx         INTEGER DEFAULT 0,
            last_seen       DATETIME
        );

        CREATE TABLE IF NOT EXISTS traffic_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            peer_id     INTEGER NOT NULL REFERENCES peers(id),
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            tx_delta    INTEGER DEFAULT 0,
            rx_delta    INTEGER DEFAULT 0,
            total_tx    INTEGER DEFAULT 0,
            total_rx    INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_traffic_peer ON traffic_log(peer_id, recorded_at);
        ''')

# ── Peer CRUD ──────────────────────────────────────────────────
def upsert_peer(mt_id, public_key, private_key, interface, allowed_address, comment='', quota_bytes=0, expiry_date=None):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO peers (mt_id, public_key, private_key, interface, allowed_address, comment, quota_bytes, expiry_date)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(public_key) DO UPDATE SET
                mt_id=excluded.mt_id,
                interface=excluded.interface,
                allowed_address=excluded.allowed_address,
                comment=excluded.comment
        ''', (mt_id, public_key, private_key, interface, allowed_address, comment, quota_bytes, expiry_date))

def get_all_peers():
    with get_db() as conn:
        return conn.execute('SELECT * FROM peers ORDER BY created_at DESC').fetchall()

def get_peer_by_pubkey(public_key):
    with get_db() as conn:
        return conn.execute('SELECT * FROM peers WHERE public_key=?', (public_key,)).fetchone()

def get_peer_by_id(peer_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM peers WHERE id=?', (peer_id,)).fetchone()

def update_peer_settings(peer_id, comment, quota_bytes, expiry_date):
    with get_db() as conn:
        conn.execute('''
            UPDATE peers SET comment=?, quota_bytes=?, expiry_date=?
            WHERE id=?
        ''', (comment, quota_bytes, expiry_date, peer_id))

def delete_peer_db(peer_id):
    with get_db() as conn:
        conn.execute('DELETE FROM traffic_log WHERE peer_id=?', (peer_id,))
        conn.execute('DELETE FROM peers WHERE id=?', (peer_id,))

def update_traffic(public_key, raw_tx, raw_rx, mt_id=None, last_handshake=None):
    """Called by scheduler. Calculates delta and accumulates."""
    with get_db() as conn:
        peer = conn.execute('SELECT * FROM peers WHERE public_key=?', (public_key,)).fetchone()
        if not peer:
            return

        last_tx = peer['last_tx'] or 0
        last_rx = peer['last_rx'] or 0

        # MikroTik counters reset on reboot/peer-reset — handle wrap
        tx_delta = raw_tx - last_tx if raw_tx >= last_tx else raw_tx
        rx_delta = raw_rx - last_rx if raw_rx >= last_rx else raw_rx

        new_total_tx = (peer['total_tx'] or 0) + tx_delta
        new_total_rx = (peer['total_rx'] or 0) + rx_delta

        conn.execute('''
            UPDATE peers SET
                last_tx=?, last_rx=?,
                total_tx=?, total_rx=?,
                last_seen=CURRENT_TIMESTAMP,
                mt_id=COALESCE(?, mt_id)
            WHERE public_key=?
        ''', (raw_tx, raw_rx, new_total_tx, new_total_rx, mt_id, public_key))

        if tx_delta > 0 or rx_delta > 0:
            conn.execute('''
                INSERT INTO traffic_log (peer_id, tx_delta, rx_delta, total_tx, total_rx)
                VALUES (?,?,?,?,?)
            ''', (peer['id'], tx_delta, rx_delta, new_total_tx, new_total_rx))

def get_traffic_history(peer_id, limit=48):
    with get_db() as conn:
        return conn.execute('''
            SELECT recorded_at, tx_delta, rx_delta, total_tx, total_rx
            FROM traffic_log WHERE peer_id=?
            ORDER BY recorded_at DESC LIMIT ?
        ''', (peer_id, limit)).fetchall()

def get_expired_peers():
    with get_db() as conn:
        return conn.execute('''
            SELECT * FROM peers
            WHERE expiry_date IS NOT NULL AND expiry_date < date('now') AND disabled=0
        ''').fetchall()

def get_over_quota_peers():
    with get_db() as conn:
        return conn.execute('''
            SELECT * FROM peers
            WHERE quota_bytes > 0 AND (total_tx + total_rx) >= quota_bytes AND disabled=0
        ''').fetchall()

def set_peer_disabled(peer_id, disabled: bool):
    with get_db() as conn:
        conn.execute('UPDATE peers SET disabled=? WHERE id=?', (1 if disabled else 0, peer_id))
