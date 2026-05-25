"""P1.2-validation — valide le prompt qualifiers (Phase B) sur un set multi-corpus.

Mesure, pour un LLM donné, la capacité du prompt d'extraction enrichi à produire
des qualifiers structurés (temporal/spatial/version/condition/scope_limit) ancrés
dans le texte source.

Set de validation domain-agnostic (ADR_PHASE_B §5/§7) : SAP technique, SAP
procédural, médical, juridique, aéronautique. Chaque unité contient au moins une
condition d'applicabilité extractible.

Métriques :
  - claims_with_qualifiers_rate : % de claims portant ≥1 qualifier (gate P1.2 ≥30%)
  - grounded_rate : % de qualifiers dont la valeur est ancrée dans l'unité source
  - type_distribution : répartition par QualifierType
  - quality_score = grounded_rate (proxy P1.2-validation ≥80%)

STOP rule (ADR §7) : si claims_with_qualifiers_rate < 20% → prompt à revoir
AVANT ré-ingestion (ne pas brûler l'EC2 Burst sur une extraction défaillante).

Usage :
    # DeepInfra (dispo maintenant, coût négligeable ~7 unités)
    python scripts/p1_2_validate_qualifiers.py --provider deepinfra \
        --model deepseek-ai/DeepSeek-V3.1

    # EC2 Burst vLLM (modèle de ré-ingestion) quand V5_VLLM_URL est positionné
    python scripts/p1_2_validate_qualifiers.py --provider vllm
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Charger .env (DEEPINFRA_API_KEY, V5_VLLM_URL, ...)
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT.parent / ".env")
except Exception:
    pass

from knowbase.claimfirst.extractors.claim_extractor import (  # noqa: E402
    ClaimExtractor,
    build_claim_extraction_prompt,
)
from knowbase.claimfirst.models.claim import QualifierType  # noqa: E402


# ── Set de validation multi-corpus (domain-agnostic) ─────────────────────────
# Chaque unité a au moins un qualifier attendu. `expects_procedural` marque les
# unités séquentielles (pour observer claim_type=PROCEDURAL).
VALIDATION_UNITS: List[Dict[str, Any]] = [
    {
        "domain": "sap_technical",
        "doc_title": "SAP S/4HANA Cloud — Release Notes",
        "doc_type": "technical",
        "text": "Since the 2023 release, SAP S/4HANA Cloud supports embedded "
        "analytics for finance, but only in the Private Cloud edition.",
        "expected_qualifier_types": {"temporal", "version", "scope_limit"},
    },
    {
        "domain": "sap_security",
        "doc_title": "SAP Security Baseline",
        "doc_type": "technical",
        "text": "Multi-factor authentication is mandatory for all administrator "
        "accounts in production environments.",
        "expected_qualifier_types": {"scope_limit", "condition"},
    },
    {
        "domain": "sap_procedural",
        "doc_title": "Single Sign-On Configuration Guide",
        "doc_type": "procedure",
        "text": "To enable single sign-on, first configure the identity provider, "
        "then activate the SAML trust, and finally assign users to the role.",
        "expected_qualifier_types": set(),
        "expects_procedural": True,
    },
    {
        "domain": "medical",
        "doc_title": "Drug Prescribing Information",
        "doc_type": "reference",
        "text": "In adults over 65 years, the daily dose should be reduced to 50 mg, "
        "except in patients with renal impairment.",
        "expected_qualifier_types": {"condition", "scope_limit"},
    },
    {
        "domain": "medical_2",
        "doc_title": "Immunization Schedule",
        "doc_type": "reference",
        "text": "Vaccination is recommended for children from 6 months of age in "
        "endemic regions only.",
        "expected_qualifier_types": {"condition", "spatial"},
    },
    {
        "domain": "legal",
        "doc_title": "Dual-Use Export Control Regulation",
        "doc_type": "legal",
        "text": "Effective from the 2021 amendment, exporters must obtain "
        "authorization before shipping dual-use items to non-EU countries.",
        "expected_qualifier_types": {"temporal", "spatial"},
    },
    {
        "domain": "aerospace",
        "doc_title": "Airspace Operations Manual",
        "doc_type": "technical",
        "text": "Above flight level 250, the reduced vertical separation minimum "
        "applies only to RVSM-approved aircraft.",
        "expected_qualifier_types": {"spatial", "condition"},
    },
]


def _make_client(provider: str):
    """Retourne (client_openai, model, label)."""
    from openai import OpenAI

    if provider == "deepinfra":
        key = os.getenv("DEEPINFRA_API_KEY", "").strip()
        if not key:
            raise SystemExit("DEEPINFRA_API_KEY manquant dans l'environnement/.env")
        return (
            OpenAI(api_key=key, base_url="https://api.deepinfra.com/v1/openai"),
            None,  # modèle fourni en CLI
            "deepinfra",
        )
    if provider == "vllm":
        url = (os.getenv("V5_VLLM_URL") or os.getenv("VLLM_URL") or "").strip()
        if not url:
            raise SystemExit(
                "V5_VLLM_URL / VLLM_URL non positionné — l'EC2 Burst n'est pas joignable.\n"
                "Décommenter/mettre à jour V5_VLLM_URL dans .env avec l'IP publique EC2."
            )
        base = url.rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1"
        return (
            OpenAI(api_key="EMPTY", base_url=base),
            os.getenv("V5_VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
            f"vllm ({base})",
        )
    raise SystemExit(f"Provider inconnu: {provider}")


def _content_words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(w) > 2]


def _is_grounded(value: str, source: str) -> bool:
    """Un qualifier est ancré si ≥50% de ses mots de contenu sont dans la source."""
    vw = _content_words(value)
    if not vw:
        return False
    sw = set(_content_words(source))
    hits = sum(1 for w in vw if w in sw)
    return hits / len(vw) >= 0.5


def _call_llm(client, model: str, prompt: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _parse_claims_json(raw: str) -> List[Dict[str, Any]]:
    """Extrait la liste claims du JSON LLM (tolérant aux fences/préambule)."""
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?", "", txt).strip()
    txt = re.sub(r"```$", "", txt).strip()
    # Trouver le premier objet JSON
    start = txt.find("{")
    if start < 0:
        return []
    try:
        obj = json.loads(txt[start:])
    except json.JSONDecodeError:
        # tentative : prendre jusqu'à la dernière }
        end = txt.rfind("}")
        try:
            obj = json.loads(txt[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(obj, dict):
        return obj.get("claims", []) or []
    if isinstance(obj, list):
        return obj
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["deepinfra", "vllm"], default="deepinfra")
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V3.1")
    args = ap.parse_args()

    client, forced_model, label = _make_client(args.provider)
    model = forced_model or args.model

    print(f"=== P1.2 validation qualifiers — provider={label} model={model} ===\n")

    total_claims = 0
    claims_with_qual = 0
    total_qual = 0
    grounded_qual = 0
    procedural_claims = 0
    type_counter: Dict[str, int] = {t.value: 0 for t in QualifierType}
    per_unit: List[Dict[str, Any]] = []
    errors = 0

    for u in VALIDATION_UNITS:
        units_text = f"U1: {u['text']}"
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=u["doc_title"],
            doc_type=u["doc_type"],
        )
        try:
            raw = _call_llm(client, model, prompt)
        except Exception as exc:  # pragma: no cover - réseau
            print(f"[{u['domain']}] ERREUR appel LLM: {exc}")
            errors += 1
            continue

        claims = _parse_claims_json(raw)
        u_claims = len(claims)
        u_with_qual = 0
        u_quals: List[Dict[str, Any]] = []
        for c in claims:
            total_claims += 1
            if str(c.get("claim_type", "")).upper() == "PROCEDURAL":
                procedural_claims += 1
            quals = ClaimExtractor._parse_qualifiers(c.get("qualifiers"))
            if quals:
                claims_with_qual += 1
                u_with_qual += 1
            for q in quals:
                total_qual += 1
                type_counter[q.qualifier_type.value] += 1
                grounded = _is_grounded(q.value, u["text"])
                if grounded:
                    grounded_qual += 1
                u_quals.append(
                    {
                        "type": q.qualifier_type.value,
                        "value": q.value,
                        "conf": q.confidence,
                        "grounded": grounded,
                    }
                )

        per_unit.append(
            {
                "domain": u["domain"],
                "n_claims": u_claims,
                "n_with_qual": u_with_qual,
                "quals": u_quals,
            }
        )
        print(f"[{u['domain']}] {u_claims} claims, {u_with_qual} avec qualifiers")
        for q in u_quals:
            flag = "✓" if q["grounded"] else "✗ NON-ANCRÉ"
            print(f"    - {q['type']:11s} \"{q['value']}\" (conf={q['conf']}) {flag}")

    # ── Synthèse ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    rate_claims = claims_with_qual / total_claims if total_claims else 0.0
    grounded_rate = grounded_qual / total_qual if total_qual else 0.0
    print(f"Total claims extraits        : {total_claims}")
    print(f"Claims avec ≥1 qualifier     : {claims_with_qual} ({rate_claims:.0%})  [gate P1.2 ≥30%]")
    print(f"Qualifiers totaux            : {total_qual}")
    print(f"Qualifiers ancrés (grounded) : {grounded_qual} ({grounded_rate:.0%})  [P1.2-valid ≥80%]")
    print(f"Claims PROCEDURAL détectés   : {procedural_claims}")
    print(f"Distribution par type        : "
          + ", ".join(f"{k}={v}" for k, v in type_counter.items() if v))
    if errors:
        print(f"⚠ Appels LLM en erreur       : {errors}")

    print("\n--- Verdict ---")
    if rate_claims < 0.20:
        print("🛑 STOP RULE déclenchée : <20% claims avec qualifiers. "
              "Revoir le prompt AVANT ré-ingestion (ne pas brûler l'EC2 Burst).")
    elif rate_claims >= 0.30 and grounded_rate >= 0.80:
        print("✅ Gate P1.2 ATTEINTE (≥30% claims qualifiés ET ≥80% ancrés).")
    elif rate_claims >= 0.30:
        print(f"🟡 Taux qualifiers OK (≥30%) mais ancrage {grounded_rate:.0%} < 80% "
              "→ resserrer la contrainte d'ancrage verbatim dans le prompt.")
    else:
        print(f"🟡 Taux qualifiers {rate_claims:.0%} entre 20% et 30% "
              "→ prompt à améliorer mais non bloquant.")

    out = ROOT / "data" / "benchmark" / "p1_2_qualifier_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "provider": label,
                "model": model,
                "total_claims": total_claims,
                "claims_with_qualifiers_rate": rate_claims,
                "grounded_rate": grounded_rate,
                "procedural_claims": procedural_claims,
                "type_distribution": type_counter,
                "per_unit": per_unit,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nRapport écrit : {out}")


if __name__ == "__main__":
    main()
