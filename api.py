# api.py
import httpx
import json
import logging
from config import Config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

import re

def clean_think_tags(text: str) -> str:
    """Strip out internal <think>...</think> reasoning blocks from Qwen/DeepSeek models."""
    if not text:
        return ""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*$', '', text, flags=re.DOTALL)
    return text.strip()


def get_best_gemini_model() -> str:
    """Query Google AI Studio programmatically to discover the best active Gemini model."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={Config.GEMINI_API_KEY}"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                flash_models = [
                    m["name"].split("/")[-1] for m in data.get("models", [])
                    if "flash" in m.get("name", "").lower()
                    and "generateContent" in m.get("supportedGenerationMethods", [])
                    and "preview" not in m.get("name", "").lower()
                ]
                if flash_models:
                    flash_models.sort(reverse=True)
                    log.info(f"Successfully discovered active Gemini models. Selected: {flash_models[0]}")
                    return flash_models[0]
    except Exception as e:
        log.error(f"Error discovering Gemini models: {e}")
    return "gemini-3.5-flash"  # Active 2026 default fallback

def call_gemini(messages: list[dict], image_data: str = None):
    """Call Google Gemini API as a robust free tier vision/text provider."""
    model_id = get_best_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={Config.GEMINI_API_KEY}"
    headers = {
        "Content-Type": "application/json"
    }
    
    system_prompt = ""
    contents = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        if role == "system":
            system_prompt = clean_think_tags(content)
            continue
            
        mapped_role = "model" if role == "assistant" else "user"
        
        if isinstance(content, list):
            texts = [c["text"] for c in content if c.get("type") == "text"]
            content = " ".join(texts) if texts else ""
            
        contents.append({
            "role": mapped_role,
            "parts": [{"text": clean_think_tags(content)}]
        })
        
    # Inject image attachment to the last user message block if present
    if image_data and contents:
        for i in range(len(contents) - 1, -1, -1):
            if contents[i]["role"] == "user":
                contents[i]["parts"].append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_data
                    }
                })
                break
                
    payload = {
        "contents": contents
    }
    
    if system_prompt:
        payload["systemInstruction"] = {
            "parts": [{"text": system_prompt}]
        }
        
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                try:
                    reply = data["candidates"][0]["content"]["parts"][0]["text"]
                    return clean_think_tags(reply)
                except Exception as e:
                    log.error(f"Error parsing Gemini response: {e}. Raw response: {data}")
                    return "⚠️ Error parsing Gemini response."
            else:
                log.error(f"=== GEMINI ERROR {r.status_code} ===\n{r.text[:500]}")
                return f"⚠️ Gemini API Error ({r.status_code}): {r.text[:300]}"
    except Exception as exc:
        log.exception("=== GEMINI UNEXPECTED ERROR ===")
        return f"⚠️ Gemini Connection Error: {exc}"

def call_llm(messages: list[dict], stream: bool = False, image_data: str = None):
    # Route vision / image requests to Google Gemini if API Key is configured
    if image_data and getattr(Config, "GEMINI_API_KEY", None):
        return call_gemini(messages, image_data)

    if not Config.GROQ_API_KEY:
        # Fallback to Gemini if Groq is missing but Gemini key is available
        if getattr(Config, "GEMINI_API_KEY", None):
            return call_gemini(messages, image_data)
            
        msg = "Error: GROQ_API_KEY missing. Please add it to your Streamlit Secrets."
        if stream:
            def err_gen(): yield msg
            return err_gen()
        return msg

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # DYNAMIC MODEL SWITCHING & MULTIMODAL PAYLOAD
    model = Config.MODEL
    if image_data:
        model = "qwen/qwen3.6-27b"
        stream = False  # Vision requests don't reliably support streaming
        # Deep copy to avoid mutating the caller's message objects
        import copy
        messages = copy.deepcopy(messages)
        # Ensure all messages have plain text content (sanitize older messages)
        for msg in messages:
            if isinstance(msg.get("content"), list):
                texts = [c["text"] for c in msg["content"] if c.get("type") == "text"]
                msg["content"] = " ".join(texts) if texts else ""
        # Reformat the last user message for multimodal input
        if messages and messages[-1]["role"] == "user":
            user_text = messages[-1]["content"]
            messages[-1]["content"] = [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                }
            ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000,
        "stream": stream
    }

    log.debug("=== GROQ REQUEST ===")
    log.debug("MODEL: %s | STREAM: %s", model, stream)
    # Note: Avoid logging the full image data in debug as it's too large
    # log.debug("PAYLOAD:\n%s", json.dumps(payload, indent=2))

    try:
        if stream:
            def stream_generator():
                try:
                    with httpx.Client(timeout=60.0) as client:
                        with client.stream("POST", url, json=payload, headers=headers) as r:
                            if r.status_code != 200:
                                r.read()
                                log.error("=== GROQ STREAM ERROR %s ===\n%s", r.status_code, r.text[:500])
                                yield f"⚠️ API Error ({r.status_code}): {r.text[:300]}"
                                return
                            for line in r.iter_lines():
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        content = data["choices"][0]["delta"].get("content", "")
                                        if content:
                                            yield content
                                    except json.JSONDecodeError:
                                        continue
                except Exception as exc:
                    log.exception("=== STREAM ERROR ===")
                    yield f"\n\n⚠️ Error: {exc}"
            
            # Since Qwen streams thinking tokens inside <think>...</think>,
            # we wrap the generator to strip out thinking tags dynamically.
            def streaming_think_filter(gen):
                in_think = False
                buffer = ""
                for chunk in gen:
                    buffer += chunk
                    while True:
                        if not in_think:
                            # Look for start of thinking tag
                            start_idx = buffer.find("<think>")
                            if start_idx != -1:
                                # Yield everything before the thinking block starts
                                if start_idx > 0:
                                    yield buffer[:start_idx]
                                in_think = True
                                buffer = buffer[start_idx + 7:]
                            else:
                                # No start tag found. Check for partial '<' or '<t' at the end of buffer
                                # to prevent yielding partial tags
                                partial_match = False
                                for i in range(1, min(len(buffer) + 1, 8)):
                                    suffix = buffer[-i:]
                                    if "<think>".startswith(suffix):
                                        partial_match = True
                                        if len(buffer) > i:
                                            yield buffer[:-i]
                                            buffer = suffix
                                        break
                                if not partial_match:
                                    yield buffer
                                    buffer = ""
                                break
                        else:
                            # Inside thinking block, look for end of thinking tag
                            end_idx = buffer.find("</think>")
                            if end_idx != -1:
                                in_think = False
                                buffer = buffer[end_idx + 8:]
                            else:
                                # Still thinking, empty buffer because we discard thinking tokens
                                buffer = ""
                                break
                # Yield any leftover non-thinking text
                if not in_think and buffer:
                    yield buffer

            return streaming_think_filter(stream_generator())
        else:
            import time
            max_retries = 3
            backoff_sec = 2
            for attempt in range(max_retries):
                try:
                    with httpx.Client(timeout=60.0) as client:
                        r = client.post(url, json=payload, headers=headers)
                        if r.status_code == 200:
                            data = r.json()
                            reply = data["choices"][0]["message"]["content"]
                            log.debug("=== GROQ SUCCESS ===")
                            return clean_think_tags(reply)
                        elif r.status_code in [429, 500, 502, 503, 504] and attempt < max_retries - 1:
                            log.warning(f"=== GROQ SERVER ERROR {r.status_code}. Retrying in {backoff_sec}s... (Attempt {attempt+1}/{max_retries}) ===")
                            time.sleep(backoff_sec)
                            backoff_sec *= 2
                        else:
                            log.error("=== GROQ ERROR %s ===\n%s", r.status_code, r.text[:500])
                            return f"⚠️ API Error ({r.status_code}): {r.text[:300]}"
                except Exception as exc:
                    if attempt < max_retries - 1:
                        log.warning(f"=== GROQ REQUEST EXCEPTION {exc}. Retrying in {backoff_sec}s... (Attempt {attempt+1}/{max_retries}) ===")
                        time.sleep(backoff_sec)
                        backoff_sec *= 2
                    else:
                        raise exc
    except Exception as exc:
        log.exception("=== UNEXPECTED ERROR ===")
        msg = f"⚠️ Error: {exc}"
        if stream:
            def err_gen(): yield msg
            return err_gen()
        return msg
