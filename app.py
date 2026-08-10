# HabitBot v4.2 - Production Release
import streamlit as st
import json
import re
import logging
import pandas as pd
import plotly.express as px
import extra_streamlit_components as stx
from datetime import datetime
import sys
import importlib
import config
import api

# Force reload helper modules to bypass Streamlit Cloud cache
if "config" in sys.modules:
    importlib.reload(sys.modules["config"])
if "api" in sys.modules:
    importlib.reload(sys.modules["api"])
if "utils" in sys.modules:
    importlib.reload(sys.modules["utils"])
if "db" in sys.modules:
    importlib.reload(sys.modules["db"])

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
    get_chime_bytes, get_ticking_html, get_start_beep_bytes, get_tick_bytes,
    log_media_if_new, get_user_xp_and_level, log_completed_task,
    get_admin_platform_stats, get_username, get_latest_media_url
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
from auth import create_user, verify_user, create_session, verify_session, destroy_session
from db import init_db, DB_NAME, get_connection

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
if "nav_selection" not in st.session_state: st.session_state.nav_selection = "💬 Coach"
if "last_input" not in st.session_state: st.session_state.last_input = ""
if "timer_mode" not in st.session_state: st.session_state.timer_mode = "🍅 Focus"
if "timer_active" not in st.session_state: st.session_state.timer_active = False
if "timer_seconds" not in st.session_state: st.session_state.timer_seconds = 1500
if "timer_max_seconds" not in st.session_state: st.session_state.timer_max_seconds = 1500
if "sb_adj_mins" not in st.session_state: st.session_state.sb_adj_mins = 25
if "play_start_sound" not in st.session_state: st.session_state.play_start_sound = False
if "lib_custom_url" not in st.session_state: st.session_state.lib_custom_url = ""

# GLOBAL SETUP
st.markdown(get_permission_js(), unsafe_allow_html=True)

# CALLBACKS (Shared between Sidebar and Main App)
def get_callbacks(user_id):
    def _toggle_freeze():
        logged = get_todays_logged_habits(user_id)
        if "❄️ Freeze Day" in logged:
            unlog_habit(user_id, "❄️ Freeze Day")
            st.session_state["show_unfreeze_toast"] = True
        else:
            log_habit(user_id, "❄️ Freeze Day", "System")
            st.session_state["trigger_snow"] = True

    def _toggle_daily(h):
        logged = get_todays_logged_habits(user_id)
        if h in logged:
            unlog_habit(user_id, h)
        else:
            log_habit(user_id, h, "Daily Matrix")
            # Check if all core habits are now completed for celebration
            core = load_core_habits(user_id)
            updated_logged = get_todays_logged_habits(user_id)
            if core and all(item in updated_logged for item in core):
                st.session_state["trigger_all_habits_balloons"] = True

    return {
        "delete_habit": lambda idx: delete_habit(user_id, idx),
        "toggle_freeze": _toggle_freeze,
        "add_core": lambda: (save_core_habits(user_id, load_core_habits(user_id) + [st.session_state.new_core_habit_in.strip()]) if st.session_state.new_core_habit_in.strip() and st.session_state.new_core_habit_in.strip() not in load_core_habits(user_id) else None),
        "delete_core": lambda idx: (save_core_habits(user_id, [h for i, h in enumerate(load_core_habits(user_id)) if i != idx])),
        "toggle_daily": _toggle_daily
    }

# (Insecure persistent query parameter login recovery removed for security)

# GLOBAL COMPONENTS
cookie_manager = stx.CookieManager(key="habitbot_cookie_manager")

# --- INSTANT SYNCHRONOUS SESSION RECOVERY (0ms Page Refresh Survival) ---
if st.session_state.user_id is None and not st.session_state.logout_triggered:
    # 1. Immediate URL parameter check (Synchronous, instant on browser reload)
    q_token = st.query_params.get("session")
    if q_token:
        uid_rec = verify_session(q_token)
        if uid_rec:
            st.session_state.user_id = uid_rec
    
    # 2. Browser cookie fallback
    if st.session_state.user_id is None:
        try:
            c_token = cookie_manager.get("habitbot_v4_session")
            if c_token and c_token not in ["None", "null", "", "undefined"]:
                uid_rec = verify_session(c_token)
                if uid_rec:
                    st.session_state.user_id = uid_rec
                    st.query_params["session"] = c_token
        except Exception:
            pass

# Restore last-watched custom media URL from SQLite for active user
if st.session_state.user_id:
    if not st.session_state.lib_custom_url:
        st.session_state.lib_custom_url = get_latest_media_url(st.session_state.user_id)

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
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})

