import os
import json
from db import get_connection, init_db

def migrate_data():
    # Ensure DB is initialized
    init_db()
    
    conn = get_connection()
    c = conn.cursor()
    
    print("Starting migration...")
    
    # Migrate History
    if os.path.exists("history.json"):
        with open("history.json", "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
                c.executemany("INSERT INTO chat_history (role, content) VALUES (?, ?)", 
                              [(msg["role"], msg["content"]) for msg in history])
                print(f"Migrated {len(history)} chat messages.")
            except Exception as e:
                print(f"Error migrating history: {e}")
                
    # Migrate Core Habits
    if os.path.exists("core_habits.json"):
        with open("core_habits.json", "r", encoding="utf-8") as f:
            try:
                core_habits = json.load(f)
                # clear existing defaults if any
                c.execute("DELETE FROM core_habits")
                c.executemany("INSERT INTO core_habits (habit_name) VALUES (?)", [(h,) for h in core_habits])
                print(f"Migrated {len(core_habits)} core habits.")
            except Exception as e:
                print(f"Error migrating core habits: {e}")
                
    # Migrate Habits Log
    if os.path.exists("habits.json"):
        with open("habits.json", "r", encoding="utf-8") as f:
            try:
                habits = json.load(f)
                c.executemany("INSERT INTO habits_log (date, habit, category) VALUES (?, ?, ?)", 
                              [(h.get("date", ""), h.get("habit", ""), h.get("category", "General")) for h in habits])
                print(f"Migrated {len(habits)} habit logs.")
            except Exception as e:
                print(f"Error migrating habit logs: {e}")
                
    # Migrate Todos
    if os.path.exists("todo.json"):
        with open("todo.json", "r", encoding="utf-8") as f:
            try:
                todos = json.load(f)
                c.executemany("INSERT INTO todos (task, priority, time, done) VALUES (?, ?, ?, ?)", 
                              [(t.get("task", ""), t.get("priority", "Medium"), t.get("time", ""), int(t.get("done", False))) for t in todos])
                print(f"Migrated {len(todos)} todos.")
            except Exception as e:
                print(f"Error migrating todos: {e}")
                
    # Migrate Reflections
    if os.path.exists("reflections.json"):
        with open("reflections.json", "r", encoding="utf-8") as f:
            try:
                reflections = json.load(f)
                c.executemany("INSERT OR REPLACE INTO reflections (date, went_well, friction) VALUES (?, ?, ?)", 
                              [(r.get("date", ""), r.get("went_well", ""), r.get("friction", "")) for r in reflections])
                print(f"Migrated {len(reflections)} reflections.")
            except Exception as e:
                print(f"Error migrating reflections: {e}")
                
    conn.commit()
    conn.close()
    
    # Rename files to .bak
    files_to_backup = ["history.json", "core_habits.json", "habits.json", "todo.json", "reflections.json"]
    for file in files_to_backup:
        if os.path.exists(file):
            try:
                os.rename(file, f"{file}.bak")
                print(f"Backed up {file} to {file}.bak")
            except Exception as e:
                print(f"Failed to backup {file}: {e}")
                
    print("Migration complete. Existing JSON files renamed to .bak.")

if __name__ == "__main__":
    migrate_data()
