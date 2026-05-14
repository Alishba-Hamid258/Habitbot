import streamlit as st
import json
import re
import logging
import pandas as pd
import plotly.express as px
import extra_streamlit_components as stx
from datetime import datetime
from api import call_llm
from config import SYSTEM_PROMPT, ARCHITECT_PROMPT
from utils import (
    is_on_topic, save_history, load_history, log_habit, get_habit_context, delete_habit, save_todos, load_todos, get_habit_stats,
    get_current_streak, load_core_habits, save_core_habits, get_todays_logged_habits, unlog_habit,
    get_weekly_summary, get_consistency_score, get_user_badges,
    save_reflection, load_reflections, get_all_habits,
    process_uploaded_file, get_notification_js, get_permission_js,
    log_focus_session, get_total_focus_time, get_heatmap_data, generate_life_audit,
    archive_current_chat, get_chat_archives, get_archived_messages, delete_chat_archive,
    get_chime_html, get_ticking_html, get_prime_audio_js
)

def extract_json_from_text(text):
    """Robustly extract a JSON list from LLM output that may contain markdown fences or extra text."""
    text = text.strip()
    # 1. Direct parse
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else [result]
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. Extract from markdown code fences
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1).strip())
            return result if isinstance(result, list) else [result]
        except (json.JSONDecodeError, ValueError):
            pass
    # 3. Find first [...] block
    bracket_match = re.search(r'\[.*\]', text, re.DOTALL)
    if bracket_match:
        try:
            result = json.loads(bracket_match.group(0))
            return result if isinstance(result, list) else [result]
        except (json.JSONDecodeError, ValueError):
            pass
    # 4. Nothing worked
    raise ValueError("Could not extract valid JSON from AI response")

# Cached wrappers defined here to avoid cross-file import issues on Streamlit Cloud
@st.cache_data(ttl=300)
def _cached_heatmap_data(user_id):
    return get_heatmap_data(user_id)

@st.cache_data(ttl=60)
def _cached_habit_stats(user_id):
    return get_habit_stats(user_id)
from auth import create_user, verify_user
from db import init_db, DB_NAME

# Page Config (First Streamlit call)
st.set_page_config(page_title="HabitBot | Your Personal Coach", layout="wide", page_icon="🤖", initial_sidebar_state="expanded")

# Initialize database tables on startup
init_db()

# (PWA CSS moved to bottom)

# (Cookie manager moved to bottom for safety)

# SESSION STATE INIT (ALL DEFAULTS AT THE TOP)
if "user_id" not in st.session_state: st.session_state.user_id = None
if "logout_triggered" not in st.session_state: st.session_state.logout_triggered = False
if "sync_attempts" not in st.session_state: st.session_state.sync_attempts = 0
if "current_page" not in st.session_state: st.session_state.current_page = "💬 Habit Coach"
if "last_input" not in st.session_state: st.session_state.last_input = ""
if "timer_mode" not in st.session_state: st.session_state.timer_mode = "🍅 Focus"
if "timer_active" not in st.session_state: st.session_state.timer_active = False
if "timer_seconds" not in st.session_state: st.session_state.timer_seconds = 1500
if "timer_max_seconds" not in st.session_state: st.session_state.timer_max_seconds = 1500
if "lib_custom_url" not in st.session_state: st.session_state.lib_custom_url = ""

# PERSISTENT LOGIN RECOVERY (Simplified)
if st.session_state.user_id is None and not st.session_state.logout_triggered:
    if "uid" in st.query_params:
        try: st.session_state.user_id = int(st.query_params["uid"])
        except: pass

# GLOBAL SETUP
st.markdown(get_permission_js(), unsafe_allow_html=True)
st.markdown(get_prime_audio_js(), unsafe_allow_html=True)

