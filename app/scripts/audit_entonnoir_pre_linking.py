"""
OSMOSE — Audit Entonnoir Pré-Linking
=====================================
Test ciblé sur la première partie du pipeline (DocItems → policy).
Objectif: comprendre POURQUOI on perd 5000 DocItems et SI les 213 rejets policy sont justifiés.

Phase A: Audit exhaustif DocItems (6743 → 1697)
Phase B: Audit policy_rejected (213 assertions)

Usage:
    docker exec knowbase-app python scripts/audit_entonnoir_pre_linking.py

Produit: /data/audit_entonnoir_YYYY-MM-DD.json (résultats machine)
         + log structuré sur stdout (résumé humain)
"""

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("audit_entonnoir")

# ============================================================================
# PHASE A — Audit DocItems
# ============================================================================

def audit_docitems(doc_items: List[Any]) -> Dict:
    """
    Audit exhaustif des DocItems: distribution par type, longueur, raisons d'exclusion.
    """
    from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer

    indexer = AssertionUnitIndexer(min_unit_length=30, max_unit_length=500)

    # Résultats
    by_type: Dict[str, Dict] = defaultdict(lambda: {
        "total": 0,
        "indexed": 0,
        "skipped": 0,
        "skip_reasons": Counter(),
        "lengths": [],
        "skipped_samples": [],
        "indexed_samples": [],
    })

    total_indexed = 0
    total_skipped = 0
    total_units = 0

    for item in doc_items:
        item_type = item.item_type
        if hasattr(item_type, 'value'):
            item_type = item_type.value

        text = item.text or ""
        text_len = len(text.strip())
        bucket = by_type[item_type]
        bucket["total"] += 1
        bucket["lengths"].append(text_len)

        # Simuler le filtrage UnitIndexer
        if not text or text_len < 30:
            bucket["skipped"] += 1
            total_skipped += 1
            if text_len == 0:
                reason = "empty"
            elif text_len < 15:
                reason = "too_short_lt15"
            else:
                reason = "too_short_15_29"
            bucket["skip_reasons"][reason] += 1

            # Garder des exemples (max 10 par type)
            if len(bucket["skipped_samples"]) < 10:
                bucket["skipped_samples"].append({
                    "item_id": item.item_id,
                    "text": text.strip()[:150],
                    "length": text_len,
                    "reason": reason,
                    "page_no": getattr(item, 'page_no', None),
                })
        else:
            # Indexer pour voir combien d'unités sont produites
            docitem_id = f"audit:{item.doc_id}:{item.item_id}"
            result = indexer.index_docitem(
                docitem_id=docitem_id,
                text=text,
                item_type=item_type,
            )
            if result.units:
                bucket["indexed"] += 1
                total_indexed += 1
                total_units += len(result.units)
                if len(bucket["indexed_samples"]) < 5:
                    bucket["indexed_samples"].append({
                        "item_id": item.item_id,
                        "text": text.strip()[:150],
                        "length": text_len,
                        "units": len(result.units),
                        "page_no": getattr(item, 'page_no', None),
                    })
            else:
                # Indexé mais 0 unités (tous segments < 30 chars)
                bucket["skipped"] += 1
                total_skipped += 1
                bucket["skip_reasons"]["segments_too_short"] += 1
                if len(bucket["skipped_samples"]) < 10:
                    bucket["skipped_samples"].append({
                        "item_id": item.item_id,
                        "text": text.strip()[:150],
                        "length": text_len,
                        "reason": "segments_too_short",
                        "page_no": getattr(item, 'page_no', None),
                    })

    # Calculer les stats par type
    type_summary = {}
    for item_type, bucket in sorted(by_type.items(), key=lambda x: -x[1]["total"]):
        lengths = bucket["lengths"]
        type_summary[item_type] = {
            "total": bucket["total"],
            "indexed": bucket["indexed"],
            "skipped": bucket["skipped"],
            "pct_indexed": round(bucket["indexed"] / max(1, bucket["total"]) * 100, 1),
            "avg_length": round(sum(lengths) / max(1, len(lengths)), 1),
            "median_length": sorted(lengths)[len(lengths) // 2] if lengths else 0,
            "skip_reasons": dict(bucket["skip_reasons"]),
            "skipped_samples": bucket["skipped_samples"],
            "indexed_samples": bucket["indexed_samples"],
        }

    return {
        "total_docitems": len(doc_items),
        "total_indexed": total_indexed,
        "total_skipped": total_skipped,
        "total_units": total_units,
        "pct_indexed": round(total_indexed / max(1, len(doc_items)) * 100, 1),
        "by_type": type_summary,
    }


# ============================================================================
# PHASE B — Audit Policy Rejected
# ============================================================================

def audit_policy(
    doc_items: List[Any],
    chunks: List[Any],
    chunk_to_docitem_map: Dict,
) -> Dict:
    """
    Audit complet du filtre policy: rejoue l'extraction + policy sur les données réelles.
    Retourne la décomposition par sous-raison avec exemples.
    """
    from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer
    from knowbase.stratified.pass1.promotion_engine import (
        is_fragment,
        is_meta_pattern,
        FRAGMENT_PATTERNS,
        _COMPILED_FRAGMENT_PATTERNS,
        _COMPILED_META_PATTERNS,
    )

    # On ne relance PAS l'extraction LLM.
    # On charge les assertions depuis Neo4j (assertion_logs) pour analyse.
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))

    all_assertions = []
    with driver.session() as session:
        result = session.run("""
            MATCH (al:AssertionLog)
            RETURN al.assertion_id as id, al.text as text, al.type as type,
                   al.status as status, al.reason as reason, al.confidence as conf,
                   size(al.text) as len
            ORDER BY al.status, size(al.text)
        """)
        for rec in result:
            all_assertions.append({
                "id": rec["id"],
                "text": rec["text"],
                "type": rec["type"],
                "status": rec["status"],
                "reason": rec["reason"],
                "confidence": rec["conf"],
                "length": rec["len"],
            })
    driver.close()

    logger.info(f"Chargé {len(all_assertions)} assertion logs depuis Neo4j")

    # Séparer par status
    rejected = [a for a in all_assertions if a["status"] == "REJECTED"]
    promoted = [a for a in all_assertions if a["status"] == "PROMOTED"]
    abstained = [a for a in all_assertions if a["status"] == "ABSTAINED"]

    # Sous-analyse des REJECTED: déterminer la sous-raison exacte
    sub_reasons = Counter()
    by_sub_reason: Dict[str, List[Dict]] = defaultdict(list)
    by_type_rejected = Counter()
    length_buckets = Counter()

    for a in rejected:
        text = a["text"]
        text_stripped = text.strip()
        a_type = a["type"]
        by_type_rejected[a_type] += 1

        # Bucket longueur
        text_len = len(text_stripped)
        if text_len < 15:
            length_buckets["<15"] += 1
        elif text_len < 30:
            length_buckets["15-29"] += 1
        elif text_len < 50:
            length_buckets["30-49"] += 1
        elif text_len < 100:
            length_buckets["50-99"] += 1
        elif text_len < 150:
            length_buckets["100-149"] += 1
        else:
            length_buckets["150+"] += 1

        # Déterminer la sous-raison exacte
        sub_reason = _classify_rejection(text_stripped, a_type, a["confidence"])
        sub_reasons[sub_reason] += 1

        # Garder des exemples (max 15 par sous-raison)
        if len(by_sub_reason[sub_reason]) < 15:
            by_sub_reason[sub_reason].append({
                "text": text_stripped[:200],
                "type": a_type,
                "length": text_len,
                "confidence": a["confidence"],
                "sub_reason": sub_reason,
            })

    # Analyse de "perte de valeur": assertions rejetées objectivement utiles
    value_loss = _identify_value_loss(rejected)

    return {
        "total_assertions": len(all_assertions),
        "promoted": len(promoted),
        "rejected": len(rejected),
        "abstained": len(abstained),
        "rejected_by_sub_reason": dict(sub_reasons.most_common()),
        "rejected_by_type": dict(by_type_rejected.most_common()),
        "rejected_by_length": dict(sorted(length_buckets.items())),
        "samples_by_sub_reason": {k: v for k, v in by_sub_reason.items()},
        "value_loss_candidates": value_loss,
    }


