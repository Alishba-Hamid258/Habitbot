import os

def clean_app_py():
    path = 'app.py'
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    start_index = -1
    end_index = -1
    
    for i, line in enumerate(lines):
        if 'def get_chime_html():' in line:
            start_index = i
        if 'def extract_json_from_text(text):' in line:
            end_index = i
            break
            
    if start_index != -1 and end_index != -1:
        new_lines = lines[:start_index] + lines[end_index:]
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"Successfully removed redundant audio functions from line {start_index} to {end_index}")
    else:
        print(f"Could not find start/end markers: start={start_index}, end={end_index}")

if __name__ == "__main__":
    clean_app_py()
