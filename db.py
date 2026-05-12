import sqlite3
import os

import streamlit as st

DB_NAME = ".streamlit/habitbot.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Users Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. Chat History (Active)
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # 2b. Chat Archives (Old sessions)
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT,
            session_name TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # 3. Core Habits
    c.execute('''
        CREATE TABLE IF NOT EXISTS core_habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            habit_name TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # 4. Habits Log
    c.execute('''
        CREATE TABLE IF NOT EXISTS habits_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            habit TEXT,
            category TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # 5. To-Dos
    c.execute('''
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task TEXT,
            priority TEXT,
            time TEXT,
            done INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # 6. Reflections
    c.execute('''
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            went_well TEXT,
            friction TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )
    ''')
    
    # 7. Focus Sessions
    c.execute('''
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            mode TEXT,
            duration_mins INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # SCHEMA MIGRATION: Add user_id column if it doesn't exist
    tables = ["chat_history", "core_habits", "habits_log", "todos", "reflections", "focus_sessions"]
    for table in tables:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            # Column already exists
            pass
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
