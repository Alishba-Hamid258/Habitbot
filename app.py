import streamlit as st
import json
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
    process_uploaded_file, get_notification_js, get_permission_js, get_chime_html,
    log_focus_session, get_total_focus_time, get_heatmap_data, generate_life_audit,
    archive_current_chat, get_chat_archives, get_archived_messages
)

# Cached wrappers defined here to avoid cross-file import issues on Streamlit Cloud
@st.cache_data(ttl=300)
def _cached_heatmap_data(user_id):
    return get_heatmap_data(user_id)

@st.cache_data(ttl=60)
def _cached_habit_stats(user_id):
    return get_habit_stats(user_id)
from auth import create_user, verify_user
from db import init_db

# Initialize database tables on startup
init_db()

# Page Config
st.set_page_config(page_title="HabitBot | Your Personal Coach", layout="wide", page_icon="🤖")

# ==========================================
# PWA & MOBILE OPTIMIZATION (CSS & META)
# ==========================================
pwa_html = """
<style>
    /* 1. Hide Streamlit Branding & Reclaim Space */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    .stDeployButton {display:none;}
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }

    /* 2. Thumb-Friendly UI */
    .stCheckbox label p {
        font-size: 1.1rem !important;
        padding: 8px 0 !important;
    }
    
    div[data-testid="stButton"] button {
        height: 3.2rem !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
    }

    /* 3. Horizontal Scroll for Wide Components (Heatmap) */
    div[data-testid="stPlotlyChart"] {
        overflow-x: auto !important;
        background: rgba(255, 255, 255, 0.03);
        border-radius: 12px;
        padding: 5px;
    }

    /* 4. Tab Navigation Optimization */
    button[data-baseweb="tab"] {
        font-size: 0.9rem !important;
        padding-left: 10px !important;
        padding-right: 10px !important;
    }

    /* 5. Premium Chat bubbles */
    .stChatMessage {
        background: rgba(255, 255, 255, 0.05) !important;
        border-radius: 20px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        margin-bottom: 15px !important;
        backdrop-filter: blur(10px);
        max-width: 85% !important;
    }
    
    /* Align User messages right, Assistant left (Simulated) */
    div[data-testid="stChatMessage"]:has(div[aria-label="chat user"]) {
        margin-left: auto !important;
        background: rgba(0, 104, 201, 0.1) !important;
        border-color: rgba(0, 104, 201, 0.3) !important;
    }

    .stChatInputContainer {
        border-radius: 20px !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }

    /* 6. Standalone App Feel */
    @media all and (display-mode: standalone) {
        body { background-color: #0E1117; }
    }
</style>

<!-- PWA Metadata -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0E1117">
<link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/190/190411.png">
"""
st.markdown(pwa_html, unsafe_allow_html=True)

# COOKIE MANAGER INIT
cookie_manager = stx.CookieManager()

# SESSION STATE INIT
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "logout_triggered" not in st.session_state:
    st.session_state.logout_triggered = False

# PERSISTENT LOGIN RECOVERY (Only if we haven't manually logged out)
if st.session_state.user_id is None and not st.session_state.logout_triggered:
    # Attempt to read cookie
    saved_uid = cookie_manager.get(cookie="habitbot_user_id")
    if saved_uid and st.session_state.user_id != int(saved_uid):
        st.session_state.user_id = int(saved_uid)
        st.rerun()

if "last_input" not in st.session_state: st.session_state.last_input = ""
if "timer_mode" not in st.session_state: st.session_state.timer_mode = "🍅 Focus"
if "timer_active" not in st.session_state: st.session_state.timer_active = False
if "timer_seconds" not in st.session_state: st.session_state.timer_seconds = 1500 # Default 25 min
if "timer_max_seconds" not in st.session_state: st.session_state.timer_max_seconds = 1500

