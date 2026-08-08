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

import secrets

def create_session(user_id):
    """Generate a secure session token for user_id and store it in user_sessions."""
    session_token = secrets.token_hex(32)
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)", (user_id, session_token))
        conn.commit()
        ret = session_token
    except Exception:
        ret = None
    conn.close()
    return ret

def verify_session(session_token):
    """Verify session token and return user_id, or None if invalid."""
    if not session_token:
        return None
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_sessions WHERE session_token = ?", (session_token,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def destroy_session(session_token):
    """Delete session token from user_sessions."""
    if not session_token:
        return
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_sessions WHERE session_token = ?", (session_token,))
    conn.commit()
    conn.close()


