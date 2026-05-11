"""Test rapide modèles dispo Together AI pour Reading Agent.

Together AI a DeepSeek-V3 et DeepSeek-V3.1 ?
"""
import os
import requests

KEY = os.getenv("TOGETHER_API_KEY", "").strip()

# Candidats à tester (avec tool use natif)
CANDIDATES = [
    "deepseek-ai/DeepSeek-V3.1",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-V3-0324",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "Qwen/Qwen2.5-72B-Instruct-Turbo",
]

for model in CANDIDATES:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply OK in one word."}],
        "max_tokens": 10,
        "temperature": 0,
    }
    try:
        r = requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            content = data["choices"][0]["message"]["content"][:40]
            print(f"✅ {model:<55} → '{content}'")
        else:
            err = r.json().get("error", {}).get("message", "")[:80] if r.text.startswith("{") else r.text[:80]
            print(f"❌ {model:<55} → {r.status_code} : {err}")
    except Exception as e:
        print(f"❌ {model:<55} → {type(e).__name__}: {str(e)[:60]}")