# ==========================================
# AUTHENTICATION SCREEN
# ==========================================
if st.session_state.user_id is None:
    # If we are not in logout mode, we might be waiting for a cookie to sync
    # 🛡️ Cookie Sync Logic (Wait max 3 reruns before showing login)
    if not st.session_state.logout_triggered:
        if "sync_attempts" not in st.session_state: st.session_state.sync_attempts = 0
        st.session_state.sync_attempts += 1
        
        with st.status("🔒 Securing your session...", expanded=True) as status:
            st.write("Syncing with your encrypted vault...")
            
            # If we've tried syncing a few times and still no user_id, show login
            if st.session_state.sync_attempts > 2:
                st.session_state.logout_triggered = True
                st.rerun()
                
            if st.button("Force Login"):
                st.session_state.logout_triggered = True
                st.rerun()

    # Only show the login form if we are in logout mode or no cookie was found
    if st.session_state.logout_triggered:
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
                        cookie_manager.set("habitbot_user_id", str(uid), expires_at=expiry)
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
                            st.success("Account created! You can now log in.")
                        else:
                            st.error("Username already taken.")
    st.stop()

# ==========================================
# MAIN APP (AUTHENTICATED)
# ==========================================
uid = st.session_state.user_id

# REQUEST NOTIFICATION PERMISSIONS
st.markdown(get_permission_js(), unsafe_allow_html=True)

# CALLBACKS
def delete_habit_cb(idx): delete_habit(uid, idx)
def toggle_freeze_cb():
    logged = get_todays_logged_habits(uid)
    if "❄️ Freeze Day" in logged: unlog_habit(uid, "❄️ Freeze Day")
    else: log_habit(uid, "❄️ Freeze Day", "System")
def add_core_habit_cb():
    h = st.session_state.new_core_habit_in.strip()
    if h:
        current = load_core_habits(uid)
        if h not in current:
            current.append(h)
            save_core_habits(uid, current)
            st.session_state.new_core_habit_in = ""
def delete_core_habit_cb(idx):
    current = load_core_habits(uid)
    current.pop(idx)
    save_core_habits(uid, current)
def toggle_daily_habit_cb(habit_text):
    logged = get_todays_logged_habits(uid)
    if habit_text in logged: unlog_habit(uid, habit_text)
    else: log_habit(uid, habit_text, "Daily Matrix")