# SIDEBAR (Status & Tools)
with st.sidebar:
    st.title("🤖 HabitBot")
    
    if st.session_state.user_id:
        uid = st.session_state.user_id
        cb = get_callbacks(uid)
        
        current_username = get_username(uid)
        
        # Profile & Logout
        with st.container(border=True):
            c1, c2 = st.columns([0.3, 0.7])
            c1.markdown("### 👤")
            c2.markdown(f"**{current_username}**  \n`ID: #{uid}`")
            if st.button("Logout", use_container_width=True):
                try:
                    cookie_val = cookie_manager.get("habitbot_v4_session")
                    if cookie_val:
                        destroy_session(cookie_val)
                except:
                    pass
                st.session_state.user_id = None
                st.session_state.logout_triggered = True
                # Clear chat history so next user doesn't see previous user's messages
                st.session_state.pop("messages", None)
                st.session_state.pop("_messages_loaded_for", None)
                try: 
                    cookie_manager.set("habitbot_v4_session", "None") # Explicitly invalidate
                    cookie_manager.delete("habitbot_v4_session")
                except: pass
                st.query_params.clear()
                st.rerun()

        st.markdown("---")

        # Pomodoro Timer (Fragmented for real-time updates)
        st.markdown("---")
        st.markdown("### ⏲️ Pomodoro")
        
        # Audio Settings
        with st.expander("🔊 Audio Settings"):
            if st.button("🔔 Test Chime", use_container_width=True):
                st.audio(get_chime_bytes(), format="audio/wav", autoplay=True)
                st.toast("Chime triggered!", icon="🎵")
        # Mode Selection & Callbacks
        def update_custom_time():
            mins = st.session_state.sb_adj_mins
            st.session_state.timer_seconds = mins * 60
            st.session_state.timer_max_seconds = mins * 60
            st.session_state.timer_mode = st.session_state.get("sb_custom_name", "Focus").strip() or "Focus"
            st.session_state.timer_active = False

        m_cols = st.columns(3)
        if m_cols[0].button("🎯", help="Focus (25m)"): 
            st.session_state.timer_seconds = 1500
            st.session_state.timer_max_seconds = 1500
            st.session_state.sb_adj_mins = 25
            st.session_state.timer_mode = "Focus"
            st.session_state.timer_active = False
            st.rerun()
        if m_cols[1].button("☕", help="Short Break (5m)"): 
            st.session_state.timer_seconds = 300
            st.session_state.timer_max_seconds = 300
            st.session_state.sb_adj_mins = 5
            st.session_state.timer_mode = "Break"
            st.session_state.timer_active = False
            st.rerun()
        if m_cols[2].button("🧘", help="Long Break (15m)"): 
            st.session_state.timer_seconds = 900
            st.session_state.timer_max_seconds = 900
            st.session_state.sb_adj_mins = 15
            st.session_state.timer_mode = "Break"
            st.session_state.timer_active = False
            st.rerun()

        # Custom Adjustment
        c_time, c_name = st.columns([0.4, 0.6])
        c_time.number_input("Mins", min_value=1, max_value=120, step=1, key="sb_adj_mins", on_change=update_custom_time)
        c_name.text_input("Name", value="Focus", key="sb_custom_name", on_change=update_custom_time, help="Name your session (e.g. 'Coding', 'Reading')")

        # Fragment for Countdown
        @st.fragment(run_every="1s")
        def timer_fragment():
            # Play start beep exactly once when starting
            if st.session_state.get("play_start_sound"):
                st.audio(get_start_beep_bytes(), format="audio/wav", autoplay=True)
                st.session_state.play_start_sound = False

            if st.session_state.timer_active and st.session_state.timer_seconds > 0:
                st.session_state.timer_seconds -= 1
                # Play tick in the final 5 seconds (5, 4, 3, 2, 1) using explicit branches to force React remounts
                if st.session_state.timer_seconds == 5:
                    st.audio(get_tick_bytes(), format="audio/wav", autoplay=True)
                elif st.session_state.timer_seconds == 4:
                    st.audio(get_tick_bytes(), format="audio/wav", autoplay=True)
                elif st.session_state.timer_seconds == 3:
                    st.audio(get_tick_bytes(), format="audio/wav", autoplay=True)
                elif st.session_state.timer_seconds == 2:
                    st.audio(get_tick_bytes(), format="audio/wav", autoplay=True)
                elif st.session_state.timer_seconds == 1:
                    st.audio(get_tick_bytes(), format="audio/wav", autoplay=True)
                
                if st.session_state.timer_seconds == 0:
                    st.session_state.timer_active = False
                    st.toast("⏰ Time's up!", icon="🔔")
                    st.audio(get_chime_bytes(), format="audio/wav", autoplay=True)
                    # Log the completed session to the database
                    duration_mins = st.session_state.timer_max_seconds // 60
                    # Ensure we use the custom name if the user set one, otherwise fallback to timer_mode
                    final_mode = st.session_state.get("sb_custom_name", "").strip()
                    if not final_mode: final_mode = st.session_state.timer_mode
                    
                    if duration_mins > 0:
                        log_focus_session(uid, final_mode, duration_mins)

            mins, secs = divmod(st.session_state.timer_seconds, 60)
            st.markdown(f"<h1 style='text-align: center; color: #FF4B4B;'>{mins:02d}:{secs:02d}</h1>", unsafe_allow_html=True)
            st.progress(max(0, min(1.0, st.session_state.timer_seconds / st.session_state.timer_max_seconds)))
            
            if st.session_state.timer_active:
                if st.button("⏹ Pause Timer", use_container_width=True, key="sb_pause"): 
                    st.session_state.timer_active = False
                    st.rerun()
            else:
                if st.button("🚀 Start Timer", use_container_width=True, key="sb_start"): 
                    st.session_state.timer_active = True
                    st.session_state.play_start_sound = True
                    st.rerun()
        
        timer_fragment()

        # (Ticking sound removed per user request)

        # Daily Matrix
        st.markdown("---")
        st.markdown("### 🛡️ Daily Matrix")
        st.caption("Tick your daily habits here. Every checkmark builds your Streak and Discipline score.")

        # Streak & Discipline — driven by this section
        streak = get_current_streak(uid)
        discipline = get_consistency_score(uid)
        c1, c2 = st.columns(2)
        c1.metric("🔥 Streak", f"{streak}d", help="Consecutive days you logged at least one habit")
        c2.metric("🎯 Discipline", f"{discipline}%", help="% of the last 30 days you were active")

        # Contextual tip & Milestone Badges
        if streak == 0 and discipline == 0:
            st.caption("💡 Check off a habit below to start your streak!")
        elif streak >= 30:
            st.success(f"👑 **{streak}-Day Legend Streak!** Truly elite discipline!", icon="👑")
        elif streak >= 14:
            st.success(f"⚡ **{streak}-Day Master Streak!** 2 unbroken weeks — habits are identity!", icon="⚡")
        elif streak >= 7:
            st.success(f"⚔️ **{streak}-Day Warrior Streak!** 1 full week of compounding growth!", icon="🔥")
        elif streak >= 3:
            st.info(f"🥉 **{streak}-Day Streak!** You've got real momentum going!", icon="🚀")
        elif streak >= 1:
            st.caption(f"🔥 {streak}-day streak — check today's habits to keep it alive!")
        if discipline >= 80:
            st.caption(f"⭐ Elite discipline ({discipline}%) — top tier consistency!")
        elif discipline >= 50:
            st.caption(f"📈 {discipline}% discipline — solid! Push for 80%+ this month.")

        st.markdown("")
        core = load_core_habits(uid)
        logged = get_todays_logged_habits(uid)
        st.button("☀️ Unfreeze Day" if "❄️ Freeze Day" in logged else "❄️ Freeze Day", on_click=cb["toggle_freeze"], use_container_width=True, key="sb_freeze_btn", help="Freeze skips today without breaking your streak")
        for h in core:
            st.checkbox(h, value=h in logged, key=f"sb_chk_{h}", on_change=cb["toggle_daily"], args=(h,))
            
        with st.expander("⚙️ Manage Core Habits"):
            st.text_input("New Habit", key="new_core_habit_in", placeholder="e.g. 🥦 Eat Veggies")
            st.button("➕ Add Habit", on_click=cb["add_core"], use_container_width=True)
            if core:
                st.markdown("---")
                st.caption("Active Core Habits:")
                for i, h in enumerate(core):
                    col_h, col_del = st.columns([0.8, 0.2])
                    col_h.write(h)
                    col_del.button("🗑️", key=f"del_core_{i}", on_click=cb["delete_core"], args=(i,))
                    
        # Persistent Background Music/Video Player
        st.markdown("---")
        with st.expander("🎵 Custom Media Player"):
            st.caption("Play background music or videos continuously across all tabs.")
            custom_url = st.text_input("YouTube URL", value=st.session_state.lib_custom_url, placeholder="https://www.youtube.com/watch?v=...", key="sb_custom_player_input")
            st.session_state.lib_custom_url = custom_url
            if custom_url:
                log_media_if_new(uid, custom_url)
            if st.session_state.lib_custom_url:
                if "youtube.com" in st.session_state.lib_custom_url or "youtu.be" in st.session_state.lib_custom_url:
                    st.video(st.session_state.lib_custom_url)
    else:
        st.info("👋 Welcome! Please log in.")

