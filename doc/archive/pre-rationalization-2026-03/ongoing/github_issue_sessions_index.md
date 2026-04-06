## Additional data: `sessions-index.json` stops being updated

**Environment:**
- Claude Code 2.1.42 (stable)
- Windows 11 Pro 10.0.26200
- Issue started: February 15, 2026

### Observation

I noticed that `/resume` couldn't find my recent sessions. I compared sessions on disk vs sessions registered in the index and found a discrepancy:

```
Sessions on disk:  118
Sessions in index: 87

LAST 15 sessions on disk (sorted by mtime):
2026-02-14 22:46 | 318148cd | 1,478KB | IN INDEX
2026-02-15 09:21 | 5d158395 |     5KB | *** MISSING ***
2026-02-15 11:38 | a22bc060 |   526KB | IN INDEX
2026-02-15 11:38 | bf049b7b |   396KB | IN INDEX
2026-02-15 11:38 | c1d91bfa |   454KB | IN INDEX
2026-02-15 11:38 | 0435bc47 |    73KB | IN INDEX
2026-02-15 12:25 | 1d003a66 |   611KB | IN INDEX
2026-02-15 13:13 | 66d486cc |   365KB | *** MISSING ***
2026-02-16 00:08 | 9546067c |19,803KB | *** MISSING ***
2026-02-16 07:48 | 621e03cb |    18KB | *** MISSING ***
2026-02-16 08:03 | 90a2c3f3 | 5,187KB | IN INDEX (created before the issue)
```

### Facts

- `sessions-index.json` was last modified on **Feb 15 at 13:08**
- 4 sessions created after that timestamp exist on disk but are missing from the index
- These sessions are invisible to `/resume` despite being fully intact on disk
- One of them (`9546067c`, 20MB) represents several hours of work

### Additional finding: manually adding entries doesn't fix `/resume`

I tried manually adding the missing sessions to `sessions-index.json` with the correct structure (identical keys: `sessionId`, `fullPath`, `fileMtime`, `firstPrompt`, `summary`, `messageCount`, `created`, `modified`, `gitBranch`, `projectPath`, `isSidechain`). The entries were successfully added and the JSON file validates correctly (118 entries, all keys matching existing entries).

However, **`/resume` still doesn't show the added sessions**, even after restarting Claude Code in a new terminal. The file was not overwritten by Claude Code on restart (still shows our modifications with correct timestamp).

This suggests that either:
- `/resume` does not read `sessions-index.json` directly (or uses it only as a cache that gets regenerated from another source)
- There is an additional mechanism or secondary index that controls which sessions appear in the picker
- The index file may be read only once at some initialization point and cached in memory differently

### Possible investigation leads

- The index file stopped being updated at a specific point in time — something may have caused writes to `sessions-index.json` to silently fail from that point on
- I notice that at `2026-02-15 11:38`, 4 sessions were created almost simultaneously — could be worth checking if concurrent index writes are properly handled
- The 31 other missing sessions (118 on disk vs 87 in index) suggest this may have happened before as well, or that some session types are never indexed
- Manually patching the index file does not restore visibility in `/resume` — the picker seems to rely on something else than (or in addition to) this file

### Diagnostic scripts

**Script 1 — Compare disk vs index** (adapt `<PROJECT>` to your project path):

```python
import json, os, datetime

index_path = os.path.expanduser("~/.claude/projects/<PROJECT>/sessions-index.json")
sessions_dir = os.path.dirname(index_path)

with open(index_path, encoding="utf-8") as f:
    indexed_ids = {e["sessionId"] for e in json.load(f).get("entries", [])}

for f in sorted(os.listdir(sessions_dir)):
    if not f.endswith(".jsonl"):
        continue
    sid = f.replace(".jsonl", "")
    fpath = os.path.join(sessions_dir, f)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
    size = os.path.getsize(fpath) // 1024
    status = "OK" if sid in indexed_ids else "*** MISSING ***"
    print(f"{mtime:%Y-%m-%d %H:%M} | {sid[:12]} | {size:>6}KB | {status}")
```

**Script 2 — Add missing sessions to index** (attempted fix, did not restore `/resume` visibility):

```python
import json, os, datetime, shutil

index_path = os.path.expanduser("~/.claude/projects/<PROJECT>/sessions-index.json")
sessions_dir = os.path.dirname(index_path)

shutil.copy2(index_path, index_path + ".bak")

with open(index_path, encoding="utf-8") as f:
    data = json.load(f)

indexed_ids = {e["sessionId"] for e in data.get("entries", [])}

for fname in os.listdir(sessions_dir):
    if not fname.endswith(".jsonl"):
        continue
    sid = fname.replace(".jsonl", "")
    if sid in indexed_ids:
        continue
    fpath = os.path.join(sessions_dir, fname)
    if os.path.getsize(fpath) == 0:
        continue
    mtime = os.path.getmtime(fpath)
    ctime = os.path.getctime(fpath)
    # Parse first user prompt
    first_prompt = "No prompt"
    msg_count = 0
    try:
        with open(fpath, encoding="utf-8") as sf:
            for line in sf:
                try:
                    msg = json.loads(line.strip())
                    if msg.get("type") in ("user", "assistant"):
                        msg_count += 1
                        if first_prompt == "No prompt" and msg.get("type") == "user":
                            content = msg.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        txt = c.get("text", "")
                                        if txt and not txt.startswith("[Request"):
                                            first_prompt = txt[:200]
                                            break
                except json.JSONDecodeError:
                    continue
    except Exception:
        continue
    data["entries"].append({
        "sessionId": sid,
        "fullPath": fpath,
        "fileMtime": int(mtime * 1000),
        "firstPrompt": first_prompt,
        "summary": "",
        "messageCount": msg_count,
        "created": datetime.datetime.fromtimestamp(ctime).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "modified": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "gitBranch": "main",
        "projectPath": "<YOUR_PROJECT_PATH>",
        "isSidechain": False,
    })

with open(index_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```
