"""Test : le 14B a flagué des fratries d'énumération comme CONTRADICTS (faux positifs).
Rejoue les MÊMES paires sur Qwen3-235B (DeepInfra, bypass burst) avec le MÊME prompt NLI,
pour voir si le modèle plus fort suit correctement les règles (→ NONE attendu).
"""
from __future__ import annotations
import json
import os

from openai import OpenAI
from knowbase.relations.nli_adjudicator import NLI_PROMPT

MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

# Paires que le 14B a classées CONTRADICTS conf=1.0 (toutes = faux positifs attendus NONE),
# + 1 cas ambigu (file name) en contrôle.
PAIRS = [
    ("HR payroll FR", "Social declaration GIP-MDS (net-entreprises.fr) has the following service consumer: CO_HRPAYFR_WSP3112_CRMHTTP_OPS.",
     "HR payroll FR", "Social declaration GIP-MDS (net-entreprises.fr) has the following service consumer: CO_HRPAYFR_WSP3114_CRMHTTP_OPS."),
    ("SLL backend", "Assigning business catalog SAP_SLL_BC_PI_MM_DOC_TRANS assigns the business catalog SAP_CMD_BC_CUSTOMER_DSP in the same backend role.",
     "SLL backend", "Assigning business catalog SAP_SLL_BC_PI_MM_DOC_TRANS assigns the business catalog SAP_CMD_BC_PRODUCT_DSP in the same backend role."),
    ("SLL backend", "Assigning the business catalog SAP_SLL_BC_PI_PREF_TRANS in the backend role also assigns the business catalog SAP_CMD_BC_CUSTOMER_DSP in the same backend role.",
     "SLL backend", "Assigning the business catalog SAP_SLL_BC_PI_PREF_TRANS in the backend role also assigns the business catalog SAP_CMD_BC_PRODUCT_DSP in the same backend role."),
    ("SLL backend", "Assigning business catalog SAP_SLL_BC_PI_MM_DOC_TRANS assigns the business catalog SAP_CMD_BC_CUSTOMER_DSP in the same backend role.",
     "SLL backend", "Assigning business catalog SAP_SLL_BC_PI_MM_DOC_TRANS assigns the business catalog SAP_CMD_BC_SUPPLIER_DSP in the same backend role."),
    ("HR CZ", "HR_CZ_DIR_DOWNLOAD has the logical file name RPCZIPT0.",
     "HR CZ", "HR_CZ_DIR_DOWNLOAD has the logical file name RPCZPLT0."),
]


def main() -> None:
    client = OpenAI(api_key=os.getenv("DEEPINFRA_API_KEY", ""),
                    base_url="https://api.deepinfra.com/v1/openai")
    print(f"=== Adjudication test sur {MODEL} (14B avait sorti CONTRADICTS conf=1.0 partout) ===\n")
    for i, (da, ta, db, tb) in enumerate(PAIRS, 1):
        prompt = NLI_PROMPT.format(doc_a=da, text_a=ta, doc_b=db, text_b=tb)
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=350,
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            print(f"[{i}] {ta[-45:]}  vs  {tb[-45:]}")
            print(f"    → 235B: relation={data.get('relation')} conf={data.get('confidence')} | {data.get('reasoning','')[:120]}\n")
        except Exception as e:
            print(f"[{i}] ERREUR: {str(e)[:160]}\n")


if __name__ == "__main__":
    main()
