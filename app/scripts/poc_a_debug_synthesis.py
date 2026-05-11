"""Debug : tester si Together AI répond à la forced synthesis sans tools."""
import sys, os
sys.path.insert(0, "/app/src")
import requests

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()

# Test 1: appel simple sans tools (la forced synthesis a tools=[])
print("=== Test 1: tools=[] explicite ===")
payload = {
    "model": "deepseek-ai/DeepSeek-V3.1",
    "messages": [{"role": "user", "content": "Say hello in one sentence."}],
    "tools": [],
    "tool_choice": "auto",
    "max_tokens": 200,
    "temperature": 0,
}
r = requests.post(
    "https://api.together.xyz/v1/chat/completions",
    headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
    json=payload,
    timeout=60,
)
print(f"Status: {r.status_code}")
data = r.json()
msg = data.get("choices", [{}])[0].get("message", {})
print(f"Content: '{msg.get('content', '')}'")
print(f"Tool calls: {msg.get('tool_calls')}")
print(f"Reasoning: {msg.get('reasoning_content')}")
print(f"Usage: {data.get('usage')}")

# Test 2: sans clé tools du tout
print("\n=== Test 2: sans clé tools du tout ===")
payload = {
    "model": "deepseek-ai/DeepSeek-V3.1",
    "messages": [{"role": "user", "content": "Say hello in one sentence."}],
    "max_tokens": 200,
    "temperature": 0,
}
r = requests.post(
    "https://api.together.xyz/v1/chat/completions",
    headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
    json=payload,
    timeout=60,
)
data = r.json()
msg = data.get("choices", [{}])[0].get("message", {})
print(f"Content: '{msg.get('content', '')}'")

# Test 3: simulation forced synthesis avec history simulée
print("\n=== Test 3: forced synthesis avec messages history + tools=[] ===")
fake_history = [
    {"role": "system", "content": "You are a research agent. Use tools then conclude."},
    {"role": "user", "content": "What is in Article 5?"},
    {"role": "assistant", "content": "", "tool_calls": [{
        "id": "call_xx",
        "type": "function",
        "function": {"name": "read", "arguments": '{"doc_id": "test", "section_path_or_numbering": "Article 5"}'},
    }]},
    {"role": "tool", "tool_call_id": "call_xx", "content": '{"text": "Article 5 says X about cyber-surveillance"}'},
    {"role": "user", "content": "Reached max iterations. Now produce final answer. Do not call any tool."}
]
payload = {
    "model": "deepseek-ai/DeepSeek-V3.1",
    "messages": fake_history,
    "tools": [],
    "max_tokens": 500,
    "temperature": 0,
}
r = requests.post(
    "https://api.together.xyz/v1/chat/completions",
    headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
    json=payload,
    timeout=60,
)
print(f"Status: {r.status_code}")
data = r.json()
msg = data.get("choices", [{}])[0].get("message", {})
print(f"Content: '{msg.get('content', '')[:300]}'")
print(f"Tool calls: {msg.get('tool_calls')}")
print(f"Usage: {data.get('usage')}")