# CALLBACKS (Shared between Sidebar and Main App)
def get_callbacks(user_id):
    return {
        "delete_habit": lambda idx: delete_habit(user_id, idx),
        "toggle_freeze": lambda: (unlog_habit(user_id, "❄️ Freeze Day") if "❄️ Freeze Day" in get_todays_logged_habits(user_id) else log_habit(user_id, "❄️ Freeze Day", "System")),
        "add_core": lambda: (save_core_habits(user_id, load_core_habits(user_id) + [st.session_state.new_core_habit_in.strip()]) if st.session_state.new_core_habit_in.strip() and st.session_state.new_core_habit_in.strip() not in load_core_habits(user_id) else None),
        "delete_core": lambda idx: (save_core_habits(user_id, [h for i, h in enumerate(load_core_habits(user_id)) if i != idx])),
        "toggle_daily": lambda h: (unlog_habit(user_id, h) if h in get_todays_logged_habits(user_id) else log_habit(user_id, h, "Daily Matrix"))
    }

# PERSISTENT LOGIN RECOVERY (One-time check, no reruns here to avoid loops)
if st.session_state.user_id is None and not st.session_state.logout_triggered:
    if "uid" in st.query_params:
        try: st.session_state.user_id = int(st.query_params["uid"])
        except: pass

# GLOBAL COMPONENTS
cookie_manager = stx.CookieManager(key="habitbot_cookie_manager")

# HELPER FOR HEATMAP
def show_consistency_heatmap(user_id):
    df = _cached_heatmap_data(user_id)
    if df.empty:
        st.write("No data available for heatmap.")
        return
    df['date'] = pd.to_datetime(df['date'])
    df['week_of_year'] = df['date'].dt.isocalendar().week
    df['year'] = df['date'].dt.year
    df['day_of_week'] = df['date'].dt.day_name()
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    df['week_id'] = df['year'].astype(str) + "-W" + df['week_of_year'].astype(str).str.zfill(2)
    pivot = df.pivot(index='day_of_week', columns='week_id', values='count').reindex(day_order)
    display_cols = [c.split("-W")[-1] for c in pivot.columns]
    fig = px.imshow(pivot, labels=dict(x="Weeks", y="Day", color="Habits"), x=display_cols, y=pivot.index, color_continuous_scale="Blues", template="plotly_dark")
    fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=10), coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

