#!/usr/bin/env python3
import sys
FILEPATH = r"C:\Projects\SAP_KB\src\knowbase\ingestion\hybrid_anchor_chunker.py"
content = sys.stdin.read()
with open(FILEPATH, 'w', encoding='utf-8') as f:
    f.write(content)
print(f"Written {len(content)} chars to {FILEPATH}")