def _classify_rejection(text: str, assertion_type: str, confidence: float) -> str:
    """
    Classifie précisément la sous-raison de rejet d'une assertion.
    Reproduit la logique de filter_by_promotion_policy() avec diagnostics.
    """
    from knowbase.stratified.pass1.promotion_engine import (
        is_fragment,
        is_meta_pattern,
        _COMPILED_FRAGMENT_PATTERNS,
    )

    # 1. Meta-pattern ?
    if is_meta_pattern(text):
        # Sous-classer le meta-pattern
        text_lower = text.lower().strip()
        if any(w in text_lower for w in ["copyright", "©", "all rights reserved"]):
            return "meta:copyright"
        if any(w in text_lower for w in ["internal", "under nda", "confidential"]):
            return "meta:classification_header"
        if text_lower.startswith(("is ", "how ", "what ", "can ", "do ", "will ", "does ")):
            return "meta:question"
        if any(w in text_lower for w in ["diagram", "figure", "page describes", "section shows"]):
            return "meta:visual_description"
        if any(w in text_lower for w in ["disclaimer", "not a commitment", "without notice"]):
            return "meta:disclaimer"
        return "meta:other_pattern"

    # 2. Fragment ?
    # ADR 2026-01-30: no_verb désactivé — seuls length/words/pattern restent
    if is_fragment(text):
        # Sous-classer le fragment
        if len(text) < 15:
            return "fragment:too_short_lt15"
        words = text.split()
        if len(words) < 3:
            return "fragment:too_few_words"
        # Check pattern match
        for pattern in _COMPILED_FRAGMENT_PATTERNS:
            if pattern.match(text):
                return "fragment:pattern_match"
        return "fragment:other"

    # 3. Tier-based rejection
    # PROMOTION_POLICY mapping
    tier_map = {
        "DEFINITIONAL": "ALWAYS",
        "PRESCRIPTIVE": "ALWAYS",
        "CAUSAL": "ALWAYS",
        "FACTUAL": "CONDITIONAL",
        "CONDITIONAL": "CONDITIONAL",
        "PERMISSIVE": "CONDITIONAL",
        "COMPARATIVE": "RARELY",
        "PROCEDURAL": "NEVER",
    }
    tier = tier_map.get(assertion_type, "RARELY")

    if tier == "NEVER":
        return "tier:PROCEDURAL_never"
    if tier == "RARELY" and confidence < 0.9:
        return "tier:RARELY_low_conf"
    if tier == "CONDITIONAL" and confidence < 0.7:
        return "tier:CONDITIONAL_low_conf"

    return "unknown_rejection"