# ==========================================
# AUTHENTICATION & ADMIN PORTAL
# ==========================================
if st.session_state.user_id is None:
    # --- STANDALONE ADMIN DASHBOARD SCREEN ---
    if st.session_state.get("admin_portal_open", False):
        col_a1, col_a2 = st.columns([0.8, 0.2])
        col_a1.title("👑 HabitBot Creator Admin Portal")
        if col_a2.button("🚪 Exit Admin", use_container_width=True):
            st.session_state.admin_portal_open = False
            st.rerun()
            
        st.caption("Platform-wide analytics, registered user directory, and database management.")
        
        with st.spinner("Fetching platform analytics..."):
            admin_data = get_admin_platform_stats()
            
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("👥 Total Users", f"{admin_data['total_users']}")
        m2.metric("🛡️ Habits Tracked", f"{admin_data['total_habits']}")
        focus_hours = round(admin_data['total_focus_mins'] / 60.0, 1)
        m3.metric("🧠 Deep Work", f"{focus_hours} hrs")
        m4.metric("✅ Finished Tasks", f"{admin_data['total_tasks']}")
        m5.metric("💬 Chat Sessions", f"{admin_data['total_chat_archives']}")
        
        st.markdown("---")
        
        st.markdown("### 📋 Registered Users Directory")
        users_df = admin_data['users_df']
        if not users_df.empty:
            st.dataframe(
                users_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "User ID": st.column_config.NumberColumn("User ID", format="%d"),
                    "Username": st.column_config.TextColumn("Username"),
                    "Joined Date": st.column_config.TextColumn("Joined Date"),
                    "Habits Checked": st.column_config.NumberColumn("Habits Completed", format="%d 🛡️"),
                    "Focus Mins": st.column_config.NumberColumn("Focus Time", format="%d mins 🍅")
                }
            )
        else:
            st.info("No registered users found.")
            
        st.markdown("---")
        st.info(f"💾 **Active Database Engine**: SQLite (`{DB_NAME}`)\n\n"
                f"🚀 **Scaling to Free Cloud DB**: When your user base grows, you can connect **Supabase** or **Turso** to keep data permanently across all cloud restarts!")
        st.stop()

    # --- COOKIE RECOVERY ATTEMPT ---
    if not st.session_state.logout_triggered:
        try:
            cookie_val = cookie_manager.get("habitbot_v4_session")
            if cookie_val and cookie_val not in ["None", "null", "", "undefined"]:
                uid = verify_session(cookie_val)
                if uid:
                    st.session_state.user_id = uid
                    st.rerun()
        except: pass

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🤖 HabitBot v4.0")
        st.markdown("### Secure Login & Privacy")
        
        tab_login, tab_signup, tab_admin = st.tabs(["🔐 Login", "📝 Sign Up", "👑 Admin Portal"])
        
        with tab_login:
            u = st.text_input("Username", key="l_u")
            p = st.text_input("Password", type="password", key="l_p")
            if st.button("Login", use_container_width=True):
                uid = verify_user(u, p)
                if uid:
                    token = create_session(uid)
                    if token:
                        st.session_state.user_id = uid
                        st.session_state.logout_triggered = False
                        st.query_params["session"] = token
                        # Restore last active video URL
                        st.session_state.lib_custom_url = get_latest_media_url(uid)
                        # Save to cookie for 30 days
                        import datetime as dt
                        expiry = dt.datetime.now() + dt.timedelta(days=30)
                        cookie_manager.set("habitbot_v4_session", token, expires_at=expiry)
                        st.rerun()
                    else:
                        st.error("Failed to initialize session.")
                else:
                    st.error("Invalid username or password.")
        
        with tab_signup:
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
                        st.success("Account created! You can now switch to the 'Login' tab to enter.")
                    else:
                        st.error("Username already taken.")
                        
        with tab_admin:
            st.info("🔒 Creator & Admin Access Only")
            admin_u = st.text_input("Admin Username", value="admin", key="admin_auth_u")
            admin_p = st.text_input("Admin Password", type="password", value="admin123", key="admin_auth_p")
            if st.button("👑 Enter Admin Portal", use_container_width=True, type="primary"):
                if admin_u.strip() == "admin" and admin_p == "admin123":
                    st.session_state.admin_portal_open = True
                    st.rerun()
                else:
                    st.error("Invalid Admin credentials. (Default: admin / admin123)")
    st.stop()