# SIDEBAR (Status & Tools)
with st.sidebar:
    st.title("🤖 HabitBot")
    
    if st.session_state.user_id:
        uid = st.session_state.user_id
        cb = get_callbacks(uid)
        
        # Profile & Logout
        with st.container(border=True):
            c1, c2 = st.columns([0.3, 0.7])
            c1.markdown("### 👤")
            c2.markdown(f"**User: {uid}**")
            if st.button("Logout", use_container_width=True):
                st.session_state.user_id = None
                st.session_state.logout_triggered = True
                try: 
                    cookie_manager.set("habitbot_v4_uid", "None") # Explicitly invalidate
                    cookie_manager.delete("habitbot_v4_uid")
                except: pass
                st.query_params.clear()
                st.rerun()

        st.markdown("---")
        
        # Stats
        st.markdown("### 🔥 Mastery")
        c1, c2 = st.columns(2)
        c1.metric("Streak", f"{get_current_streak(uid)}d")
        c2.metric("Discipline", f"{get_consistency_score(uid)}%")

        # Pomodoro Timer (Fragmented for real-time updates)
        st.markdown("---")
        st.markdown("### ⏲️ Pomodoro")
        
        # Audio Settings
        with st.expander("🔊 Audio Settings"):
            if st.button("🔔 Test Chime", use_container_width=True):
                st.markdown(get_chime_html(), unsafe_allow_html=True)
                st.toast("Chime triggered!", icon="🎵")
        # Mode Selection
        m_cols = st.columns(3)
        if m_cols[0].button("🎯", help="Focus (25m)"): 
            st.session_state.timer_seconds = 1500
            st.session_state.timer_max_seconds = 1500
            st.session_state.timer_active = False
            st.rerun()
        if m_cols[1].button("☕", help="Short Break (5m)"): 
            st.session_state.timer_seconds = 300
            st.session_state.timer_max_seconds = 300
            st.session_state.timer_active = False
            st.rerun()
        if m_cols[2].button("🧘", help="Long Break (15m)"): 
            st.session_state.timer_seconds = 900
            st.session_state.timer_max_seconds = 900
            st.session_state.timer_active = False
            st.rerun()

        # Custom Adjustment
        adj_mins = st.number_input("Minutes", value=max(1, st.session_state.timer_seconds // 60), min_value=1, max_value=120, step=1, key="sb_adj_mins")
        if adj_mins * 60 != st.session_state.timer_seconds and not st.session_state.timer_active:
            st.session_state.timer_seconds = adj_mins * 60
            st.session_state.timer_max_seconds = adj_mins * 60

        # Fragment for Countdown
        @st.fragment(run_every="1s")
        def timer_fragment():
            if st.session_state.timer_active and st.session_state.timer_seconds > 0:
                st.session_state.timer_seconds -= 1
                if st.session_state.timer_seconds == 0:
                    st.session_state.timer_active = False
                    st.toast("⏰ Time's up!", icon="🔔")
                    st.markdown(get_chime_html(), unsafe_allow_html=True)

            mins, secs = divmod(st.session_state.timer_seconds, 60)
            st.markdown(f"<h1 style='text-align: center; color: #FF4B4B;'>{mins:02d}:{secs:02d}</h1>", unsafe_allow_html=True)
            st.progress(max(0, min(1.0, st.session_state.timer_seconds / st.session_state.timer_max_seconds)))
            
            if st.session_state.timer_active:
                if st.button("⏹ Pause Timer", use_container_width=True, key="sb_pause"): 
                    st.session_state.timer_active = False
                    st.rerun()
            else:
                if st.button("🚀 Start Timer", use_container_width=True, key="sb_start"): 
                    st.markdown("<script>window.primeAudio();</script>", unsafe_allow_html=True)
                    st.session_state.timer_active = True
                    st.rerun()
        
        timer_fragment()

        # (Ticking sound removed per user request)

        # Daily Matrix
        st.markdown("---")
        st.markdown("### 🛡️ Daily Matrix")
        core = load_core_habits(uid)
        logged = get_todays_logged_habits(uid)
        st.button("☀️ Unfreeze" if "❄️ Freeze Day" in logged else "❄️ Freeze", on_click=cb["toggle_freeze"], use_container_width=True, key="sb_freeze_btn")
        for h in core:
            st.checkbox(h, value=h in logged, key=f"sb_chk_{h}", on_change=cb["toggle_daily"], args=(h,))
    else:
        st.info("👋 Welcome! Please log in.")
# (End of setup)

# ==========================================
# AUTHENTICATION SCREEN
# ==========================================
if st.session_state.user_id is None:
    # --- COOKIE RECOVERY ATTEMPT ---
    if not st.session_state.logout_triggered:
        try:
            cookie_val = cookie_manager.get("habitbot_v4_uid")
            if cookie_val and cookie_val not in ["None", "null", "", "undefined"]:
                st.session_state.user_id = int(cookie_val)
                st.rerun()
        except: pass

    # Always show the login form if user_id is missing
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🤖 HabitBot v4.0")
        st.markdown("### Secure Login & Privacy")
        
        tab_login, tab_signup = st.tabs(["🔐 Login", "📝 Sign Up"])
        
        with tab_login:
            u = st.text_input("Username", key="l_u")
            p = st.text_input("Password", type="password", key="l_p")
            if st.button("Login", use_container_width=True):
                uid = verify_user(u, p)
                if uid:
                    st.session_state.user_id = uid
                    st.session_state.logout_triggered = False # Reset flag
                    # Save to cookie for 30 days
                    import datetime as dt
                    expiry = dt.datetime.now() + dt.timedelta(days=30)
                    cookie_manager.set("habitbot_v4_uid", str(uid), expires_at=expiry)
                    st.query_params["uid"] = str(uid) # Add to URL for instant recovery on refresh
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        
        with tab_signup:
            st.info("Start your journey to mastery today.")
            new_u = st.text_input("Choose Username", key="s_u")
            new_p = st.text_input("Choose Password", type="password", key="s_p")
            confirm_p = st.text_input("Confirm Password", type="password", key="s_pc")
            if st.button("Create Account", use_container_width=True):
                if new_p != confirm_p:
                    st.error("Passwords do not match!")
                elif len(new_p) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    uid = create_user(new_u, new_p)
                    if uid:
                        st.session_state.user_id = uid
                        st.session_state.logout_triggered = False
                        # Save to cookie for 30 days
                        import datetime as dt
                        expiry = dt.datetime.now() + dt.timedelta(days=30)
                        cookie_manager.set("habitbot_v4_uid", str(uid), expires_at=expiry)
                        st.query_params["uid"] = str(uid)
                        st.success("Account created! Welcome to HabitBot.")
                        st.rerun()
                    else:
                        st.error("Username already taken.")
    st.stop()

# ==========================================
# MAIN APP (AUTHENTICATED)
uid = st.session_state.user_id

# Top Navigation (Tabs style)
pages_map = {
    "💬 Coach": "💬 Habit Coach", 
    "📊 Analytics": "📊 Analytics", 
    "✅ Tasks": "✅ To-Do List", 
    "📓 Logbook": "📓 Logbook", 
    "📚 Library": "📚 Library"
}

# Header bar with Nav and Stats
with st.container():
    cols = st.columns([0.6, 0.4])
    with cols[0]:
        choice = st.segmented_control(
            "Navigation", 
            options=list(pages_map.keys()), 
            default=next(k for k, v in pages_map.items() if v == st.session_state.current_page),
            label_visibility="collapsed",
            key="top_nav_bar"
        )
        if choice:
            st.session_state.current_page = pages_map[choice]
    
    with cols[1]:
        st.markdown(f"<p style='text-align:right; margin:0;'>🔥 {get_current_streak(uid)}d | 🎯 {get_consistency_score(uid)}%</p>", unsafe_allow_html=True)

st.markdown("---")

# PAGE DISPATCHER
page = st.session_state.current_page
if "messages" not in st.session_state:
    saved = load_history(uid)
    st.session_state.messages = saved if saved else [{"role": "system", "content": SYSTEM_PROMPT}]

if page == "💬 Habit Coach":
    if "view_archive" not in st.session_state: st.session_state.view_archive = None

    if st.session_state.view_archive:
        col_back, col_title = st.columns([0.3, 0.7])
        if col_back.button("⬅️ Back to Active Chat", use_container_width=True):
            st.session_state.view_archive = None
            st.rerun()
        col_title.markdown("### 📜 Archived Session")
        for m in st.session_state.view_archive[1:]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        st.stop()

    col1, col2 = st.columns([0.7, 0.3])
    col1.markdown("### 💬 Habit Coach")
    if col2.button("➕ New Chat", use_container_width=True):
        archive_current_chat(uid, st.session_state.messages)
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_history(uid, st.session_state.messages)
        st.rerun()

    with st.expander("📜 Previous Sessions Archive"):
        archives = get_chat_archives(uid)
        if archives:
            for sid, name, ts in archives:
                arch_col, del_col = st.columns([0.85, 0.15])
                if arch_col.button(f"📄 {ts} | {name}", key=f"arch_{sid}", use_container_width=True):
                    st.session_state.view_archive = get_archived_messages(uid, sid)
                    st.rerun()
                if del_col.button("🗑️", key=f"del_{sid}"):
                    delete_chat_archive(uid, sid)
                    st.rerun()
        else: st.write("No archived sessions yet.")
    
    st.markdown("---")
    for m in st.session_state.messages[1:]:
        avatar = "🤖" if m["role"] == "assistant" else "👤"
        with st.chat_message(m["role"], avatar=avatar):
            from utils import _safe_content
            content = _safe_content(m.get("content", ""))
            if "[FILE ATTACHMENT]:" in content:
                main_text, attachment = content.split("[FILE ATTACHMENT]:", 1)
                st.markdown(main_text.strip())
                with st.expander("📄 View Attached"): st.text(attachment.strip())
            else: st.markdown(content)

    uploaded_file = st.file_uploader("Attach context", type=["png", "jpg", "jpeg", "webp", "pdf", "txt", "md"])
    if prompt := st.chat_input("Ask about habits…"):
        if prompt != st.session_state.last_input:
            st.session_state.last_input = prompt
            file_payload = process_uploaded_file(uploaded_file)
            image_data = None
            final_prompt = prompt
            if file_payload:
                if file_payload["type"] == "image": image_data = file_payload["data"]
                else: final_prompt = f"{prompt}\n\n[FILE ATTACHMENT]:\n{file_payload['data']}"
            with st.chat_message("user", avatar="👤"): st.markdown(prompt)
            if not is_on_topic(prompt, st.session_state.messages):
                refusal = "I specialized in habits and productivity."
                with st.chat_message("assistant", avatar="🤖"): st.markdown(refusal)
                st.session_state.messages.append({"role": "assistant", "content": refusal})
            else:
                st.session_state.messages.append({"role": "user", "content": final_prompt})
                habit_summary = get_habit_context(uid)
                dynamic_messages = st.session_state.messages.copy()
                dynamic_messages[0] = {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nPROGRESS:\n{habit_summary}"}
                with st.chat_message("assistant", avatar="🤖"):
                    llm_response = call_llm(dynamic_messages, stream=True, image_data=image_data)
                    reply = st.write_stream(llm_response) if not isinstance(llm_response, str) else st.markdown(llm_response) or llm_response
                st.session_state.messages.append({"role": "assistant", "content": reply})
                save_history(uid, st.session_state.messages)
                st.rerun()

# PAGE: ANALYTICS
elif page == "📊 Analytics":
    st.subheader("Performance Analytics")
    
    # HEATMAP AT THE TOP
    st.markdown("### Consistency Heatmap")
    show_consistency_heatmap(uid)
    
    # WEEKLY AI REPORT
    st.markdown("---")
    st.markdown("### ✨ AI Weekly Mastery Report")
    if st.button("Generate Performance Audit"):
        with st.spinner("Analyzing your discipline..."):
            summary = get_weekly_summary(uid)
            msg = [
                {"role": "system", "content": "You are the Mastery Coach. Analyze the user's weekly performance and provide a high-agency, motivating audit. Highlight wins and identify points of friction."},
                {"role": "user", "content": f"Here is my data for the last 7 days:\n{summary}"}
            ]
            report = call_llm(msg)
            st.markdown(report)
    st.markdown("---")

    daily, weekly, monthly = _cached_habit_stats(uid)
    total_focus = get_total_focus_time(uid, "today")
    st.info(f"🧠 **Deep Work Today**: {total_focus} minutes logged")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Current Streak", f"{get_current_streak(uid)} Days")
    col2.metric("Consistency Score", f"{get_consistency_score(uid)}%")
    badges = get_user_badges(uid)
    with col3:
        st.markdown("**Earned Badges**")
        st.markdown(" ".join([f"`{b}`" for b in badges]))

    if daily is not None:
        sub_tab_day, sub_tab_week, sub_tab_month = st.tabs(["📅 Daily", "📅 Weekly", "📅 Monthly"])
        with sub_tab_day: st.bar_chart(daily.set_index('day'))
        with sub_tab_week: st.bar_chart(weekly.set_index('week'))
        with sub_tab_month: st.bar_chart(monthly.set_index('month'))

# PAGE: TO-DO
elif page == "✅ To-Do List":
    st.subheader("AI Task Architect")
    todos = load_todos(uid)
    
    ai_prompt = st.text_area("💡 Describe your goals or what you want to accomplish:", 
                              placeholder="e.g. I want to prepare for my exams, exercise daily, and read more books this week...",
                              key="ai_task_prompt")
    
    if st.button("✨ Generate AI Tasks"):
        if not ai_prompt.strip():
            st.warning("Please describe your goals first so the AI can generate relevant tasks.")
        else:
            with st.spinner("Analyzing your goals..."):
                history = get_weekly_summary(uid)
                msg = [
                    {"role": "system", "content": ARCHITECT_PROMPT}, 
                    {"role": "user", "content": f"My goals: {ai_prompt}\n\nMy weekly progress so far:\n{history}"}
                ]
                ai_tasks_json = call_llm(msg)
                try:
                    new_tasks = extract_json_from_text(ai_tasks_json)
                    # Normalize AI tasks to always have all required keys
                    for task in new_tasks:
                        task.setdefault("done", False)
                        task.setdefault("task", "Untitled Task")
                        task.setdefault("priority", "Medium")
                        task.setdefault("time", "")
                    todos.extend(new_tasks)
                    save_todos(uid, todos)
                    st.rerun()
                except Exception as e:
                    st.error(f"AI returned invalid task format: {e}")
                    with st.expander("🔍 Debug: Raw AI Response"):
                        st.code(ai_tasks_json)

    # Manual Add
    with st.expander("➕ Add Task Manually"):
        col1, col2, col3 = st.columns([0.5, 0.2, 0.3])
        t_text = col1.text_input("Task", key="new_todo_text")
        t_pri = col2.selectbox("Priority", ["Low", "Medium", "High"])
        t_time = col3.text_input("Time (e.g. 10am)")
        if st.button("Add Task"):
            todos.append({"task": t_text, "priority": t_pri, "time": t_time, "done": False})
            save_todos(uid, todos)
            st.rerun()

    st.markdown("---")
    for i, t in enumerate(todos):
        c1, c2, c3, c4 = st.columns([0.1, 0.6, 0.2, 0.1])
        t_done = t.get("done", False)
        t_task = t.get("task", "Untitled Task")
        t_pri = t.get("priority", "Medium")
        t_time = t.get("time", "")
        done = c1.checkbox("Done", value=t_done, key=f"todo_{i}", label_visibility="collapsed")
        if done != t_done:
            todos[i]["done"] = done
            save_todos(uid, todos)
            st.rerun()
        c2.markdown(f"**{t_task}**" if not t_done else f"~~{t_task}~~")
        c3.caption(f"{t_pri} | {t_time}")
        if c4.button("🗑️", key=f"del_todo_{i}"):
            todos.pop(i)
            save_todos(uid, todos)
            st.rerun()

# PAGE: LOGBOOK
elif page == "📓 Logbook":
    st.subheader("The Vault")
    
    with st.expander("🌙 Evening Reflection"):
        w_well = st.text_area("What went well today?")
        friction = st.text_area("What was a point of friction?")
        if st.button("Save Reflection"):
            save_reflection(uid, w_well, friction)
            st.success("Reflected! See you tomorrow.")

    st.markdown("---")
    st.markdown("### 💾 Data Safety & Backups")
    st.caption("Since HabitBot is currently in a cloud environment, local data can be reset during server updates. Protect your progress by exporting regularly.")
    
    audit_col, db_col = st.columns(2)
    with audit_col:
        st.markdown("#### 📊 Life Audit")
        st.write("Export your habits and reflections to an Excel file.")
        if st.button("Prepare Audit File", use_container_width=True):
            with st.spinner("Compiling your legendary journey..."):
                audit_data = generate_life_audit(uid)
                st.download_button(
                    label="📥 Download Life Audit (.xlsx)",
                    data=audit_data,
                    file_name=f"HabitBot_Life_Audit_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
    
    with db_col:
        st.markdown("#### 🗄️ Raw Database")
        st.write("Download the raw SQLite database for advanced backup.")
        try:
            with open(DB_NAME, "rb") as f:
                st.download_button(
                    label="📥 Download Database (.db)",
                    data=f,
                    file_name=f"habitbot_backup_{datetime.now().strftime('%Y-%m-%d')}.db",
                    mime="application/x-sqlite3",
                    use_container_width=True
                )
        except Exception as e:
            st.error("Could not prepare database backup.")

# PAGE: LIBRARY
elif page == "📚 Library":
    st.subheader("📚 Mastery Library")
    st.caption("Curated resources to sharpen your habits and mindset.")

    lib_tab1, lib_tab2, lib_tab3 = st.tabs(["📖 Essential Books", "🎥 Mastery Theater", "🎬 Custom Player"])

    with lib_tab1:
        st.markdown("### 📖 The Habit Blueprint")
        books = [
            {"title": "The Power of Habit", "author": "Charles Duhigg", "desc": "Why we do what we do in life and business.", "link": "https://dn710109.ca.archive.org/0/items/the-power-of-habit-charles-duhigg/The%20Power%20of%20Habit%20-%20Charles%20Duhigg.pdf", "icon": "🔄"},
            {"title": "Think and Grow Rich", "author": "Napoleon Hill", "desc": "The classic guide to success and wealth.", "link": "https://pdf.infobooks.org//ING/Autores/Napoleon%20Hill/think-and-grow-rich-napoleon-hill.pdf", "icon": "💰"},
            {"title": "As a Man Thinketh", "author": "James Allen", "desc": "How your thoughts shape your reality.", "link": "https://pdf.infobooks.org/ING/PDF/as-a-man-thinketh-james-allen.pdf", "icon": "🧠"},
            {"title": "The Science of Getting Rich", "author": "Wallace D. Wattles", "desc": "The mental science behind prosperity.", "link": "https://pdf.infobooks.org/ING/PDF/the-science-of-getting-rich.pdf", "icon": "📈"},
            {"title": "The Power of Concentration", "author": "Theron Q. Dumont", "desc": "Exercises to train your focus like a muscle.", "link": "https://pdf.infobooks.org/ING/PDF/thepower-of-concentration-theron-q-dumont.pdf", "icon": "🎯"},
            {"title": "Deep Work", "author": "Cal Newport", "desc": "Rules for focused success in a distracted world.", "link": "https://www.calnewport.com/books/deep-work/", "icon": "🧪"}
        ]
        for b in books:
            with st.container(border=True):
                col1, col2 = st.columns([0.8, 0.2])
                col1.markdown(f"#### {b['icon']} {b['title']}")
                col1.caption(f"by {b['author']}")
                col1.write(b['desc'])
                col2.link_button("Details", b['link'], use_container_width=True)

    with lib_tab2:
        st.markdown("### 🎥 Mastery Theater")
        st.caption("Curated high-performance habit videos.")
        videos = [
            {"title": "Atomic Habits Summary", "url": "https://www.youtube.com/watch?v=PZ7lDrwYdZc"},
            {"title": "Deep Work Masterclass", "url": "https://www.youtube.com/watch?v=3E7hkPZ-HTk"},
            {"title": "The Science of Habits", "url": "https://www.youtube.com/watch?v=Wcs2PFz5q6g"},
            {"title": "Mindset of a Champion", "url": "https://www.youtube.com/watch?v=yiB6VlSjUOk"},
            {"title": "Optimal Daily Routine", "url": "https://www.youtube.com/watch?v=S9DdUhLLdlM"}
        ]
        # 2-column grid for videos
        for i in range(0, len(videos), 2):
            cols = st.columns(2)
            for j in range(2):
                if i + j < len(videos):
                    v = videos[i+j]
                    with cols[j].container(border=True):
                        st.markdown(f"##### {v['title']}")
                        st.video(v['url'])

    with lib_tab3:
        st.markdown("### 🎬 Custom Player")
        st.caption("Paste any YouTube URL below to watch it directly in HabitBot.")
        # Use value from session_state and update it on change
        custom_url = st.text_input("YouTube URL", value=st.session_state.lib_custom_url, placeholder="https://www.youtube.com/watch?v=...", key="lib_custom_player_input")
        st.session_state.lib_custom_url = custom_url
        
        if st.session_state.lib_custom_url:
            if "youtube.com" in st.session_state.lib_custom_url or "youtu.be" in st.session_state.lib_custom_url:
                with st.container(border=True):
                    st.video(st.session_state.lib_custom_url)
                    st.success("Playing your custom resource!")
            else:
                st.warning("Please enter a valid YouTube link.")
# FINAL PWA CSS & META
pwa_html = """
<style>
    header[data-testid="stHeader"] { visibility: visible !important; background: rgba(14, 17, 23, 0.9) !important; }
    .block-container { padding-top: 1rem !important; }
    [data-testid="stSidebar"] { background-color: #0E1117 !important; }
</style>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0E1117">
"""
st.markdown(pwa_html, unsafe_allow_html=True)
