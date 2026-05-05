"""
Bench latence + qualité de plusieurs modèles DeepInfra sur une tâche
NLI/faithfulness-judge représentative. Pour CH-33 : décider du modèle
de routage des couches vérification.

Mesure pour chaque modèle :
- elapsed_s (wallclock du chat_completion)
- output_tokens (tokens générés)
- tokens_per_sec
- json_valid (le JSON parse-t-il ?)
- verdict (correct = PARTIAL ou UNFAITHFUL avec ≥1 claim UNSUPPORTED)
- output_excerpt
"""
import io
import json
import os
import sys
import time

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")
if not DEEPINFRA_API_KEY:
    # Try to read from .env
    env_path = r"C:/Projects/SAP_KB/.env"
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            if line.startswith("DEEPINFRA_API_KEY="):
                DEEPINFRA_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
assert DEEPINFRA_API_KEY, "DEEPINFRA_API_KEY missing"

BASE_URL = "https://api.deepinfra.com/v1/openai"

MODELS = [
    "Qwen/Qwen2.5-72B-Instruct",  # baseline actuelle
    "Qwen/Qwen3-235B-A22B-Instruct-2507",  # MoE (utilisé par decomposer)
    "meta-llama/Llama-3.3-70B-Instruct",
    "Qwen/Qwen2.5-14B-Instruct",
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
]

# Prompt = faithfulness judge sur le cas réel observé (T6 fausse prémisse)
SYSTEM_PROMPT = """You are a faithfulness judge for a domain-agnostic RAG system.

Given a generated ANSWER and the EVIDENCE that was retrieved, your job is to:
1. Decompose the answer into atomic factual claims (each a single, verifiable statement).
2. For each atomic claim, judge whether it is SUPPORTED by the evidence.

Definitions:
- SUPPORTED = the claim is explicitly stated or strongly implied by at least one evidence passage.
- UNSUPPORTED = the claim is not present in the evidence (the LLM may have invented it).
- NEUTRAL = the claim is a generic/non-factual statement (a definition, a connector,
  a meta-comment), not a factual assertion to verify.

Rules:
1. Be DOMAIN-AGNOSTIC.
2. Numerical values, dates, identifiers must match the evidence exactly to be SUPPORTED.
3. Citation tokens like [doc=xxx] are NOT factual claims to verify.

OUTPUT — STRICT JSON ONLY:
{
  "atomic_claims": [
    {"claim": "<atomic statement>", "verdict": "SUPPORTED"|"UNSUPPORTED"|"NEUTRAL", "confidence": 0.0..1.0, "reasoning": "short"}
  ],
  "overall_faithfulness": 0.0..1.0,
  "overall_verdict": "FAITHFUL"|"PARTIAL"|"UNFAITHFUL"
}
"""

USER_PROMPT = """EVIDENCE (id-referenced):
[1] doc=dualuse_reg_2021_821_original_65eef5dc Regulation (EU) 2021/821 establishes a Union regime for the control of exports, brokering, technical assistance, transit and transfer of dual-use items.
[2] doc=dualuse_reg_2021_821_original_65eef5dc Member States may, in cases where exports of dual-use items not listed in Annex I might be of concern, require an authorisation under Article 4.
[3] doc=dualuse_del_2023_996_3616a044 The list of items in Annex I is updated to reflect changes adopted by international non-proliferation regimes and export control arrangements.
[4] doc=dualuse_del_2024_2547_cb08f84b Annex I to Regulation (EU) 2021/821 is replaced by the text in the Annex to this Regulation.
[5] doc=dualuse_del_2023_66_cdc2b691 Member States cooperate with the Commission to ensure consistency in the application of export controls.

ANSWER:
Le règlement (UE) 2021/821 interdit toute exportation de produits à double usage vers les pays tiers afin de se conformer aux régimes internationaux de non-prolifération [doc=dualuse_del_2023_66_cdc2b691; doc=dualuse_del_2024_2547_cb08f84b]. Cette mesure vise à faciliter les références pour les autorités de contrôle des exportations en remplaçant l'Annexe I.

Decompose the answer into atomic claims and judge each. Return JSON only."""