# ==========================================
# MAIN APP (AUTHENTICATED)
# ==========================================
uid = st.session_state.user_id

current_username = get_username(uid)
is_admin = (uid == 1) or ("admin" in current_username.lower()) or st.session_state.get("is_admin_unlocked", False)

# Header bar with Stats
xp_info = get_user_xp_and_level(uid)
st.markdown(f"<p style='text-align:right; margin:0 0 10px 0;'>🎮 <b>Lv.{xp_info['level']}</b> ({xp_info['total_xp']} XP) &nbsp;|&nbsp; 🔥 {get_current_streak(uid)}d &nbsp;|&nbsp; 🎯 {get_consistency_score(uid)}%</p>", unsafe_allow_html=True)

# Milestone & Action Celebrations
if st.session_state.pop("trigger_snow", False):
    st.snow()
    st.toast("❄️ Day Frozen! Your streak is safely shielded without breaking.", icon="🧊")
if st.session_state.pop("show_unfreeze_toast", False):
    st.toast("☀️ Day Unfrozen! Welcome back to active habit tracking.", icon="☀️")
if st.session_state.pop("trigger_all_habits_balloons", False):
    st.balloons()
    st.toast("🎉 Perfect Day! You've completed ALL core habits today! (+XP Earned)", icon="🏆")

