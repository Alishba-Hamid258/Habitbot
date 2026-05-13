import os

def fix_utils_py():
    path = 'utils.py'
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace get_ticking_html and add get_prime_audio_js
    new_ticking = '''def get_ticking_html():
    # Return empty string to disable ticking as requested
    return ""

def get_prime_audio_js():
    return """<script>
        window.primeAudio = function() {
            // Triggered on first user interaction to unlock audio context
            const a = new Audio("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=");
            a.play().catch(() => {});
        }
    </script>"""
'''
    
    # We find where get_ticking_html starts and replace everything from there to the end
    # Assuming get_ticking_html is the last function
    start_marker = 'def get_ticking_html():'
    idx = content.find(start_marker)
    if idx != -1:
        new_content = content[:idx] + new_ticking
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Successfully updated utils.py")
    else:
        print("Could not find get_ticking_html in utils.py")

if __name__ == "__main__":
    fix_utils_py()
