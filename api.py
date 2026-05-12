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
        model = "llama-3.2-11b-vision-preview"
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
        "n": 1,
        "stream": stream
    }

    log.debug("=== GROQ REQUEST ===")
    log.debug("MODEL: %s", model)
    # Note: Avoid logging the full image data in debug as it's too large
    # log.debug("PAYLOAD:\n%s", json.dumps(payload, indent=2))

    try:
        if stream:
            def stream_generator():
                with httpx.Client(timeout=60.0) as client:
                    with client.stream("POST", url, json=payload, headers=headers) as r:
                        r.raise_for_status()
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
            return stream_generator()
        else:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                reply = data["choices"][0]["message"]["content"]
                log.debug("=== GROQ SUCCESS ===")
                return reply
    except httpx.HTTPStatusError as exc:
        err = exc.response.text
        log.error("=== GROQ ERROR %s ===\n%s", exc.response.status_code, err)
        msg = f"API error: {err}"
        if stream:
            def err_gen(): yield msg
            return err_gen()
        return msg
    except Exception as exc:
        log.exception("=== UNEXPECTED ERROR ===")
        msg = f"Error: {exc}"
        if stream:
            def err_gen(): yield msg
            return err_gen()
        return msg