def call_model(model: str, max_tokens: int = 900, timeout: float = 180.0) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {DEEPINFRA_API_KEY}",
        "Content-Type": "application/json",
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {
            "model": model,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_s": round(time.time() - t0, 2),
        }
    elapsed = round(time.time() - t0, 2)
    choice = data["choices"][0]
    content = choice["message"]["content"] or ""
    usage = data.get("usage", {})
    in_toks = usage.get("prompt_tokens", 0)
    out_toks = usage.get("completion_tokens", 0)
    tps = round(out_toks / elapsed, 1) if elapsed > 0 else 0

    json_valid = False
    parsed = None
    try:
        # Some models wrap with markdown
        import re
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            parsed = json.loads(m.group())
            json_valid = True
    except Exception:
        pass

    n_supported = 0
    n_unsupported = 0
    n_neutral = 0
    flagged_premise = False
    if parsed:
        for ac in parsed.get("atomic_claims", []) or []:
            v = (ac.get("verdict") or "").upper()
            if v == "SUPPORTED":
                n_supported += 1
            elif v == "UNSUPPORTED":
                n_unsupported += 1
                if "interdi" in (ac.get("claim") or "").lower():
                    flagged_premise = True
            elif v == "NEUTRAL":
                n_neutral += 1
        overall_v = parsed.get("overall_verdict", "?")
    else:
        overall_v = "?"

    return {
        "model": model,
        "elapsed_s": elapsed,
        "in_tokens": in_toks,
        "out_tokens": out_toks,
        "tokens_per_sec": tps,
        "json_valid": json_valid,
        "n_supported": n_supported,
        "n_unsupported": n_unsupported,
        "n_neutral": n_neutral,
        "flagged_false_premise": flagged_premise,
        "overall_verdict": overall_v,
        "content_excerpt": content[:300],
    }


def main():
    print("Bench latence + qualité — faithfulness judge prompt sur cas T6 fausse prémisse")
    print(f"Expected behavior: PARTIAL ou UNFAITHFUL avec ≥1 UNSUPPORTED (le claim 'interdit toute exportation' doit être flagué)\n")

    results = []
    for model in MODELS:
        print(f"--> {model}", flush=True)
        r = call_model(model)
        if "error" in r:
            print(f"    ERROR: {r['error']}  ({r['elapsed_s']}s)", flush=True)
        else:
            print(
                f"    elapsed={r['elapsed_s']}s  out={r['out_tokens']} tok  tps={r['tokens_per_sec']}  "
                f"json={r['json_valid']}  verdict={r['overall_verdict']}  "
                f"S/U/N={r['n_supported']}/{r['n_unsupported']}/{r['n_neutral']}  "
                f"flagged_premise={r['flagged_false_premise']}",
                flush=True,
            )
        results.append(r)
        print(flush=True)

    # Tableau récap
    print("\n" + "=" * 110)
    print("RECAP")
    print("=" * 110)
    header = f"{'Model':<55} {'elapsed':>8} {'tps':>6} {'json':>5} {'verdict':>10} {'S/U/N':>10} {'fp':>4}"
    print(header)
    print("-" * 110)
    for r in results:
        if "error" in r:
            print(f"{r['model']:<55} ERROR: {r['error'][:50]}")
            continue
        print(
            f"{r['model']:<55} {r['elapsed_s']:>7.2f}s {r['tokens_per_sec']:>6.0f} "
            f"{'Y' if r['json_valid'] else 'N':>5} {r['overall_verdict']:>10} "
            f"{r['n_supported']}/{r['n_unsupported']}/{r['n_neutral']:>4} "
            f"{'Y' if r['flagged_false_premise'] else 'N':>4}"
        )

    out_path = r"C:/Projects/SAP_KB/benchmark/bench_models_latency.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
