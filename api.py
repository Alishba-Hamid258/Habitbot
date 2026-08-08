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

def call_llm(messages: list[dict], stream: bool = False, image_data: str = None):
    if not Config.GROQ_API_KEY:
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
            return stream_generator()
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
                            return reply
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
