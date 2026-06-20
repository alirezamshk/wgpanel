import hashlib, os

def hash_password(password):
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"

def verify_password(password, stored):
    try:
        salt, h = stored.split(':', 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == h
    except:
        return False