# Re-load history whenever the active user changes (prevents cross-user bleed)
if "messages" not in st.session_state or st.session_state.get("_messages_loaded_for") != uid:
    saved = load_history(uid)
    st.session_state.messages = saved if saved else [{"role": "system", "content": SYSTEM_PROMPT}]
    st.session_state._messages_loaded_for = uid

# Native Tabs — Instant client-side tab switching with ZERO network delay and ZERO element bleed
tab_coach, tab_analytics, tab_tasks, tab_logbook, tab_library = st.tabs([
    "💬 Coach", "📊 Analytics", "✅ Tasks", "📓 Logbook", "📚 Library"
])

# -------------------------------------------------------------
# TAB 1: HABIT COACH
# -------------------------------------------------------------
with tab_coach:
    if "view_archive" not in st.session_state: st.session_state.view_archive = None

    if st.session_state.view_archive:
        col_back, col_title = st.columns([0.3, 0.7])
        if col_back.button("⬅️ Back to Active Chat", use_container_width=True):
            st.session_state.view_archive = None
            st.rerun()
        col_title.markdown("### 📜 Archived Session")
        for m in st.session_state.view_archive[1:]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
    else:
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
        
        # 1. Main Chat Container (Always placed ABOVE input widgets)
        chat_container = st.container()
        
        with chat_container:
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

            # 2. Interactive Quick-Prompt Chips (Only shown when starting a fresh chat)
            prompt_from_chip = None
            if len(st.session_state.messages) <= 1:
                st.caption("💡 Choose a quick topic or type your own question below:")
                chip_cols = st.columns(4)
                if chip_cols[0].button("⚡ Plan My Day", use_container_width=True, key="chip_btn_1"):
                    prompt_from_chip = "Help me plan an ultra-productive day using time-blocking and habit stacking."
                if chip_cols[1].button("🧠 Beat Procrastination", use_container_width=True, key="chip_btn_2"):
                    prompt_from_chip = "I'm procrastinating on an important task. Guide me through the 2-minute rule to start immediately."
                if chip_cols[2].button("💪 Morning Routine", use_container_width=True, key="chip_btn_3"):
                    prompt_from_chip = "Design an energizing 30-minute morning routine based on behavioral science."
                if chip_cols[3].button("🎯 Habit Audit", use_container_width=True, key="chip_btn_4"):
                    prompt_from_chip = "Audit my daily habits and tell me which smallest adjustment will compound the most."
                st.markdown("")

        # 3. Input Controls (Always placed BELOW chat_container at the bottom)
        uploaded_file = st.file_uploader("Attach context", type=["png", "jpg", "jpeg", "webp", "pdf", "txt", "md"], label_visibility="collapsed")
        chat_input_val = st.chat_input("Ask about habits…")
        prompt = prompt_from_chip or chat_input_val
        
        if prompt:
            file_payload = process_uploaded_file(uploaded_file)
            image_data = None
            final_prompt = prompt
            if file_payload:
                if file_payload["type"] == "image": image_data = file_payload["data"]
                else: final_prompt = f"{prompt}\n\n[FILE ATTACHMENT]:\n{file_payload['data']}"
                
            # Render new user message & assistant reply INSIDE chat_container (ABOVE input box!)
            with chat_container:
                with st.chat_message("user", avatar="👤"): st.markdown(prompt)
                if file_payload is None and not is_on_topic(prompt, st.session_state.messages):
                    refusal = "I specialized in habits and productivity."
                    with st.chat_message("assistant", avatar="🤖"): st.markdown(refusal)
                    st.session_state.messages.append({"role": "user", "content": final_prompt})
                    st.session_state.messages.append({"role": "assistant", "content": refusal})
                    save_history(uid, st.session_state.messages)
                    st.rerun()
                else:
                    habit_summary = get_habit_context(uid)
                    dynamic_messages = st.session_state.messages.copy()
                    dynamic_messages.append({"role": "user", "content": final_prompt})
                    dynamic_messages[0] = {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nPROGRESS:\n{habit_summary}"}
                    with st.chat_message("assistant", avatar="🤖"):
                        llm_response = call_llm(dynamic_messages, stream=True, image_data=image_data)
                        if not isinstance(llm_response, str):
                            reply = st.write_stream(llm_response)
                        else:
                            st.markdown(llm_response)
                            reply = llm_response
                    
                    # Sanitize final saved replies against unclosed think tags
                    from api import clean_think_tags
                    reply = clean_think_tags(reply)
                    if not reply.strip():
                        reply = "⚠️ The AI server timed out or returned an empty response due to temporary capacity constraints. Please try resending your message."
                    st.session_state.messages.append({"role": "user", "content": final_prompt})
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    save_history(uid, st.session_state.messages)
                    st.rerun()

# -------------------------------------------------------------
# TAB 2: ANALYTICS
# -------------------------------------------------------------
with tab_analytics:
    # GAMIFICATION & MASTERY XP CARD
    xp_data = get_user_xp_and_level(uid)
    with st.container(border=True):
        g_c1, g_c2 = st.columns([0.65, 0.35])
        with g_c1:
            st.markdown(f"### {xp_data['title']}")
            if xp_data['level'] < 10:
                st.caption(f"🚀 **{xp_data['needed_xp']} XP** needed to reach **Level {xp_data['level'] + 1}**")
            else:
                st.caption("👑 Max level reached! You are a true Discipline Grandmaster.")
            st.progress(xp_data['progress_pct'])
        with g_c2:
            st.metric("Total Experience", f"{xp_data['total_xp']} XP", delta=f"Level {xp_data['level']}")

        st.caption(f"💡 **XP Breakdown**: 🛡️ Habits: `+{xp_data['habits_xp']} XP` | 🍅 Focus Time: `+{xp_data['focus_xp']} XP` | 🌙 Reflections: `+{xp_data['reflections_xp']} XP` | ✅ Tasks: `+{xp_data['tasks_xp']} XP`")

    st.markdown("---")
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

# -------------------------------------------------------------
# TAB 3: TO-DO TASKS
# -------------------------------------------------------------
with tab_tasks:
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
    # Task Progress Metrics & Bar
    total_tasks = len(todos)
    completed_tasks = sum(1 for t in todos if t.get("done", False))
    
    if total_tasks > 0:
        pct = int((completed_tasks / total_tasks) * 100)
        p_col1, p_col2 = st.columns([0.7, 0.3])
        p_col1.markdown(f"#### 📋 Progress: `{completed_tasks}/{total_tasks}` completed ({pct}%)")
        if completed_tasks > 0:
            if p_col2.button("🧹 Clear Completed", use_container_width=True, help="Remove all checked-off tasks"):
                todos = [t for t in todos if not t.get("done", False)]
                save_todos(uid, todos)
                st.rerun()
        st.progress(completed_tasks / total_tasks)
        
        if completed_tasks == total_tasks:
            st.success("🎉 **All tasks completed!** You conquered your entire list today!", icon="🏆")
        elif pct >= 50:
            st.info("🔥 **Over halfway done!** Keep the momentum rolling.", icon="⚡")
        st.markdown("")
    else:
        st.caption("No tasks yet. Generate tasks with the AI Architect above or add one manually!")

    for i, t in enumerate(todos):
        c1, c2, c3, c4 = st.columns([0.1, 0.6, 0.2, 0.1])
        t_id = t.get("id") or f"{i}_{abs(hash(t.get('task', '')))}"
        t_done = t.get("done", False)
        t_task = t.get("task", "Untitled Task")
        t_pri = t.get("priority", "Medium")
        t_time = t.get("time", "")
        done = c1.checkbox("Done", value=t_done, key=f"todo_chk_{t_id}", label_visibility="collapsed")
        if done != t_done:
            todos[i]["done"] = done
            if done:
                log_completed_task(uid, t_task)
            save_todos(uid, todos)
            st.rerun()
        c2.markdown(f"**{t_task}**" if not t_done else f"~~{t_task}~~")
        c3.caption(f"{t_pri} | {t_time}")
        if c4.button("🗑️", key=f"del_todo_{t_id}"):
            todos.pop(i)
            save_todos(uid, todos)
            st.rerun()

# -------------------------------------------------------------
# TAB 4: LOGBOOK
# -------------------------------------------------------------
with tab_logbook:
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
                # Guarantee media_history table exists before export (bypasses all module caching)
                try:
                    _conn = get_connection()
                    _conn.execute('''CREATE TABLE IF NOT EXISTS media_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, date TEXT, url TEXT, title TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(id))''')
                    _conn.commit()
                    _conn.close()
                except Exception:
                    pass
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
        except Exception:
            st.info("Database file not found yet.")

# -------------------------------------------------------------
# TAB 5: LIBRARY
# -------------------------------------------------------------
with tab_library:
    st.subheader("📚 Mastery Library")
    st.caption("Curated resources to sharpen your habits and mindset.")

    lib_tab1, lib_tab2, lib_tab3 = st.tabs(["📖 Essential Books", "🎥 Mastery Theater", "🎬 Custom Player"])

    with lib_tab1:
        st.markdown("### 📖 The Habit Blueprint")
        books = [
            {"title": "The Power of Habit", "author": "Charles Duhigg", "desc": "Why we do what we do in life and business.", "link": "https://archive.org/details/the-power-of-habit-charles-duhigg", "icon": "🔄"},
            {"title": "Think and Grow Rich", "author": "Napoleon Hill", "desc": "The classic guide to success and wealth.", "link": "https://archive.org/details/thinkandgrowrich00hill", "icon": "💰"},
            {"title": "As a Man Thinketh", "author": "James Allen", "desc": "How your thoughts shape your reality.", "link": "https://www.gutenberg.org/ebooks/4507", "icon": "🧠"},
            {"title": "The Science of Getting Rich", "author": "Wallace D. Wattles", "desc": "The mental science behind prosperity.", "link": "https://www.gutenberg.org/ebooks/59832", "icon": "📈"},
            {"title": "The Power of Concentration", "author": "Theron Q. Dumont", "desc": "Exercises to train your focus like a muscle.", "link": "https://www.gutenberg.org/ebooks/49214", "icon": "🎯"},
            {"title": "Deep Work", "author": "Cal Newport", "desc": "Rules for focused success in a distracted world.", "link": "https://openlibrary.org/works/OL17841393W/Deep_Work", "icon": "🧪"}
        ]
        for b in books:
            with st.container(border=True):
                col1, col2 = st.columns([0.8, 0.2])
                col1.markdown(f"#### {b['icon']} {b['title']}")
                col1.caption(f"by {b['author']}")
                col1.write(b['desc'])
                col2.link_button("📖 Read Free", b['link'], use_container_width=True)

    with lib_tab2:
        st.markdown("### 🎥 Mastery Theater")
        st.caption("Curated high-performance habit videos.")
        videos = [
            {"title": "Atomic Habits Summary", "url": "https://www.youtube.com/watch?v=PZ7lDrwYdZc"},
            {"title": "Deep Work Masterclass", "url": "https://www.youtube.com/watch?v=3E7hkPZ-HTk"},
            {"title": "The Science of Habits", "url": "https://www.youtube.com/watch?v=Wcs2PFz5q6g"},
            {"title": "Forget Big Change (Tiny Habits)", "url": "https://www.youtube.com/watch?v=AdKUJxjn-R8"},
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
        st.caption("Paste a YouTube URL below — it will play here **and** keep playing in the sidebar when you switch tabs!")
        
        custom_url = st.text_input(
            "YouTube URL",
            value=st.session_state.lib_custom_url,
            placeholder="https://www.youtube.com/watch?v=...",
            key="lib_custom_player_input"
        )
        # Update shared session state so sidebar player picks it up
        st.session_state.lib_custom_url = custom_url
        if custom_url:
            log_media_if_new(uid, custom_url)

        if st.session_state.lib_custom_url:
            if "youtube.com" in st.session_state.lib_custom_url or "youtu.be" in st.session_state.lib_custom_url:
                with st.container(border=True):
                    st.video(st.session_state.lib_custom_url)
                    st.success("✅ Also playing in the sidebar — switch to any tab and it keeps going!")
            else:
                st.warning("Please enter a valid YouTube link.")
# FINAL PWA CSS & META
pwa_html = """
<style>
    /* Hide all Streamlit audio player widgets and their element containers completely */
    [data-testid="stAudio"], div[data-testid="element-container"]:has(audio), audio {
        display: none !important;
        height: 0px !important;
        margin: 0px !important;
        padding: 0px !important;
    }
    
    header[data-testid="stHeader"] { visibility: visible !important; background: rgba(14, 17, 23, 0.9) !important; }
    .block-container { padding-top: 1rem !important; }
    [data-testid="stSidebar"] { background-color: #0E1117 !important; }
    
    /* Fallback styles: make standard uploader look nice if not yet nested */
    div[data-testid="stFileUploader"] {
        padding: 0 !important;
        margin-bottom: 10px !important;
    }
    div[data-testid="stFileUploader"] section {
        padding: 10px 16px !important;
        min-height: unset !important;
        border-radius: 12px !important;
        border: 1px dashed rgba(255, 255, 255, 0.15) !important;
        background-color: rgba(255, 255, 255, 0.03) !important;
    }
    
    /* Sleek, Low-Profile File Uploader styled as inline '+' button inside stChatInput */
    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] {
        display: block !important;
        position: absolute !important;
        left: 12px !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        width: 32px !important;
        height: 32px !important;
        z-index: 999999 !important;
        overflow: visible !important;
        padding: 0 !important;
        margin: 0 !important;
    }

    /* Customize the file uploader dropzone into a circular '+' button when nested */
    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] section {
        width: 32px !important;
        height: 32px !important;
        padding: 0 !important;
        min-height: unset !important;
        border-radius: 50% !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        background-color: rgba(255, 255, 255, 0.05) !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
        overflow: hidden !important;
        transition: background-color 0.2s ease, border-color 0.2s ease;
    }

    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] section:hover {
        background-color: rgba(255, 255, 255, 0.15) !important;
        border-color: rgba(255, 255, 255, 0.4) !important;
    }

    /* Hide all text inside the dropzone when nested */
    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] section > div {
        display: none !important;
    }

    /* Inject a '+' sign using pseudo-element when nested */
    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] section::after {
        content: "+" !important;
        font-size: 20px !important;
        color: rgba(255, 255, 255, 0.7) !important;
        font-weight: normal !important;
        display: block !important;
        line-height: 28px !important;
        text-align: center !important;
    }

    /* Shift the chat input content area to the right to make room for the '+' button */
    div[data-testid="stChatInput"] {
        padding-left: 48px !important;
        position: relative !important;
    }

    /* Let the uploaded file name floating container render above the chat bar */
    div[data-testid="stChatInput"] div[data-testid="stFileUploader"] [data-testid="stUploadedFileData"] {
        position: absolute !important;
        bottom: 45px !important;
        left: -4px !important;
        width: 260px !important;
        background-color: #1e1e1e !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 8px !important;
        padding: 8px !important;
        z-index: 10000 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
    }
</style>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0E1117">

<script>
    (function() {
        function moveUploader() {
            try {
                // Try parent document (for same-origin iframes)
                const doc = window.parent.document;
                const uploader = doc.querySelector('div[data-testid="stFileUploader"]');
                const chatInput = doc.querySelector('div[data-testid="stChatInput"]');
                if (uploader && chatInput) {
                    if (uploader.parentNode !== chatInput) {
                        chatInput.insertBefore(uploader, chatInput.firstChild);
                    }
                }
            } catch (e) {
                // If parent document access throws a SecurityError, fallback safely to local document
                try {
                    const uploader = document.querySelector('div[data-testid="stFileUploader"]');
                    const chatInput = document.querySelector('div[data-testid="stChatInput"]');
                    if (uploader && chatInput) {
                        if (uploader.parentNode !== chatInput) {
                            chatInput.insertBefore(uploader, chatInput.firstChild);
                        }
                    }
                } catch (innerErr) {
                    console.error("Failed to move uploader:", innerErr);
                }
            }
        }
        moveUploader();
        setInterval(moveUploader, 250);
    })();
</script>
"""
st.markdown(pwa_html, unsafe_allow_html=True)
