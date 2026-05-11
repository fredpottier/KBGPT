"""Vérifie support tool use DeepSeek-V3.1 sur Together AI + mesure latence."""
import os, time, json
import requests

KEY = os.getenv("TOGETHER_API_KEY", "").strip()

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather of a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

payload = {
    "model": "deepseek-ai/DeepSeek-V3.1",
    "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
    "tools": TOOLS,
    "tool_choice": "auto",
    "max_tokens": 200,
    "temperature": 0,
}

# Test tool use
t0 = time.time()
r = requests.post(
    "https://api.together.xyz/v1/chat/completions",
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    json=payload,
    timeout=60,
)
elapsed = time.time() - t0
print(f"Status: {r.status_code} ({elapsed:.2f}s)")
if r.status_code == 200:
    data = r.json()
    msg = data["choices"][0]["message"]
    print(f"Content: {msg.get('content')}")
    print(f"Tool calls: {msg.get('tool_calls')}")
    print(f"Usage: {data.get('usage')}")
else:
    print(f"Error: {r.text[:300]}")

# Test latence simple (sans tools) pour comparer
print("\n=== Latence sans tools (3 appels) ===")
for i in range(3):
    t0 = time.time()
    r = requests.post(
        "https://api.together.xyz/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-ai/DeepSeek-V3.1",
            "messages": [{"role": "user", "content": "Count from 1 to 5."}],
            "max_tokens": 50,
            "temperature": 0,
        },
        timeout=60,
    )
    print(f"  Call {i+1}: {time.time()-t0:.2f}s")
