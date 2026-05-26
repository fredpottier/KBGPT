#!/usr/bin/env python
"""
p1_dedup_tiered_probe.py — Mesure (READ-ONLY) du potentiel de déduplication
sémantique "tiered" sur les claims déjà présents dans le KG, SANS ré-ingestion.

Lever #2 du Volet 2 SOTA (doc/ongoing/SOTA_CLAIM_EXTRACTION_2026.md) : on cherche à
réduire le volume/redondance issu de la sur-extraction P1.3.5 (×23) par un
post-traitement DÉTERMINISTE, avant de retoucher le prompt.

Cascade (chaque tier filtre les candidats du suivant) :
  Tier 1 — exact / normalisé / content_fingerprint   (déterministe, sans modèle)
  Tier 2 — cosine >= seuil sur embeddings e5-large    (candidats near-dup, GPU local)
  Tier 3 — entailment bidirectionnel HHEM-2.1          (logique CORE : dup vs subsumption vs distinct)

Garde-fou identifiants (#3 partiel) : un claim qui porte un identifiant
(ALL_CAPS, snake_case, code transaction, n° réglement, version…) que son
"survivant" candidat n'a PAS n'est JAMAIS marqué dupliqué. Hallucination 65%->1.6%
quand on protège les identifiants (littérature 2026).

Le script NE MODIFIE PAS le KG. Il calcule des embeddings en local (GPU) et les
met en cache disque pour itérer vite. Sortie = rapport JSON + Markdown.

Usage:
    docker compose exec app python scripts/p1_dedup_tiered_probe.py
    docker compose exec app python scripts/p1_dedup_tiered_probe.py --limit 500      # smoke
    docker compose exec app python scripts/p1_dedup_tiered_probe.py --tiers 1        # Tier 1 seul
    docker compose exec app python scripts/p1_dedup_tiered_probe.py --tiers 1,2      # sans NLI
    docker compose exec app python scripts/p1_dedup_tiered_probe.py --cosine-threshold 0.92
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] dedup_probe")

ROOT = Path(__file__).resolve().parent.parent          # /app
OUT_DIR = ROOT / "data" / "benchmark" / "dedup"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"      # même modèle que les chunks


# ──────────────────────────────────────────────────────────────────────────────
# Garde-fou identifiants
# ──────────────────────────────────────────────────────────────────────────────

# ALL_CAPS / acronymes / codes (≥2 chars, commence par majuscule) : SAP, HANA, WWI, CG5Z, SE80, MM02
_ALLCAPS_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
# snake_case / identifiants techniques : valid_from, doc_id, structured_form_json
_SNAKE_RE = re.compile(r"\b\w+_\w+\b")
# tout token porteur d'un chiffre : 2021/821, v3.1, 1.2.3, S/4HANA, 20, 4HANA
_DIGIT_TOKEN_RE = re.compile(r"\b[\w/.\-]*\d[\w/.\-]*\b")


def protected_identifiers(text: str) -> frozenset[str]:
    """Ensemble des identifiants "protégés" portés par un claim.

    Insensible à la casse pour le snake/digit, sensible pour ALL_CAPS (canonisé en lower
    pour comparaison d'ensembles). On préfère sur-protéger (faux positifs côté KEEP)
    plutôt que perdre un identifiant rare — cohérent avec la régression factual observée
    quand le cosine pur fusionne des claims à identifiants distincts.
    """
    if not text:
        return frozenset()
    toks: set[str] = set()
    for m in _ALLCAPS_RE.findall(text):
        # éviter de capturer un mot anglais tout en majuscules trivial — on garde quand même
        toks.add(m.lower())
    for m in _SNAKE_RE.findall(text):
        toks.add(m.lower())
    for m in _DIGIT_TOKEN_RE.findall(text):
        # ignorer purement numérique court (ex "1", "2") = peu discriminant
        if re.search(r"\d", m) and len(m) >= 2:
            toks.add(m.lower())
    return frozenset(toks)


# ──────────────────────────────────────────────────────────────────────────────
# Normalisation texte (Tier 1)
# ──────────────────────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Normalisation pour exact-match Tier 1 : casse, accents, ponctuation, espaces."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Union-Find (clustering des doublons confirmés)
# ──────────────────────────────────────────────────────────────────────────────

class UnionFind:
    def __init__(self, items: List[str]):
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def clusters(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = defaultdict(list)
        for x in self.parent:
            groups[self.find(x)].append(x)
        return {k: v for k, v in groups.items() if len(v) > 1}


# ──────────────────────────────────────────────────────────────────────────────
# Chargement des claims
# ──────────────────────────────────────────────────────────────────────────────

def load_claims(tenant_id: str, limit: Optional[int]) -> List[dict]:
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    cypher = """
        MATCH (c:Claim {tenant_id: $tid})
        RETURN c.claim_id          AS claim_id,
               c.text              AS text,
               c.subject_canonical AS subject_canonical,
               c.doc_id            AS doc_id,
               c.content_fingerprint AS content_fingerprint,
               c.confidence        AS confidence,
               c.claim_type        AS claim_type
        ORDER BY c.claim_id
    """
    if limit:
        cypher += f"\n        LIMIT {int(limit)}"

    with driver.session() as session:
        rows = [dict(r) for r in session.run(cypher, tid=tenant_id)]
    driver.close()
    # nettoyer
    for r in rows:
        r["text"] = r.get("text") or ""
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Tier 1 — exact / normalisé / fingerprint
# ──────────────────────────────────────────────────────────────────────────────

def tier1_exact(claims: List[dict]) -> dict:
    by_norm: Dict[str, List[str]] = defaultdict(list)
    by_cfp: Dict[str, List[str]] = defaultdict(list)
    for c in claims:
        nt = normalize_text(c["text"])
        if nt:
            by_norm[nt].append(c["claim_id"])
        cfp = c.get("content_fingerprint")
        if cfp:
            by_cfp[cfp].append(c["claim_id"])

    norm_clusters = {k: v for k, v in by_norm.items() if len(v) > 1}
    cfp_clusters = {k: v for k, v in by_cfp.items() if len(v) > 1}

    # claims supprimables = (taille cluster - 1) sommé, en UNION des deux signaux
    uf = UnionFind([c["claim_id"] for c in claims])
    for ids in norm_clusters.values():
        for o in ids[1:]:
            uf.union(ids[0], o)
    for ids in cfp_clusters.values():
        for o in ids[1:]:
            uf.union(ids[0], o)
    clusters = uf.clusters()
    removable = sum(len(v) - 1 for v in clusters.values())

    return {
        "norm_exact_clusters": len(norm_clusters),
        "content_fingerprint_clusters": len(cfp_clusters),
        "merged_clusters": len(clusters),
        "removable": removable,
        "clusters": clusters,                         # {root: [claim_ids]}
        "norm_samples": list(norm_clusters.items())[:15],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tier 2 — cosine sur embeddings e5-large
# ──────────────────────────────────────────────────────────────────────────────

def compute_embeddings(claims: List[dict], cache_path: Path) -> np.ndarray:
    ids = [c["claim_id"] for c in claims]
    if cache_path.exists():
        data = np.load(cache_path, allow_pickle=True)
        cached_ids = list(data["claim_ids"])
        if cached_ids == ids:
            logger.info("Embeddings rechargés du cache (%d claims)", len(ids))
            return data["embeddings"].astype(np.float32)
        logger.info("Cache embeddings obsolète (set de claims différent) -> recalcul")

    logger.info("Chargement du modèle %s ...", EMBEDDING_MODEL)
    from knowbase.common.clients.embeddings import EmbeddingModelManager

    model = EmbeddingModelManager().get_model()
    texts = [f"passage: {c['text']}" for c in claims]
    t0 = time.time()
    emb = model.encode(
        texts, normalize_embeddings=True, batch_size=128, show_progress_bar=False
    ).astype(np.float32)
    logger.info("Embeddings calculés : %s en %.0fs", emb.shape, time.time() - t0)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, claim_ids=np.array(ids, dtype=object), embeddings=emb)
    return emb


def tier2_cosine(
    claims: List[dict],
    emb: np.ndarray,
    threshold: float,
    block_size: int = 1024,
) -> List[Tuple[int, int, float]]:
    """Retourne les paires (i, j, cosine) avec i<j et cosine>=threshold.

    Embeddings déjà L2-normalisés -> cosine = produit scalaire. Calcul par blocs de
    lignes pour borner la mémoire (block × N).
    """
    n = emb.shape[0]
    pairs: List[Tuple[int, int, float]] = []
    for start in range(0, n, block_size):
        end = min(start + block_size, n)
        sims = emb[start:end] @ emb.T          # (block, n)
        for local_i in range(end - start):
            i = start + local_i
            row = sims[local_i]
            # candidats j>i au-dessus du seuil
            js = np.where(row[i + 1 :] >= threshold)[0] + (i + 1)
            for j in js:
                pairs.append((i, int(j), float(row[j])))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


# ──────────────────────────────────────────────────────────────────────────────
# Tier 3 — équivalence sémantique via cross-encoder bge-reranker-v2-m3
# ──────────────────────────────────────────────────────────────────────────────
#
# Note d'implémentation : HHEM-2.1-Open (entailment NLI directionnel) est inutilisable
# dans ce container (remote code custom HHEMv2 incompatible avec la version transformers
# installée -> AttributeError all_tied_weights_keys). On utilise donc bge-reranker-v2-m3,
# l'autre brique disponible et déjà chargée en prod runtime_v6. Validé empiriquement :
# il discrimine les "frères d'énumération" (SSO user/pwd vs X.509 -> 0.07) des vraies
# paraphrases/subsumptions (-> 0.95-1.0) là où le cosine seul les confond (≥0.93).
# Score symétrisé = moyenne des deux sens ; l'asymétrie sert d'indice de subsumption.

def tier3_crossencoder(
    claims: List[dict],
    pairs: List[Tuple[int, int, float]],
    dup_threshold: float,
    subsumption_ratio: float,
    max_pairs: int,
    reranker_model: str,
) -> dict:
    from knowbase.common.clients.reranker import get_cross_encoder

    ce = get_cross_encoder(reranker_model)

    capped = pairs[:max_pairs]
    if len(pairs) > max_pairs:
        logger.warning(
            "Tier 3 : %d paires candidates -> capées à %d (plus haut cosine)",
            len(pairs), max_pairs,
        )

    # batch des deux sens
    t0 = time.time()
    fwd = [(claims[i]["text"], claims[j]["text"]) for i, j, _ in capped]
    bwd = [(claims[j]["text"], claims[i]["text"]) for i, j, _ in capped]
    s_fwd = [float(x) for x in ce.predict(fwd, batch_size=64, show_progress_bar=False)]
    s_bwd = [float(x) for x in ce.predict(bwd, batch_size=64, show_progress_bar=False)]
    logger.info("Tier 3 : %d paires scorées (%.0fs)", len(capped), time.time() - t0)

    results = {
        "EQUIVALENT": [],      # score haut, longueurs proches -> doublon
        "SUBSUMPTION": [],     # score haut, l'un nettement plus court -> redondant (inclus)
        "DISTINCT": [],        # cosine élevé MAIS reranker bas = faux positif cosine
        "GUARDED": [],         # serait fusionné mais identifiant unique -> KEEP
    }
    score_hist: Dict[str, int] = defaultdict(int)

    for k, (i, j, cos) in enumerate(capped):
        a, b = claims[i], claims[j]
        ta, tb = a["text"], b["text"]
        sf, sb = s_fwd[k], s_bwd[k]
        score = (sf + sb) / 2.0

        bucket = f"{int(min(score, 0.999) * 10) / 10:.1f}"
        score_hist[bucket] += 1

        rec = {
            "i": i, "j": j, "cos": round(cos, 4),
            "claim_id_a": a["claim_id"], "claim_id_b": b["claim_id"],
            "text_a": ta, "text_b": tb,
            "ce_score": round(score, 4), "ce_fwd": round(sf, 4), "ce_bwd": round(sb, 4),
            "doc_a": a.get("doc_id"), "doc_b": b.get("doc_id"),
        }

        if score < dup_threshold:
            results["DISTINCT"].append(rec)
            continue

        # candidat redondant -> garde-fou identifiants
        len_a, len_b = len(ta), len(tb)
        ratio = min(len_a, len_b) / max(len_a, len_b) if max(len_a, len_b) else 1.0
        prot_a = protected_identifiers(ta)
        prot_b = protected_identifiers(tb)

        if ratio < subsumption_ratio:
            # le plus court est candidat à la suppression (subsumption)
            keep, drop = (a, b) if len_a >= len_b else (b, a)
            verdict = "SUBSUMPTION"
        else:
            keep, drop = _choose_survivor(a, b, prot_a, prot_b)
            verdict = "EQUIVALENT"

        prot_keep = protected_identifiers(keep["text"])
        prot_drop = protected_identifiers(drop["text"])
        if not prot_drop.issubset(prot_keep):
            rec["unique_ids_in_drop"] = sorted(prot_drop - prot_keep)
            rec["verdict_would_be"] = verdict
            results["GUARDED"].append(rec)
            continue

        rec["keep"] = keep["claim_id"]
        rec["drop"] = drop["claim_id"]
        results[verdict].append(rec)

    results["_n_evaluated"] = len(capped)
    results["_n_candidates"] = len(pairs)
    results["_elapsed_s"] = round(time.time() - t0, 1)
    results["_score_hist"] = dict(sorted(score_hist.items()))
    return results


def _choose_survivor(a: dict, b: dict, prot_a: frozenset, prot_b: frozenset):
    """Survivant = plus d'identifiants, puis texte le plus long, puis confiance, puis id."""
    ka = (len(prot_a), len(a["text"]), a.get("confidence") or 0.0, b["claim_id"])
    kb = (len(prot_b), len(b["text"]), b.get("confidence") or 0.0, a["claim_id"])
    return (a, b) if ka >= kb else (b, a)


# ──────────────────────────────────────────────────────────────────────────────
# Agrégation réduction
# ──────────────────────────────────────────────────────────────────────────────

def estimate_reduction(
    total: int,
    tier1: dict,
    tier3: Optional[dict],
    claims: List[dict],
) -> dict:
    """Réduction cumulée via union-find sur (Tier1 ∪ doublons confirmés Tier3)."""
    uf = UnionFind([c["claim_id"] for c in claims])
    for ids in tier1["clusters"].values():
        for o in ids[1:]:
            uf.union(ids[0], o)

    tier3_removed = 0
    if tier3:
        for rec in tier3["EQUIVALENT"] + tier3["SUBSUMPTION"]:
            uf.union(rec["keep"], rec["drop"])

    clusters = uf.clusters()
    total_removable = sum(len(v) - 1 for v in clusters.values())
    if tier3:
        tier3_removed = total_removable - tier1["removable"]

    return {
        "total_claims": total,
        "tier1_removable": tier1["removable"],
        "tier3_additional_removable": max(0, tier3_removed),
        "cumulative_removable": total_removable,
        "cumulative_pct": round(100.0 * total_removable / total, 2) if total else 0.0,
        "survivors": total - total_removable,
        "merged_cluster_count": len(clusters),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Rapport
# ──────────────────────────────────────────────────────────────────────────────

def write_reports(payload: dict, claims_by_id: dict, stamp: str) -> Tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"dedup_probe_{stamp}.json"
    md_path = OUT_DIR / f"dedup_probe_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    red = payload["reduction"]
    t1 = payload["tier1"]
    t2 = payload.get("tier2", {})
    t3 = payload.get("tier3")

    lines: List[str] = []
    lines.append(f"# Probe dédup tiered — {stamp}")
    lines.append("")
    lines.append(f"**Config** : cosine≥{payload['config']['cosine_threshold']}, "
                 f"reranker_dup≥{payload['config'].get('dup_threshold')}, "
                 f"subsumption_ratio<{payload['config'].get('subsumption_ratio')}, "
                 f"tiers={payload['config']['tiers']}")
    lines.append("")
    lines.append("## Réduction estimée (read-only, sans ré-ingestion)")
    lines.append("")
    lines.append(f"- Total claims : **{red['total_claims']}**")
    lines.append(f"- Tier 1 (exact/normalisé/fingerprint) supprimables : **{red['tier1_removable']}**")
    if t3:
        lines.append(f"- Tier 3 (entailment confirmé) supprimables additionnels : **{red['tier3_additional_removable']}**")
    lines.append(f"- **Total supprimables : {red['cumulative_removable']} "
                 f"({red['cumulative_pct']}%)** -> survivants : {red['survivors']}")
    lines.append("")

    lines.append("## Tier 1 — exact / normalisé / fingerprint")
    lines.append(f"- clusters texte normalisé : {t1['norm_exact_clusters']}")
    lines.append(f"- clusters content_fingerprint : {t1['content_fingerprint_clusters']}")
    lines.append(f"- clusters fusionnés : {t1['merged_clusters']} | supprimables : {t1['removable']}")
    lines.append("")
    if t1["norm_samples"]:
        lines.append("**Exemples doublons exacts :**")
        for nt, ids in t1["norm_samples"][:8]:
            ex = claims_by_id[ids[0]]["text"]
            lines.append(f"- ×{len(ids)} — « {ex[:160]} »")
        lines.append("")

    if t2:
        lines.append("## Tier 2 — cosine")
        lines.append(f"- paires candidates ≥{payload['config']['cosine_threshold']} : **{t2['n_pairs']}**")
        lines.append(f"- claims impliqués : {t2['n_claims_involved']}")
        lines.append("")
        if t2.get("samples"):
            lines.append("**Exemples paires near-dup (cosine) :**")
            for p in t2["samples"][:8]:
                lines.append(f"- cos={p['cos']} | A: « {p['text_a'][:120]} » | B: « {p['text_b'][:120]} »")
            lines.append("")

    if t3:
        lines.append("## Tier 3 — équivalence sémantique (cross-encoder bge-reranker-v2-m3)")
        lines.append(f"- paires évaluées : {t3['_n_evaluated']} / candidates {t3['_n_candidates']} "
                     f"({t3['_elapsed_s']}s)")
        for cat in ("EQUIVALENT", "SUBSUMPTION", "DISTINCT", "GUARDED"):
            lines.append(f"- **{cat}** : {len(t3[cat])}")
        lines.append("")
        lines.append(f"- distribution score reranker (paires cosine≥seuil) : {t3.get('_score_hist')}")
        lines.append("")
        lines.append("> DISTINCT = cosine élevé MAIS reranker bas = faux positifs du cosine pur "
                     "(ce que le Tier 3 nous fait éviter, ex. frères d'énumération). "
                     "GUARDED = aurait été fusionné mais porte un identifiant unique -> protégé.")
        lines.append("")
        for cat in ("EQUIVALENT", "SUBSUMPTION", "DISTINCT", "GUARDED"):
            recs = t3[cat]
            if not recs:
                continue
            lines.append(f"### Exemples — {cat}")
            for r in recs[:6]:
                lines.append(f"- cos={r['cos']} ce={r['ce_score']} (→{r['ce_fwd']}/←{r['ce_bwd']})")
                lines.append(f"  - A: « {r['text_a'][:160]} »")
                lines.append(f"  - B: « {r['text_b'][:160]} »")
                if cat == "GUARDED":
                    lines.append(f"  - identifiants uniques bloquant la fusion : {r.get('unique_ids_in_drop')}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Probe dédup tiered (read-only)")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--limit", type=int, default=None, help="N claims max (smoke)")
    parser.add_argument("--tiers", default="1,2,3", help="ex: '1' ou '1,2' ou '1,2,3'")
    parser.add_argument("--cosine-threshold", type=float, default=0.93)
    parser.add_argument("--dup-threshold", type=float, default=0.95,
                        help="Score cross-encoder ≥ -> doublon/subsumption")
    parser.add_argument("--subsumption-ratio", type=float, default=0.7,
                        help="Ratio longueur min/max < -> subsumption (le plus court inclus)")
    parser.add_argument("--reranker-model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--max-pairs-nli", type=int, default=20000)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    tiers = {int(t) for t in args.tiers.split(",") if t.strip()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger.info("Chargement des claims (tenant=%s, limit=%s)...", args.tenant_id, args.limit)
    claims = load_claims(args.tenant_id, args.limit)
    total = len(claims)
    claims_by_id = {c["claim_id"]: c for c in claims}
    logger.info("Claims chargés : %d", total)
    if total == 0:
        logger.error("Aucun claim — abandon.")
        return

    # Tier 1
    logger.info("Tier 1 — exact/normalisé/fingerprint ...")
    t1 = tier1_exact(claims)
    logger.info("Tier 1 : %d clusters, %d supprimables", t1["merged_clusters"], t1["removable"])

    payload: dict = {
        "generated_at": stamp,
        "config": {
            "tenant_id": args.tenant_id,
            "limit": args.limit,
            "tiers": sorted(tiers),
            "cosine_threshold": args.cosine_threshold,
            "dup_threshold": args.dup_threshold,
            "subsumption_ratio": args.subsumption_ratio,
            "reranker_model": args.reranker_model,
            "embedding_model": EMBEDDING_MODEL,
        },
        "tier1": {k: v for k, v in t1.items() if k != "clusters"},
    }
    # garder clusters pour l'agrégation mais pas dans le JSON volumineux
    tier1_full = t1

    pairs: List[Tuple[int, int, float]] = []
    t3 = None

    if 2 in tiers:
        cache_path = OUT_DIR / f"embeddings_{args.tenant_id}{'_lim'+str(args.limit) if args.limit else ''}.npz"
        if args.no_cache and cache_path.exists():
            cache_path.unlink()
        emb = compute_embeddings(claims, cache_path)
        logger.info("Tier 2 — cosine ≥ %.3f ...", args.cosine_threshold)
        pairs = tier2_cosine(claims, emb, args.cosine_threshold)
        involved = {i for i, _, _ in pairs} | {j for _, j, _ in pairs}
        logger.info("Tier 2 : %d paires, %d claims impliqués", len(pairs), len(involved))
        payload["tier2"] = {
            "n_pairs": len(pairs),
            "n_claims_involved": len(involved),
            "samples": [
                {"cos": round(c, 4),
                 "text_a": claims[i]["text"], "text_b": claims[j]["text"]}
                for i, j, c in pairs[:15]
            ],
        }

    if 3 in tiers and pairs:
        logger.info("Tier 3 — équivalence cross-encoder %s ...", args.reranker_model)
        t3 = tier3_crossencoder(
            claims, pairs,
            args.dup_threshold, args.subsumption_ratio, args.max_pairs_nli,
            args.reranker_model,
        )
        payload["tier3"] = t3
        logger.info(
            "Tier 3 : EQUIVALENT=%d SUBSUMPTION=%d DISTINCT=%d GUARDED=%d",
            len(t3["EQUIVALENT"]), len(t3["SUBSUMPTION"]),
            len(t3["DISTINCT"]), len(t3["GUARDED"]),
        )

    payload["reduction"] = estimate_reduction(total, tier1_full, t3, claims)

    json_path, md_path = write_reports(payload, claims_by_id, stamp)
    red = payload["reduction"]
    logger.info("=" * 60)
    logger.info("RÉDUCTION ESTIMÉE : %d/%d supprimables (%.2f%%) -> %d survivants",
                red["cumulative_removable"], total, red["cumulative_pct"], red["survivors"])
    logger.info("Rapport JSON : %s", json_path)
    logger.info("Rapport MD   : %s", md_path)


if __name__ == "__main__":
    main()
