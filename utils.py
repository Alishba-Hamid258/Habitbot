import os
import json
import base64
import PyPDF2
import io
from datetime import datetime
import pandas as pd
from db import get_connection

def is_on_topic(prompt: str, history: list = None) -> bool:
    prompt_lower = prompt.lower()
    productivity_keywords = [
        "habit", "goal", "routine", "time", "focus", "distraction", "pomodoro",
        "task", "todo", "plan", "schedule", "procrastination", "motivation",
        "sleep", "diet", "exercise", "workout", "reading", "learn", "meditate", "journal"
    ]
    if any(kw in prompt_lower for kw in productivity_keywords):
        return True
    return False

# ================================
# CHAT HISTORY
# ================================
def save_history(user_id, messages):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    c.executemany("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", 
                  [(user_id, m["role"], m["content"]) for m in messages])
    conn.commit()
    conn.close()

def load_history(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def archive_current_chat(user_id, messages):
    if len(messages) <= 1: return
    conn = get_connection()
    c = conn.cursor()
    session_id = datetime.now().strftime("%Y%m%d%H%M%S")
    session_name = "Session"
    for m in messages:
        if m["role"] == "user":
            session_name = (m["content"][:30] + "...") if len(m["content"]) > 30 else m["content"]
            break
    for m in messages:
        c.execute("INSERT INTO chat_archives (user_id, session_id, session_name, role, content) VALUES (?, ?, ?, ?, ?)",
                  (user_id, session_id, session_name, m["role"], m["content"]))
    conn.commit()
    conn.close()

def get_chat_archives(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT session_id, session_name, timestamp FROM chat_archives WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_archived_messages(user_id, session_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_archives WHERE user_id = ? AND session_id = ? ORDER BY id ASC", (user_id, session_id))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

# ================================
# HABITS LOG & MATRIX
# ================================
def log_habit(user_id, habit, category="General"):
    conn = get_connection()
    c = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO habits_log (user_id, date, habit, category) VALUES (?, ?, ?, ?)", (user_id, date_str, habit, category))
    conn.commit()
    conn.close()

def unlog_habit(user_id, habit_text):
    conn = get_connection()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("DELETE FROM habits_log WHERE user_id = ? AND habit = ? AND date LIKE ?", (user_id, habit_text, f"{today}%"))
    rowcount = c.rowcount
    conn.commit()
    conn.close()
    return rowcount > 0

def get_todays_logged_habits(user_id):
    conn = get_connection()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT habit FROM habits_log WHERE user_id = ? AND date LIKE ?", (user_id, f"{today}%"))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_all_habits(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, date, habit, category FROM habits_log WHERE user_id = ? ORDER BY date DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "date": r[1], "habit": r[2], "category": r[3]} for r in rows]

def delete_habit(user_id, db_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM habits_log WHERE id = ? AND user_id = ?", (db_id, user_id))
    conn.commit()
    ret = c.rowcount > 0
    conn.close()
    return ret

def get_habit_context(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT date, habit FROM habits_log WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = c.fetchall()
    conn.close()
    if rows:
        return "\n".join([f"{row[0]}: {row[1]}" for row in rows[-10:]])
    return "No habits logged yet."

# ================================
# CORE HABITS
# ================================
def load_core_habits(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT habit_name FROM core_habits WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        defaults = ["💧 Drink Water", "🧘 Meditation", "📖 Reading"]
        save_core_habits(user_id, defaults)
        return defaults
    return [row[0] for row in rows]

def save_core_habits(user_id, habits):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM core_habits WHERE user_id = ?", (user_id,))
    c.executemany("INSERT INTO core_habits (user_id, habit_name) VALUES (?, ?)", [(user_id, h) for h in habits])
    conn.commit()
    conn.close()

# ================================
# TODOS
# ================================
def save_todos(user_id, todos):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM todos WHERE user_id = ?", (user_id,))
    c.executemany("INSERT INTO todos (user_id, task, priority, time, done) VALUES (?, ?, ?, ?, ?)", 
                  [(user_id, t.get("task", ""), t.get("priority", "Medium"), t.get("time", ""), int(t.get("done", False))) for t in todos])
    conn.commit()
    conn.close()

def load_todos(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT task, priority, time, done FROM todos WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"task": r[0], "priority": r[1], "time": r[2], "done": bool(r[3])} for r in rows]

# ================================
# REFLECTIONS
# ================================
def save_reflection(user_id, went_well, friction):
    conn = get_connection()
    c = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT id FROM reflections WHERE user_id = ? AND date = ?", (user_id, date_str))
    row = c.fetchone()
    if row:
        c.execute("UPDATE reflections SET went_well = ?, friction = ? WHERE user_id = ? AND date = ?", (went_well, friction, user_id, date_str))
    else:
        c.execute("INSERT INTO reflections (user_id, date, went_well, friction) VALUES (?, ?, ?, ?)", (user_id, date_str, went_well, friction))
    conn.commit()
    conn.close()

def load_reflections(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT date, went_well, friction FROM reflections WHERE user_id = ? ORDER BY date ASC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"date": r[0], "went_well": r[1], "friction": r[2]} for r in rows]

# ================================
# GAMIFICATION & STATS
# ================================
def get_current_streak(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT date FROM habits_log WHERE user_id = ? ORDER BY date DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows: return 0
    logged_dates = sorted(list(set([r[0].split(" ")[0] for r in rows])), reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    streak = 0
    current_check_date = today
    if today not in logged_dates and yesterday in logged_dates:
        current_check_date = yesterday
    if current_check_date not in logged_dates: return 0
    for i in range(len(logged_dates)):
        expected_date = (datetime.strptime(current_check_date, "%Y-%m-%d") - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        if logged_dates[i] == expected_date: streak += 1
        else: break
    return streak

def get_consistency_score(user_id):
    conn = get_connection()
    c = conn.cursor()
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=30)
    c.execute("SELECT date FROM habits_log WHERE user_id = ? AND date >= ?", (user_id, start_date.strftime('%Y-%m-%d')))
    rows = c.fetchall()
    conn.close()
    logged_days = set()
    for r in rows:
        try:
            d = pd.to_datetime(r[0].split(' ')[0])
            logged_days.add(d.strftime('%Y-%m-%d'))
        except: pass
    return int((len(logged_days) / 30.0) * 100)

def get_heatmap_data(user_id):
    conn = get_connection()
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=364)
    
    query = "SELECT date FROM habits_log WHERE user_id = ? AND date >= ?"
    df_logs = pd.read_sql_query(query, conn, params=(user_id, start_date.strftime('%Y-%m-%d')))
    conn.close()
    
    all_days = pd.date_range(start=start_date, end=end_date, freq='D').date
    full_range = pd.DataFrame({'date': all_days})

    if df_logs.empty:
        full_range['count'] = 0
        return full_range

    df_logs['date'] = pd.to_datetime(df_logs['date']).dt.date
    daily_counts = df_logs.groupby('date').size().reset_index(name='count')
    
    heatmap_df = pd.merge(full_range, daily_counts, on='date', how='left').fillna(0)
    return heatmap_df

def get_user_badges(user_id):
    badges = []
    streak = get_current_streak(user_id)
    if streak >= 3: badges.append("🔥 3-Day Starter")
    if streak >= 7: badges.append("⚔️ 7-Day Warrior")
    if streak >= 30: badges.append("👑 30-Day Legend")
    score = get_consistency_score(user_id)
    if score >= 80: badges.append("🎯 High Consistency")
    return badges

def get_habit_stats(user_id):
    conn = get_connection()
    df = pd.read_sql_query("SELECT date, habit, category FROM habits_log WHERE user_id = ?", conn, params=(user_id,))
    conn.close()
    if df.empty: return None, None, None
    df['date'] = pd.to_datetime(df['date'])
    df['day'] = df['date'].dt.date
    daily = df.groupby('day').size().reset_index(name='count')
    df['week'] = df['date'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly = df.groupby('week').size().reset_index(name='count')
    df['month'] = df['date'].dt.to_period('M').apply(lambda r: r.start_time)
    monthly = df.groupby('month').size().reset_index(name='count')
    return daily, weekly, monthly

def get_weekly_summary(user_id):
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=7)
    summary_lines = []
    summary_lines.append(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT habit FROM habits_log WHERE user_id = ? AND date >= ?", (user_id, start_date.strftime('%Y-%m-%d')))
    recent_habits = c.fetchall()
    habit_counts = {}
    for h in recent_habits:
        habit_counts[h[0]] = habit_counts.get(h[0], 0) + 1
    summary_lines.append("\n--- HABITS COMPLETED THIS WEEK ---")
    if habit_counts:
        for habit, count in habit_counts.items(): summary_lines.append(f"- {habit}: {count} times")
    else: summary_lines.append("No habits logged this week.")
    c.execute("SELECT task, priority, done FROM todos WHERE user_id = ?", (user_id,))
    todos = c.fetchall()
    done_todos = [t for t in todos if t[2]]
    pending_todos = [t for t in todos if not t[2]]
    summary_lines.append("\n--- CURRENT TO-DO LIST STATUS ---")
    summary_lines.append(f"Completed Tasks: {len(done_todos)}")
    summary_lines.append(f"Pending Tasks: {len(pending_todos)}")
    if pending_todos:
        summary_lines.append("Top Pending Tasks:")
        for t in pending_todos[:3]: summary_lines.append(f"- {t[0]} (Priority: {t[1]})")
    c.execute("SELECT SUM(duration_mins) FROM focus_sessions WHERE user_id = ? AND date >= ? AND mode LIKE '%Focus%'", (user_id, start_date.strftime('%Y-%m-%d')))
    total_focus = c.fetchone()[0] or 0
    summary_lines.append(f"\n--- DEEP WORK ---")
    summary_lines.append(f"Total Focus Time this week: {total_focus} minutes")
    c.execute("SELECT date, went_well, friction FROM reflections WHERE user_id = ? AND date >= ?", (user_id, start_date.strftime('%Y-%m-%d')))
    reflections = c.fetchall()
    conn.close()
    if reflections:
        summary_lines.append("\n--- END OF DAY REFLECTIONS ---")
        for r in reflections:
            summary_lines.append(f"Date: {r[0]}")
            summary_lines.append(f"  Went Well: {r[1]}")
            summary_lines.append(f"  Friction: {r[2]}")
    return "\n".join(summary_lines)

def log_focus_session(user_id, mode, duration_mins):
    conn = get_connection()
    c = conn.cursor()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO focus_sessions (user_id, date, mode, duration_mins) VALUES (?, ?, ?, ?)", (user_id, date_str, mode, duration_mins))
    conn.commit()
    conn.close()

def get_total_focus_time(user_id, period="today"):
    conn = get_connection()
    c = conn.cursor()
    if period == "today":
        target = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT SUM(duration_mins) FROM focus_sessions WHERE user_id = ? AND date LIKE ? AND mode LIKE '%Focus%'", (user_id, f"{target}%"))
    else:
        c.execute("SELECT SUM(duration_mins) FROM focus_sessions WHERE user_id = ? AND mode LIKE '%Focus%'", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row[0] else 0

def generate_life_audit(user_id):
    conn = get_connection()
    tables = {
        "Habits": "SELECT date, habit, category FROM habits_log WHERE user_id = ?",
        "Focus": "SELECT date, mode, duration_mins FROM focus_sessions WHERE user_id = ?",
        "Tasks": "SELECT task, priority, time, done FROM todos WHERE user_id = ?",
        "Reflections": "SELECT date, went_well, friction FROM reflections WHERE user_id = ?",
        "Chat History": "SELECT timestamp, session_name, role, content FROM chat_archives WHERE user_id = ?"
    }
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, query in tables.items():
            df = pd.read_sql_query(query, conn, params=(user_id,))
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    conn.close()
    return output.getvalue()

# ================================
# FILE PROCESSING (VISION & DOCS)
# ================================
def encode_image(image_file):
    image_file.seek(0)
    return base64.b64encode(image_file.read()).decode("utf-8")

def extract_text_from_pdf(pdf_file):
    try:
        pdf_file.seek(0)
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error parsing PDF: {e}"

def process_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return None
    file_name = uploaded_file.name.lower()
    if file_name.endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return {"type": "image", "data": encode_image(uploaded_file)}
    elif file_name.endswith('.pdf'):
        return {"type": "text", "data": extract_text_from_pdf(uploaded_file)}
    elif file_name.endswith(('.txt', '.md', '.csv')):
        uploaded_file.seek(0)
        return {"type": "text", "data": uploaded_file.read().decode("utf-8")}
    else:
        return None

# ================================
# NOTIFICATIONS & ALERTS
# ================================
def get_notification_js(title, body):
    safe_body = body.replace('"', '\\"')
    return f"""<div style="display:none;"><script>if (Notification.permission === "granted") {{ new Notification("{title}", {{ body: "{safe_body}", icon: "https://cdn-icons-png.flaticon.com/512/190/190411.png" }}); }}</script></div>"""

def get_permission_js():
    return """<div style="display:none;"><script>if (Notification.permission !== "granted" && Notification.permission !== "denied") {{ Notification.requestPermission(); }}</script></div>"""

def get_chime_html():
    chime_url = "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"
    return f"""<div style="display:none;"><audio autoplay><source src="{chime_url}" type="audio/ogg"></audio></div>"""