# SIDEBAR
with st.sidebar:
    st.title("🤖 HabitBot")
    st.caption(f"Logged in as User ID: {uid}")
    if st.button("Logout", type="secondary", use_container_width=True):
        st.session_state.user_id = None
        st.session_state.logout_triggered = True # Tell the app we want to stay out
        cookie_manager.delete("habitbot_user_id")
        st.rerun()

    st.markdown("---")
    
    # ⏲️ Focus Timer
    st.markdown("### ⏲️ Focus Timer")
    with st.expander("⚙️ Timer Settings"):
        f_min = st.number_input("Focus (min)", 1, 120, 25, key="cfg_focus")
        s_min = st.number_input("Short Break", 1, 30, 5, key="cfg_short")
        l_min = st.number_input("Long Break", 1, 60, 15, key="cfg_long")

    POMODORO_MODES = {
        "🍅 Focus": f_min * 60,
        "☕ Short Break": s_min * 60,
        "🛋️ Long Break": l_min * 60
    }

    @st.fragment(run_every="1s")
    def smooth_timer():
        modes = list(POMODORO_MODES.keys())
        current_idx = modes.index(st.session_state.timer_mode)
        
        if st.session_state.timer_max_seconds != POMODORO_MODES[st.session_state.timer_mode] and not st.session_state.timer_active:
             st.session_state.timer_max_seconds = POMODORO_MODES[st.session_state.timer_mode]
             st.session_state.timer_seconds = POMODORO_MODES[st.session_state.timer_mode]

        selected_mode = st.radio("Mode", modes, index=current_idx, horizontal=True, label_visibility="collapsed")
        if selected_mode != st.session_state.timer_mode:
            st.session_state.timer_mode = selected_mode
            st.session_state.timer_max_seconds = POMODORO_MODES[selected_mode]
            st.session_state.timer_seconds = POMODORO_MODES[selected_mode]
            st.session_state.timer_active = False
            st.rerun()

        if st.session_state.timer_active and st.session_state.timer_seconds > 0:
            st.session_state.timer_seconds -= 1
            if st.session_state.timer_seconds <= 0:
                st.session_state.timer_active = False
                st.balloons()
                log_focus_session(uid, st.session_state.timer_mode, st.session_state.timer_max_seconds // 60)
                st.markdown(get_notification_js("HabitBot ⏲️", f"{st.session_state.timer_mode} session complete!"), unsafe_allow_html=True)
                st.markdown(get_chime_html(), unsafe_allow_html=True)
                st.toast(f"✅ {st.session_state.timer_mode} session complete!", icon="🔔")

        mins, secs = divmod(st.session_state.timer_seconds, 60)
        st.markdown(f"<h1 style='text-align: center;'>{mins:02d}:{secs:02d}</h1>", unsafe_allow_html=True)
        st.progress(st.session_state.timer_seconds / st.session_state.timer_max_seconds)
        
        c1, c2 = st.columns(2)
        if st.session_state.timer_active:
            if c1.button("⏹ Pause", use_container_width=True): st.session_state.timer_active = False; st.rerun()
        else:
            if c1.button("🚀 Start", use_container_width=True): st.session_state.timer_active = True; st.rerun()
        if c2.button("🔄 Reset", use_container_width=True):
            st.session_state.timer_seconds = st.session_state.timer_max_seconds
            st.session_state.timer_active = False
            st.rerun()

    smooth_timer()

    st.markdown("---")
    st.markdown("### 🛡️ Daily Matrix")
    core_habits = load_core_habits(uid)
    todays_logged = get_todays_logged_habits(uid)
    
    is_frozen = "❄️ Freeze Day" in todays_logged
    btn_text = "☀️ Unfreeze Day" if is_frozen else "❄️ Use Freeze Day"
    st.button(btn_text, on_click=toggle_freeze_cb, use_container_width=True)

    for h in core_habits:
        is_done = h in todays_logged
        st.checkbox(h, value=is_done, key=f"daily_check_{h}", on_change=toggle_daily_habit_cb, args=(h,))

    with st.expander("⚙️ Manage Core Habits"):
        st.text_input("New Core Habit:", key="new_core_habit_in")
        st.button("Add Habit", on_click=add_core_habit_cb)
        for i, h in enumerate(core_habits):
            col1, col2 = st.columns([0.8, 0.2])
            col1.write(h)
            col2.button("🗑️", key=f"del_core_{i}", on_click=delete_core_habit_cb, args=(i,))

# MAIN TABS
tab_chat, tab_stats, tab_todo, tab_logbook = st.tabs(["💬 Habit Coach", "📊 Analytics", "✅ To-Do List", "📓 Logbook"])

# INIT MESSAGES
if "messages" not in st.session_state:
    saved = load_history(uid)
    st.session_state.messages = saved if saved else [{"role": "system", "content": SYSTEM_PROMPT}]

# TAB 1: CHAT
with tab_chat:
    if "view_archive" not in st.session_state: st.session_state.view_archive = None

    if st.session_state.view_archive:
        col_back, col_title = st.columns([0.3, 0.7])
        if col_back.button("⬅️ Back to Active Chat", use_container_width=True):
            st.session_state.view_archive = None
            st.rerun()
        col_title.markdown("### 📜 Archived Session")
        
        for m in st.session_state.view_archive[1:]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        st.stop() # Prevent showing the active chat/input when viewing archive

    col1, col2 = st.columns([0.7, 0.3])
    col1.markdown("### 💬 Habit Coach")
    
    # Archive Check
    if col2.button("➕ New Chat", use_container_width=True):
        archive_current_chat(uid, st.session_state.messages)
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_history(uid, st.session_state.messages)
        st.rerun()

    with st.expander("📜 Previous Sessions Archive"):
        archives = get_chat_archives(uid)
        if archives:
            for sid, name, ts in archives:
                if st.button(f"📄 {ts} | {name}", key=f"arch_{sid}", use_container_width=True):
                    st.session_state.view_archive = get_archived_messages(uid, sid)
                    st.rerun()
        else:
            st.write("No archived sessions yet.")
    
    st.markdown("---")

    for m in st.session_state.messages[1:]:
        avatar = "🤖" if m["role"] == "assistant" else "👤"
        with st.chat_message(m["role"], avatar=avatar):
            content = m["content"]
            if "[FILE ATTACHMENT]:" in content:
                main_text, attachment = content.split("[FILE ATTACHMENT]:", 1)
                st.markdown(main_text.strip())
                with st.expander("📄 View Attached Document"): st.text(attachment.strip())
            else: st.markdown(content)

    with st.popover("📎", use_container_width=False):
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

            with st.chat_message("user", avatar="👤"):
                st.markdown(prompt)
                if file_payload: st.caption(f"📎 Attached: {uploaded_file.name}")

            if not is_on_topic(prompt, st.session_state.messages):
                refusal = "I specialized in habits and productivity. Try asking about routines!"
                with st.chat_message("assistant", avatar="🤖"): st.markdown(refusal)
                st.session_state.messages.append({"role": "assistant", "content": refusal})
            else:
                st.session_state.messages.append({"role": "user", "content": final_prompt})
                habit_summary = get_habit_context(uid)
                dynamic_messages = st.session_state.messages.copy()
                dynamic_messages[0] = {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nUSER'S CURRENT PROGRESS:\n{habit_summary}"}
                with st.chat_message("assistant", avatar="🤖"):
                    reply = st.write_stream(call_llm(dynamic_messages, stream=True, image_data=image_data))
                st.session_state.messages.append({"role": "assistant", "content": reply})
                save_history(uid, st.session_state.messages)
                st.session_state.last_input = ""
                st.rerun()

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
    
    # Sort days
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # Create a unique week identifier for the pivot
    df['week_id'] = df['year'].astype(str) + "-W" + df['week_of_year'].astype(str).str.zfill(2)
    
    pivot = df.pivot(index='day_of_week', columns='week_id', values='count').reindex(day_order)
    
    # Clean column names for display (just show week number or nothing)
    display_cols = [c.split("-W")[-1] for c in pivot.columns]

    fig = px.imshow(
        pivot,
        labels=dict(x="Weeks (Last 12 Months)", y="Day of Week", color="Habits"),
        x=display_cols,
        y=pivot.index,
        color_continuous_scale="Blues",
        aspect="auto",
        template="plotly_dark"
    )
    
    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=10, b=10),
        xaxis_nticks=12,
        coloraxis_showscale=False,
        dragmode=False # Disable drag for better mobile scrolling
    )
    st.plotly_chart(fig, use_container_width=False, config={'displayModeBar': False})

