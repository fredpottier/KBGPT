#!/usr/bin/env python
"""
p1_4b0_schema_granularity.py — P1.4b-0 : valider le PARI CENTRAL de la refonte sur le
LLM EXACT de ré-ingestion (Qwen2.5-14B-Instruct-AWQ, vLLM burst g6), avec guided
decoding XGrammar réel.

Question : donner au LLM un schéma où l'énumération est un CHAMP `objects[]` le fait-il
produire 1 claim-liste pour une énumération (au lieu de N claims) — là où un schéma plat
`{subject,predicate,object}` sur-décompose ? Et le schéma liste évite-t-il de sur-fusionner
des prédicats distincts / des sujets coordonnés ?

A/B : même passages, schéma FLAT vs schéma LIST, sous guided decoding (XGrammar via vLLM).
Domain-agnostic (passages SAP + médical + aerospace + générique).

Lit l'URL vLLM burst depuis data/.burst_state.json (vllm_url).

Usage (une fois le burst /health OK) :
    docker compose exec app python scripts/p1_4b0_schema_granularity.py
    python app/scripts/p1_4b0_schema_granularity.py   # depuis l'hôte si openai+env dispo
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"

# (passage, type, attendu)
PASSAGES = [
    ("Master Data Governance is available for Custom Objects, Financials, Supplier, "
     "Customer, and Material domains.", "enumeration", "1 claim, objects=[5]"),
    ("The vaccine protects against measles, mumps, and rubella.",
     "enumeration", "1 claim, objects=[3]"),
    ("The engine weighs 500 kilograms, runs on kerosene, and produces 20 kilonewtons "
     "of thrust.", "multi_predicate", "~3 claims (prédicats distincts)"),
    ("The pilot and the copilot must verify the landing gear before takeoff.",
     "coordinated_subjects", "1 claim (PAS objects=[pilot,copilot])"),
]

FLAT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "predicate", "object"],
            },
        }
    },
    "required": ["claims"],
}

LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "objects": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["subject", "predicate", "objects"],
            },
        }
    },
    "required": ["claims"],
}

FLAT_INSTR = (
    "Extract the atomic factual claims from the passage as JSON. "
    "Each claim is a (subject, predicate, object) triple."
)
LIST_INSTR = (
    "Extract the factual claims from the passage as JSON. Each claim is "
    "(subject, predicate, objects[]). RULE: when several items share the SAME subject "
    "and predicate (an enumeration), emit ONE claim whose `objects` lists all items — "
    "do NOT create one claim per item. When facts have DIFFERENT predicates, emit "
    "separate claims. Do not put coordinated subjects into `objects`.\n"
    "Examples:\n"
    "- \"The kit includes a cable, a charger, and a manual.\" -> "
    "{\"subject\":\"The kit\",\"predicate\":\"includes\",\"objects\":[\"a cable\",\"a charger\",\"a manual\"]}\n"
    "- \"The device is waterproof and weighs 200 g.\" -> two claims (different predicates)."
)


def get_vllm_url() -> str:
    for fn in ("data/.burst_state.json", "data/.burst_info.json"):
        p = ROOT / fn
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            url = d.get("vllm_url")
            if url:
                return url.rstrip("/") + "/v1"
    env = os.getenv("V5_VLLM_URL") or os.getenv("VLLM_URL")
    if env:
        return env.rstrip("/") + "/v1"
    raise SystemExit("URL vLLM burst introuvable (data/.burst_state.json absent).")


def call(client, instr: str, schema: dict, passage: str) -> dict:
    """Appel vLLM avec guided decoding (XGrammar). Fallbacks robustes."""
    messages = [
        {"role": "system", "content": instr},
        {"role": "user", "content": f"Passage:\n\"\"\"{passage}\"\"\"\nJSON:"},
    ]
    # 1) response_format json_schema (vLLM récent)
    try:
        r = client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.0, max_tokens=400,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "claims", "schema": schema}},
        )
        return json.loads(r.choices[0].message.content), "json_schema"
    except Exception:
        pass
    # 2) extra_body guided_json (XGrammar)
    try:
        r = client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.0, max_tokens=400,
            extra_body={"guided_json": schema, "guided_decoding_backend": "xgrammar"},
        )
        return json.loads(r.choices[0].message.content), "guided_json"
    except Exception:
        pass
    # 3) json_object + schéma en prompt
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": instr + "\nReturn JSON matching: "
                   + json.dumps(schema)},
                  messages[1]],
        temperature=0.0, max_tokens=400,
        response_format={"type": "json_object"},
    )
    return json.loads(r.choices[0].message.content), "json_object"


def main() -> None:
    from openai import OpenAI

    url = get_vllm_url()
    print(f"vLLM burst: {url} | model: {MODEL}\n")
    client = OpenAI(base_url=url, api_key="EMPTY", timeout=120.0)

    print("=" * 100)
    for passage, ptype, expected in PASSAGES:
        print(f"\n### [{ptype}] {passage[:80]}")
        print(f"    attendu: {expected}")
        for label, instr, schema in (("FLAT", FLAT_INSTR, FLAT_SCHEMA),
                                     ("LIST", LIST_INSTR, LIST_SCHEMA)):
            try:
                data, mode = call(client, instr, schema, passage)
                claims = data.get("claims", [])
                n = len(claims)
                if label == "LIST":
                    detail = "; ".join(
                        f"{c.get('subject','?')[:20]}|{c.get('predicate','?')[:14]}|obj={len(c.get('objects',[]))}"
                        for c in claims[:4])
                else:
                    detail = "; ".join(
                        f"{c.get('subject','?')[:20]}|{c.get('predicate','?')[:14]}|{c.get('object','?')[:20]}"
                        for c in claims[:6])
                print(f"    {label:<4} [{mode:<11}] -> {n} claim(s) | {detail}")
            except Exception as exc:
                print(f"    {label:<4} -> ERREUR: {str(exc)[:120]}")
    print("\n" + "=" * 100)
    print("Lecture : pour une ENUMERATION, LIST doit donner 1 claim (objects=N) et FLAT N claims.")
    print("Pour MULTI_PREDICATE : ~3 claims dans les 2 (prédicats distincts).")
    print("Pour COORDINATED_SUBJECTS : 1 claim, objects ne doit PAS = [pilot, copilot].")


if __name__ == "__main__":
    main()