def _identify_value_loss(rejected: List[Dict]) -> List[Dict]:
    """
    Identifie les assertions rejetées qui représentent une perte de valeur métier.
    Critères: ≥30 chars, type ALWAYS ou assertion technique, pas boilerplate.
    """
    boilerplate_patterns = [
        r"copyright",
        r"all rights reserved",
        r"sap se or an sap affiliate",
        r"internal.*nda",
        r"strictly prohibited",
        r"^©",
    ]
    compiled_boilerplate = [re.compile(p, re.IGNORECASE) for p in boilerplate_patterns]

    # Mots techniques SAP/sécurité
    technical_keywords = {
        "encryption", "mfa", "tls", "ssl", "firewall", "waf", "vpn", "vnet",
        "vpc", "tenant", "isolation", "patch", "vulnerability", "sla", "rpo",
        "rto", "backup", "replication", "failover", "disaster", "recovery",
        "compliance", "audit", "soc", "iso", "gdpr", "rbac", "sso", "saml",
        "oauth", "x.509", "certificate", "monitoring", "siem", "ids", "ips",
        "hardening", "golden image", "deployment", "infrastructure", "hyperscaler",
    }

    value_candidates = []
    for a in rejected:
        text = a["text"]
        text_len = len(text.strip())

        # Skip courts
        if text_len < 30:
            continue

        # Skip boilerplate
        is_boilerplate = any(p.search(text) for p in compiled_boilerplate)
        if is_boilerplate:
            continue

        # Score de valeur technique
        text_lower = text.lower()
        tech_score = sum(1 for kw in technical_keywords if kw in text_lower)

        # ALWAYS-tier types ont plus de valeur
        type_bonus = 2 if a["type"] in ("DEFINITIONAL", "PRESCRIPTIVE", "CAUSAL") else 0

        total_score = tech_score + type_bonus

        if total_score >= 2 or (text_len >= 50 and tech_score >= 1):
            value_candidates.append({
                "text": text.strip()[:200],
                "type": a["type"],
                "length": text_len,
                "tech_score": tech_score,
                "total_score": total_score,
                "sub_reason": _classify_rejection(text.strip(), a["type"], a.get("confidence", 0.9)),
            })

    # Trier par score décroissant
    value_candidates.sort(key=lambda x: -x["total_score"])
    return value_candidates[:30]  # Top 30


