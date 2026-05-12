"""Export gold_set_sap_v1.json questions only (no answers) for EKX testing.

Generates two files :
- gold_set_sap_v1_questions_only.md : human-readable list to copy/paste in EKX
- gold_set_sap_v1_ekx_responses.md   : empty template for EKX answers (one block
                                      per question with placeholder)
Both are usable in any third-party RAG/RAG+KG without contamination.
"""
import json
from pathlib import Path

GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v1.json")
OUT_QUESTIONS = Path("/app/benchmark/questions/gold_set_sap_v1_questions_only.md")
OUT_TEMPLATE = Path("/app/benchmark/questions/gold_set_sap_v1_ekx_responses.md")

data = json.loads(GOLDSET.read_text(encoding="utf-8"))

# 1. Plain question list (for copy-paste into EKX)
lines = ["# Gold-set SAP PCE — Questions (à tester chez EKX)\n",
         "Pose chaque question, copie la réponse EKX dans le 2e fichier.\n\n"]
for q in data:
    lines.append(f"## {q['id']} [{q['primary_type']}]\n")
    lines.append(f"{q['question']}\n\n")

OUT_QUESTIONS.write_text("".join(lines), encoding="utf-8")
print(f"✓ Questions: {OUT_QUESTIONS} ({len(data)} questions)")

# 2. Template for EKX responses
tmpl = ["# Gold-set SAP PCE — Réponses EKX (template)\n",
        "Pour chaque question, colle la réponse EKX dans le bloc correspondant.\n",
        "Garde le format ```answer ... ``` pour faciliter le parse.\n\n"]
for q in data:
    tmpl.append(f"## {q['id']} [{q['primary_type']}]\n")
    tmpl.append(f"**Q:** {q['question']}\n\n")
    tmpl.append("```answer\n")
    tmpl.append("<COLLER ici la réponse EKX intégrale>\n")
    tmpl.append("```\n\n")
    tmpl.append("---\n\n")

OUT_TEMPLATE.write_text("".join(tmpl), encoding="utf-8")
print(f"✓ Template EKX: {OUT_TEMPLATE}")
