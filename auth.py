import bcrypt
from db import get_connection

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_user(username, password):
    if not username:
        return None
    username = username.strip().lower()
    conn = get_connection()
    c = conn.cursor()
    password_hash = hash_password(password)
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        user_id = c.lastrowid
        ret = user_id
    except Exception:
        ret = None
    conn.close()
    return ret

def verify_user(username, password):
    if not username:
        return None
    username = username.strip().lower()
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row and check_password(password, row[1]):
        return row[0]
    return None