# ============================================================================
# MAIN
# ============================================================================

def main():
    logger.info("=" * 70)
    logger.info("[AUDIT] Démarrage Audit Entonnoir Pré-Linking")
    logger.info("=" * 70)

    # Charger les DocItems depuis le cache
    from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache

    cache_path = "/data/extraction_cache/363f5357dfe38242a968415f643eff1edca39866d7e714bcb9ea5606cece5359.v5cache.json"

    logger.info(f"[AUDIT] Chargement cache: {cache_path}")
    cache_result = load_pass0_from_cache(cache_path, tenant_id="default")

    if not cache_result.success:
        logger.error(f"[AUDIT] Échec chargement cache: {cache_result.error}")
        sys.exit(1)

    pass0 = cache_result.pass0_result
    doc_items = pass0.doc_items
    chunks = pass0.chunks

    logger.info(f"[AUDIT] DocItems: {len(doc_items)}, Chunks: {len(chunks)}")

    # =====================================================================
    # PHASE A — Audit DocItems
    # =====================================================================
    logger.info("")
    logger.info("=" * 70)
    logger.info("[PHASE A] Audit DocItems — Distribution et filtrage")
    logger.info("=" * 70)

    docitem_audit = audit_docitems(doc_items)

    logger.info(f"")
    logger.info(f"[PHASE A] RÉSULTATS")
    logger.info(f"  Total DocItems : {docitem_audit['total_docitems']}")
    logger.info(f"  Indexés        : {docitem_audit['total_indexed']} ({docitem_audit['pct_indexed']}%)")
    logger.info(f"  Filtrés        : {docitem_audit['total_skipped']} ({100 - docitem_audit['pct_indexed']}%)")
    logger.info(f"  Unités         : {docitem_audit['total_units']}")

    logger.info(f"")
    logger.info(f"  {'Type':<15s} {'Total':>6s} {'Indexé':>6s} {'Filtré':>6s} {'%Indexé':>7s} {'Avg Len':>8s} {'Med Len':>8s}")
    logger.info(f"  {'-'*15} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*8} {'-'*8}")
    for item_type, stats in sorted(docitem_audit["by_type"].items(), key=lambda x: -x[1]["total"]):
        logger.info(
            f"  {item_type:<15s} {stats['total']:>6d} {stats['indexed']:>6d} "
            f"{stats['skipped']:>6d} {stats['pct_indexed']:>6.1f}% "
            f"{stats['avg_length']:>7.0f} {stats['median_length']:>8d}"
        )

    # Raisons de skip par type
    logger.info(f"")
    logger.info(f"  Raisons de filtrage par type:")
    for item_type, stats in sorted(docitem_audit["by_type"].items(), key=lambda x: -x[1]["skipped"]):
        if stats["skipped"] > 0:
            reasons = ", ".join(f"{r}={c}" for r, c in stats["skip_reasons"].items())
            logger.info(f"    {item_type}: {stats['skipped']} filtrés ({reasons})")

    # Exemples de DocItems filtrés
    logger.info(f"")
    logger.info(f"  Exemples DocItems filtrés (par type):")
    for item_type, stats in sorted(docitem_audit["by_type"].items(), key=lambda x: -x[1]["skipped"]):
        samples = stats["skipped_samples"][:5]
        if samples:
            logger.info(f"    {item_type}:")
            for s in samples:
                txt = s['text'][:80] if s['text'] else '(vide)'
                logger.info(f"      [{s['reason']}] (len={s['length']:3d}) {txt}")

    # =====================================================================
    # PHASE B — Audit Policy Rejected
    # =====================================================================
    logger.info("")
    logger.info("=" * 70)
    logger.info("[PHASE B] Audit Policy Rejected — Sous-raisons et perte de valeur")
    logger.info("=" * 70)

    policy_audit = audit_policy(doc_items, chunks, pass0.chunk_to_docitem_map)

    logger.info(f"")
    logger.info(f"[PHASE B] RÉSULTATS")
    logger.info(f"  Total assertions : {policy_audit['total_assertions']}")
    logger.info(f"  PROMOTED         : {policy_audit['promoted']}")
    logger.info(f"  REJECTED         : {policy_audit['rejected']}")
    logger.info(f"  ABSTAINED        : {policy_audit['abstained']}")

    logger.info(f"")
    logger.info(f"  Sous-raisons de rejet:")
    for reason, count in sorted(policy_audit["rejected_by_sub_reason"].items(), key=lambda x: -x[1]):
        pct = count / max(1, policy_audit["rejected"]) * 100
        logger.info(f"    {reason:<35s}: {count:>4d} ({pct:>5.1f}%)")

    logger.info(f"")
    logger.info(f"  Distribution par type d'assertion:")
    for a_type, count in sorted(policy_audit["rejected_by_type"].items(), key=lambda x: -x[1]):
        logger.info(f"    {a_type:<15s}: {count}")

    logger.info(f"")
    logger.info(f"  Distribution par longueur:")
    for bucket, count in sorted(policy_audit["rejected_by_length"].items()):
        logger.info(f"    {bucket:<12s}: {count}")

    # Exemples par sous-raison
    logger.info(f"")
    logger.info(f"  Exemples par sous-raison dominante:")
    for reason in sorted(policy_audit["samples_by_sub_reason"].keys()):
        samples = policy_audit["samples_by_sub_reason"][reason][:5]
        if samples:
            logger.info(f"")
            logger.info(f"    === {reason} ({len(policy_audit['samples_by_sub_reason'][reason])} total) ===")
            for s in samples:
                logger.info(f"      [{s['type']:12s}] (len={s['length']:3d}) {s['text'][:120]}")

    # Perte de valeur
    logger.info(f"")
    logger.info(f"  {'=' * 60}")
    logger.info(f"  PERTE DE VALEUR — Top assertions rejetées objectivement utiles")
    logger.info(f"  {'=' * 60}")
    value_loss = policy_audit["value_loss_candidates"]
    logger.info(f"  Candidats identifiés: {len(value_loss)}")
    for i, v in enumerate(value_loss[:20], 1):
        logger.info(
            f"  {i:>2d}. [{v['type']:12s}] (score={v['total_score']}, len={v['length']:3d}) "
            f"[{v['sub_reason']}]"
        )
        logger.info(f"      \"{v['text'][:150]}\"")

    # =====================================================================
    # VERDICT FINAL
    # =====================================================================
    logger.info(f"")
    logger.info("=" * 70)
    logger.info("[VERDICT] Synthèse")
    logger.info("=" * 70)

    # Compter les rejets par catégorie verdict
    # ADR 2026-01-30: no_verb désactivé — ne devrait plus y en avoir
    fragment_no_verb = policy_audit["rejected_by_sub_reason"].get("fragment:no_verb", 0)
    fragment_short = (
        policy_audit["rejected_by_sub_reason"].get("fragment:too_short_lt15", 0) +
        policy_audit["rejected_by_sub_reason"].get("fragment:too_few_words", 0) +
        policy_audit["rejected_by_sub_reason"].get("fragment:pattern_match", 0)
    )
    meta_legit = (
        policy_audit["rejected_by_sub_reason"].get("meta:copyright", 0) +
        policy_audit["rejected_by_sub_reason"].get("meta:classification_header", 0) +
        policy_audit["rejected_by_sub_reason"].get("meta:disclaimer", 0)
    )
    meta_questionable = (
        policy_audit["rejected_by_sub_reason"].get("meta:question", 0) +
        policy_audit["rejected_by_sub_reason"].get("meta:visual_description", 0) +
        policy_audit["rejected_by_sub_reason"].get("meta:other_pattern", 0)
    )
    tier_never = policy_audit["rejected_by_sub_reason"].get("tier:PROCEDURAL_never", 0)
    tier_low_conf = (
        policy_audit["rejected_by_sub_reason"].get("tier:RARELY_low_conf", 0) +
        policy_audit["rejected_by_sub_reason"].get("tier:CONDITIONAL_low_conf", 0)
    )

    total_rej = policy_audit["rejected"]
    legit = fragment_short + meta_legit
    questionable = meta_questionable + tier_low_conf
    excessive = fragment_no_verb + tier_never + policy_audit["rejected_by_sub_reason"].get("fragment:other", 0)

    logger.info(f"  Rejets LÉGITIMES (bruit réel)      : {legit:>4d} ({legit/max(1,total_rej)*100:.0f}%)")
    logger.info(f"    - Fragments courts (<15, <3 mots) : {fragment_short}")
    logger.info(f"    - Meta copyright/NDA/disclaimer   : {meta_legit}")
    logger.info(f"")
    logger.info(f"  Rejets DISCUTABLES                  : {questionable:>4d} ({questionable/max(1,total_rej)*100:.0f}%)")
    logger.info(f"    - Meta questions/descriptions      : {meta_questionable}")
    logger.info(f"    - Tier low confidence              : {tier_low_conf}")
    logger.info(f"")
    logger.info(f"  Rejets EXCESSIFS                    : {excessive:>4d} ({excessive/max(1,total_rej)*100:.0f}%)")
    logger.info(f"    - Fragment:no_verb                 : {fragment_no_verb}")
    logger.info(f"    - Tier PROCEDURAL (NEVER)          : {tier_never}")
    logger.info(f"    - Fragment:other                   : {policy_audit['rejected_by_sub_reason'].get('fragment:other', 0)}")
    logger.info(f"")
    logger.info(f"  GAIN POTENTIEL si fix no_verb + PROCEDURAL→CONDITIONAL:")
    gain = fragment_no_verb + tier_never
    current = policy_audit["promoted"]
    logger.info(f"    +{gain} assertions récupérées → {current + gain} informations potentielles (+{gain/max(1,current)*100:.0f}%)")

    # =====================================================================
    # Sauvegarder les résultats JSON
    # =====================================================================
    output_path = f"/data/audit_entonnoir_{datetime.now().strftime('%Y-%m-%d')}.json"

    # Nettoyer les données pour sérialisation
    output = {
        "metadata": {
            "date": datetime.now().isoformat(),
            "document": "RISE with SAP Cloud ERP Private Security",
            "cache_file": cache_path,
            "pipeline": "Stratified V2 (GlobalView 16K)",
        },
        "phase_a_docitems": {
            "total": docitem_audit["total_docitems"],
            "indexed": docitem_audit["total_indexed"],
            "skipped": docitem_audit["total_skipped"],
            "units": docitem_audit["total_units"],
            "by_type": {
                k: {kk: vv for kk, vv in v.items() if kk != "lengths"}
                for k, v in docitem_audit["by_type"].items()
            },
        },
        "phase_b_policy": policy_audit,
        "verdict": {
            "legit_rejections": legit,
            "questionable_rejections": questionable,
            "excessive_rejections": excessive,
            "potential_gain": gain,
            "current_promoted": current,
            "projected_promoted": current + gain,
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"")
    logger.info(f"[AUDIT] Résultats sauvegardés: {output_path}")
    logger.info(f"[AUDIT] Terminé.")


if __name__ == "__main__":
    main()
