"""Fix missing sessions in sessions-index.json"""
import json, os, datetime, shutil

index_path = os.path.expanduser(
    "~/.claude/projects/C--Projects-SAP-KB/sessions-index.json"
)
sessions_dir = os.path.dirname(index_path)

# Backup
backup_path = index_path + ".bak"
shutil.copy2(index_path, backup_path)
print(f"Backup: {backup_path}")

with open(index_path, encoding="utf-8") as f:
    data = json.load(f)

indexed_ids = {e["sessionId"] for e in data.get("entries", [])}
added = 0

for fname in os.listdir(sessions_dir):
    if not fname.endswith(".jsonl"):
        continue
    sid = fname.replace(".jsonl", "")
    if sid in indexed_ids:
        continue

    fpath = os.path.join(sessions_dir, fname)
    size = os.path.getsize(fpath)

    if size == 0:
        continue

    mtime = os.path.getmtime(fpath)
    ctime = os.path.getctime(fpath)

    # Lire le premier message utilisateur et compter les messages
    first_prompt = "No prompt"
    message_count = 0
    try:
        with open(fpath, encoding="utf-8") as sf:
            for line in sf:
                try:
                    msg = json.loads(line.strip())
                    msg_type = msg.get("type", "")
                    msg_role = msg.get("role", "")
                    if msg_type in ("human", "assistant") or msg_role in ("user", "assistant"):
                        message_count += 1
                        if first_prompt == "No prompt" and (msg_type == "human" or msg_role == "user"):
                            content = msg.get("message", {}).get("content", "") or msg.get("content", "")
                            if isinstance(content, list):
                                content = content[0].get("text", "") if content else ""
                            first_prompt = str(content)[:200]
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Warning reading {sid[:12]}: {e}")

    win_path = fpath.replace("/", "\\")
    entry = {
        "sessionId": sid,
        "fullPath": win_path,
        "fileMtime": int(mtime * 1000),
        "firstPrompt": first_prompt,
        "summary": "",
        "messageCount": message_count,
        "created": datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "modified": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "gitBranch": "main",
        "projectPath": "C:\\Projects\\SAP_KB",
        "isSidechain": False,
    }
    data["entries"].append(entry)
    added += 1
    dt = datetime.datetime.fromtimestamp(mtime)
    print(f"  Added: {dt:%Y-%m-%d %H:%M} | {sid[:12]} | {size//1024}KB | msgs={message_count}")

with open(index_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\nDone: {added} sessions added to index")
print(f"Total entries now: {len(data['entries'])}")
