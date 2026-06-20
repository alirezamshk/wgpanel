import threading
import time
import logging
from datetime import datetime

import db
import mikrotik
from config import COLLECT_INTERVAL

log = logging.getLogger('scheduler')

def collect_traffic():
    try:
        peers = mikrotik.get_peers_traffic()
        for p in peers:
            db.update_traffic(
                public_key=p['public_key'],
                raw_tx=p['tx'],
                raw_rx=p['rx'],
                mt_id=p['mt_id'],
                last_handshake=p['last_handshake']
            )
        log.info(f"[{datetime.now().strftime('%H:%M:%S')}] Collected traffic for {len(peers)} peers")
    except Exception as e:
        log.error(f"Traffic collection error: {e}")

def enforce_policies():
    """Disable expired or over-quota peers on MikroTik."""
    try:
        # Expired
        for peer in db.get_expired_peers():
            if peer['mt_id']:
                try:
                    mikrotik.disable_peer(peer['mt_id'])
                    db.set_peer_disabled(peer['id'], True)
                    log.info(f"Disabled expired peer: {peer['comment'] or peer['public_key'][:16]}")
                except Exception as e:
                    log.error(f"Failed to disable expired peer {peer['id']}: {e}")

        # Over quota
        for peer in db.get_over_quota_peers():
            if peer['mt_id']:
                try:
                    mikrotik.disable_peer(peer['mt_id'])
                    db.set_peer_disabled(peer['id'], True)
                    log.info(f"Disabled over-quota peer: {peer['comment'] or peer['public_key'][:16]}")
                except Exception as e:
                    log.error(f"Failed to disable over-quota peer {peer['id']}: {e}")
    except Exception as e:
        log.error(f"Policy enforcement error: {e}")

def run_scheduler():
    log.info(f"Scheduler started. Interval: {COLLECT_INTERVAL}s")
    while True:
        collect_traffic()
        enforce_policies()
        time.sleep(COLLECT_INTERVAL)

def start():
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