# TAB 2: ANALYTICS
with tab_stats:
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

# TAB 3: TO-DO
with tab_todo:
    st.subheader("AI Task Architect")
    todos = load_todos(uid)
    
    if st.button("✨ Generate AI Tasks"):
        with st.spinner("Analyzing goals..."):
            history = get_weekly_summary(uid)
            msg = [{"role": "system", "content": ARCHITECT_PROMPT}, {"role": "user", "content": f"My weekly summary:\n{history}"}]
            ai_tasks_json = call_llm(msg)
            try:
                new_tasks = json.loads(ai_tasks_json)
                todos.extend(new_tasks)
                save_todos(uid, todos)
                st.rerun()
            except: st.error("AI returned invalid task format.")

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
        done = c1.checkbox("", value=t["done"], key=f"todo_{i}")
        if done != t["done"]:
            todos[i]["done"] = done
            save_todos(uid, todos)
            st.rerun()
        c2.markdown(f"**{t['task']}**" if not t['done'] else f"~~{t['task']}~~")
        c3.caption(f"{t['priority']} | {t['time']}")
        if c4.button("🗑️", key=f"del_todo_{i}"):
            todos.pop(i)
            save_todos(uid, todos)
            st.rerun()

# TAB 4: LOGBOOK
with tab_logbook:
    st.subheader("The Vault")
    
    with st.expander("🌙 Evening Reflection"):
        w_well = st.text_area("What went well today?")
        friction = st.text_area("What was a point of friction?")
        if st.button("Save Reflection"):
            save_reflection(uid, w_well, friction)
            st.success("Reflected! See you tomorrow.")

    st.markdown("---")
    st.markdown("### 📥 Life Audit Export")
    st.caption("Take ownership of your data. Export your entire habit history, focus logs, and reflections to Excel.")
    
    if st.button("Prepare Audit File"):
        with st.spinner("Compiling your legendary journey..."):
            audit_data = generate_life_audit(uid)
            st.download_button(
                label="📥 Click here to Download Life Audit (.xlsx)",
                data=audit_data,
                file_name=f"HabitBot_Life_Audit_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    st.markdown("---")
    all_logs = get_all_habits(uid)
    if all_logs:
        st.dataframe(all_logs, use_container_width=True)
    else: st.write("No entries in your logbook yet.")