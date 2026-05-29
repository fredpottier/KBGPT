"""P1.3.5 — comparaison de la qualité d'extraction entre modèles.

Lance le prompt d'extraction révisé (décontextualisation + question-guided +
open-predicate) sur le set multi-corpus et compare plusieurs (provider, modèle)
côte à côte. Sert à valider que le Qwen2.5-72B (EC2 g6e/L40S) atteint le niveau
de DeepSeek-V3.1 avant de ré-ingérer.

Métriques par modèle :
  - n_claims        : total claims extraits (rappel brut — le 14B sous-extrait)
  - n_procedural    : claims PROCEDURAL détectés
  - qual_rate       : % claims avec ≥1 qualifier
  - grounded_rate   : % qualifiers ancrés dans le verbatim
  - n_open_pred     : claims avec prédicat libre (open_predicate)
  - decontext_ok    : % claims sans anaphore de tête évidente (proxy #1)

Référence 14B (mesurée 25/05 sur ce set) : 6 claims, 0 procedural, qual 100%.

Usage :
    # Compare le endpoint vLLM courant (72B une fois déployé) vs DeepSeek-V3.1
    V5_VLLM_URL=http://<ip>:8000 V5_VLLM_MODEL=Qwen/Qwen2.5-72B-Instruct-AWQ \
      python app/scripts/p1_extraction_model_compare.py

    # DeepSeek seul
    python app/scripts/p1_extraction_model_compare.py --only deepinfra
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Réutilise le harnais P1.2 (set de validation + helpers)
from scripts.p1_2_validate_qualifiers import (  # noqa: E402
    VALIDATION_UNITS,
    _make_client,
    _call_llm,
    _parse_claims_json,
    _is_grounded,
)
from knowbase.claimfirst.extractors.claim_extractor import (  # noqa: E402
    ClaimExtractor,
    build_claim_extraction_prompt,
)

# Anaphores de tête (proxy décontextualisation #1) — début de claim suspect
_LEADING_ANAPHORA = re.compile(
    r"^\s*(it|this|that|they|these|those|the system|the latter|the former|he|she)\b",
    re.IGNORECASE,
)


def run_for_model(client, model: str, label: str) -> Dict[str, Any]:
    n_claims = n_proc = n_qual = n_qtotal = n_grounded = n_open = n_decontext_bad = 0
    errors = 0
    for u in VALIDATION_UNITS:
        prompt = build_claim_extraction_prompt(
            units_text=f"U1: {u['text']}",
            doc_title=u["doc_title"],
            doc_type=u["doc_type"],
        )
        try:
            raw = _call_llm(client, model, prompt)
        except Exception as exc:  # pragma: no cover
            print(f"  [{u['domain']}] ERREUR LLM: {exc}")
            errors += 1
            continue
        for c in _parse_claims_json(raw):
            n_claims += 1
            text = str(c.get("claim_text", ""))
            if _LEADING_ANAPHORA.match(text):
                n_decontext_bad += 1
            if str(c.get("claim_type", "")).upper() == "PROCEDURAL":
                n_proc += 1
            sf = c.get("structured_form")
            if isinstance(sf, dict) and sf.get("open_predicate"):
                n_open += 1
            quals = ClaimExtractor._parse_qualifiers(c.get("qualifiers"))
            if quals:
                n_qual += 1
            for q in quals:
                n_qtotal += 1
                if _is_grounded(q.value, u["text"]):
                    n_grounded += 1
    return {
        "label": label,
        "model": model,
        "n_claims": n_claims,
        "n_procedural": n_proc,
        "qual_rate": (n_qual / n_claims) if n_claims else 0.0,
        "grounded_rate": (n_grounded / n_qtotal) if n_qtotal else 0.0,
        "n_open_pred": n_open,
        "decontext_ok": 1.0 - (n_decontext_bad / n_claims) if n_claims else 1.0,
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["deepinfra", "vllm"], default=None,
                    help="Limiter à un seul provider")
    ap.add_argument("--deepseek-model", default="deepseek-ai/DeepSeek-V3.1")
    args = ap.parse_args()

    configs = []
    if args.only in (None, "vllm"):
        if os.getenv("V5_VLLM_URL") or os.getenv("VLLM_URL"):
            client, model, label = _make_client("vllm")
            configs.append((client, model, f"vLLM/{model.split('/')[-1]}"))
        elif args.only == "vllm":
            raise SystemExit("V5_VLLM_URL non positionné — endpoint vLLM introuvable.")
    if args.only in (None, "deepinfra"):
        client, _, _ = _make_client("deepinfra")
        configs.append((client, args.deepseek_model, "DeepInfra/DeepSeek-V3.1"))

    if not configs:
        raise SystemExit("Aucun modèle à comparer (positionner V5_VLLM_URL ou --only deepinfra).")

    print("=== P1.3.5 — comparaison extraction multi-modèles (prompt révisé) ===\n")
    results: List[Dict[str, Any]] = []
    for client, model, label in configs:
        print(f"-- {label} --")
        results.append(run_for_model(client, model, label))

    # Référence 14B (mesure 25/05, prompt qualifiers de base — indicatif)
    ref_14b = {
        "label": "vLLM/Qwen2.5-14B (réf 25/05)", "model": "Qwen2.5-14B-Instruct-AWQ",
        "n_claims": 6, "n_procedural": 0, "qual_rate": 1.0, "grounded_rate": 1.0,
        "n_open_pred": 0, "decontext_ok": float("nan"), "errors": 0,
    }

    rows = results + [ref_14b]
    print("\n" + "=" * 92)
    hdr = f"{'Modèle':<34}{'claims':>7}{'proc':>6}{'qual%':>7}{'grnd%':>7}{'open':>6}{'dectx%':>8}"
    print(hdr)
    print("-" * 92)
    for r in rows:
        dectx = "n/a" if r["decontext_ok"] != r["decontext_ok"] else f"{r['decontext_ok']*100:.0f}"
        print(f"{r['label']:<34}{r['n_claims']:>7}{r['n_procedural']:>6}"
              f"{r['qual_rate']*100:>6.0f}%{r['grounded_rate']*100:>6.0f}%"
              f"{r['n_open_pred']:>6}{dectx:>7}%")

    # Verdict 72B vs DeepSeek
    vllm = next((r for r in results if r["label"].startswith("vLLM")), None)
    ds = next((r for r in results if "DeepSeek" in r["label"]), None)
    if vllm and ds:
        print("\n--- Verdict 72B vs DeepSeek ---")
        ratio = vllm["n_claims"] / ds["n_claims"] if ds["n_claims"] else 0
        print(f"Rappel claims : {vllm['n_claims']} (72B) vs {ds['n_claims']} (DeepSeek) "
              f"= {ratio:.0%} du rappel DeepSeek")
        if ratio >= 0.85 and vllm["n_procedural"] >= 1:
            print("✅ Le 72B atteint ~le niveau DeepSeek (et détecte le procédural) "
                  "→ OK comme modèle de ré-ingestion.")
        elif ratio >= 0.7:
            print("🟡 Le 72B est proche mais en-dessous → vérifier les claims manqués.")
        else:
            print("🛑 Le 72B sous-extrait nettement → revoir prompt/params avant ré-ingestion.")


if __name__ == "__main__":
    main()
