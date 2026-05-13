import wave
import struct
import base64
import io

def generate_beep_b64():
    sample_rate = 8000
    duration = 0.5  # seconds
    frequency = 1000  # Hz
    
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(sample_rate)
        
        for i in range(int(sample_rate * duration)):
            import math
            value = int(127 + 127 * math.sin(2 * math.pi * frequency * i / sample_rate))
            wav_file.writeframes(struct.pack('B', value))
            
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

print(generate_beep_b64())
