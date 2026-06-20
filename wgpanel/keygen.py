import subprocess
import db
import mikrotik

def regenerate_keypair(peer_id):
    """یه keypair جدید میسازه و public key رو روی MikroTik آپدیت میکنه"""
    peer = db.get_peer_by_id(peer_id)
    if not peer:
        return None, None

    priv = subprocess.check_output(['wg', 'genkey']).decode().strip()
    pub  = subprocess.check_output(['wg', 'pubkey'], input=priv.encode()).decode().strip()

    # آپدیت روی MikroTik
    if peer['mt_id']:
        mikrotik.update_peer(peer['mt_id'], **{'public-key': pub})

    # آپدیت توی DB
    with db.get_db() as conn:
        conn.execute('''
            UPDATE peers SET private_key=?, public_key=?, mt_id=?
            WHERE id=?
        ''', (priv, pub, peer['mt_id'], peer_id))

    return pub, priv
