#!/usr/bin/env python3
"""
Telechargement du corpus preeclampsie — structure par controverses cliniques.

10 clusters de controverses, chacun avec des etudes qui se referencent,
se contredisent et s'enchainent. Optimise pour maximiser les cross-docs
et les tensions detectables par OSMOSIS.

Usage :
    python app/scripts/download_preeclampsia_corpus.py --output data/burst/PreEclampsia --max 200
    python app/scripts/download_preeclampsia_corpus.py --dry-run
    python app/scripts/download_preeclampsia_corpus.py --cluster 1  # Un seul cluster

Note : NCBI rate-limit a 3 req/s sans API key, 10 req/s avec.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CORPUS] %(message)s")
logger = logging.getLogger("corpus-downloader")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
RATE_DELAY = 0.35 if NCBI_API_KEY else 1.1


# ═══════════════════════════════════════════════════════════════════════════════
# 10 Clusters de controverses cliniques
# ═══════════════════════════════════════════════════════════════════════════════

CLUSTERS = [
    # ── Cluster 1 : La guerre du dosage aspirine ──────────────────────
    {
        "id": 1,
        "name": "Aspirin dosage controversy",
        "prefix": "ASP",
        "target": 20,
        "description": "CLASP 1994 (inefficace) → ASPRE 2017 (150mg) → NICE/FIGO → ASAPP 2024 (162mg vs 81mg)",
        "queries": [
            # Etudes anciennes contradictoires
            '("CLASP" OR "Collaborative Low-dose Aspirin") AND preeclampsia AND aspirin',
            # ASPRE trial (reference)
            '("ASPRE" OR "Combined Multimarker Screening and Randomized Patient Treatment") AND aspirin AND preeclampsia AND "150 mg"',
            # Comparaison dosages
            '(preeclampsia OR pre-eclampsia) AND aspirin AND ("81 mg" OR "150 mg" OR "162 mg") AND (dose OR dosage OR comparison) AND "open access"[filter]',
            # Meta-analyses aspirine
            '(preeclampsia OR pre-eclampsia) AND aspirin AND prevention AND ("systematic review"[pt] OR "meta-analysis"[pt]) AND "open access"[filter]',
            # Timing aspirine (avant/apres 16 SA)
            '(preeclampsia OR pre-eclampsia) AND aspirin AND ("gestational age" OR timing OR "16 weeks" OR "first trimester") AND prevention AND "open access"[filter]',
            # Risque hemorragique
            '(preeclampsia OR pre-eclampsia) AND aspirin AND (bleeding OR "placental abruption" OR safety OR "adverse effect") AND "open access"[filter]',
        ],
    },
    # ── Cluster 2 : PlGF seul vs ratio sFlt-1/PlGF ───────────────────
    {
        "id": 2,
        "name": "PlGF alone vs sFlt-1/PlGF ratio",
        "prefix": "RAT",
        "target": 20,
        "description": "PROGNOSIS (ratio 38) vs NICE (PlGF seul) vs Kryptor (autres seuils)",
        "queries": [
            # PROGNOSIS study (Roche, seuil 38)
            '("PROGNOSIS" OR "Prediction of Short-Term Outcome") AND (sFlt-1 OR PlGF) AND preeclampsia',
            # PlGF seul (approche UK)
            '(preeclampsia OR pre-eclampsia) AND "PlGF" AND (alone OR "single marker" OR triage) AND (diagnosis OR prediction) AND "open access"[filter]',
            # Ratio sFlt-1/PlGF (approche EU)
            '(preeclampsia OR pre-eclampsia) AND "sFlt-1/PlGF" AND (ratio OR cutoff OR threshold) AND "open access"[filter]',
            # Kryptor vs Elecsys (head-to-head)
            '(preeclampsia OR pre-eclampsia) AND (Kryptor OR Elecsys OR BRAHMS OR Roche) AND (sFlt-1 OR PlGF) AND (comparison OR validation) AND "open access"[filter]',
            # Revues systematiques sur les seuils
            '(preeclampsia OR pre-eclampsia) AND (sFlt-1 OR PlGF) AND (threshold OR "cut-off" OR "rule-out" OR "rule-in") AND "open access"[filter]',
        ],
    },
    # ── Cluster 3 : FMF screening vs ACOG risk factors ────────────────
    {
        "id": 3,
        "name": "FMF algorithm vs ACOG screening",
        "prefix": "SCR",
        "target": 20,
        "description": "Combined T1 screening (FMF) vs risk factor checklist (ACOG)",
        "queries": [
            # FMF algorithm (Nicolaides)
            '("Fetal Medicine Foundation" OR FMF) AND preeclampsia AND (screening OR prediction OR algorithm) AND "first trimester" AND "open access"[filter]',
            # ACOG risk factors
            '(preeclampsia OR pre-eclampsia) AND (ACOG OR "American College") AND ("risk factor" OR screening OR guideline) AND "open access"[filter]',
            # PAPP-A + uterine artery Doppler
            '(preeclampsia OR pre-eclampsia) AND (PAPP-A OR "pregnancy-associated plasma protein") AND ("uterine artery" OR doppler) AND prediction AND "open access"[filter]',
            # Comparaison approches
            '(preeclampsia OR pre-eclampsia) AND ("first trimester screening" OR "combined screening") AND (performance OR "detection rate" OR comparison) AND "open access"[filter]',
            # MAP (mean arterial pressure) en screening
            '(preeclampsia OR pre-eclampsia) AND ("mean arterial pressure" OR MAP) AND screening AND "first trimester" AND "open access"[filter]',
        ],
    },
    # ── Cluster 4 : Definition de la preeclampsie ─────────────────────
    {
        "id": 4,
        "name": "Preeclampsia definition controversy",
        "prefix": "DEF",
        "target": 15,
        "description": "ISSHP 2018 vs ACOG 2020 vs NICE 2019 — proteinurie obligatoire ?",
        "queries": [
            # ISSHP definition
            '(ISSHP OR "International Society for the Study of Hypertension in Pregnancy") AND preeclampsia AND (definition OR classification OR criteria) AND "open access"[filter]',
            # Definitions et classifications
            '(preeclampsia OR pre-eclampsia) AND (definition OR classification OR diagnostic criteria) AND (review OR consensus) AND "open access"[filter]',
            # PE sans proteinurie
            '(preeclampsia OR pre-eclampsia) AND ("without proteinuria" OR "non-proteinuric" OR "atypical") AND "open access"[filter]',
            # Hypertensive disorders classification
            '("hypertensive disorders of pregnancy" OR "gestational hypertension") AND classification AND (preeclampsia OR pre-eclampsia) AND "open access"[filter]',
        ],
    },
    # ── Cluster 5 : Delivery timing ───────────────────────────────────
    {
        "id": 5,
        "name": "Delivery timing controversy",
        "prefix": "DEL",
        "target": 15,
        "description": "HYPITAT-II (expectatif) vs PHOENIX (PlGF-guided) vs seuils 34/37 SA",
        "queries": [
            # HYPITAT trials
            '(HYPITAT OR "Hypertension and Pre-Eclampsia Intervention Trial At Term") AND preeclampsia AND delivery AND "open access"[filter]',
            # PHOENIX trial
            '(PHOENIX OR "Placental Growth Factor to Assess and Manage") AND preeclampsia AND delivery AND "open access"[filter]',
            # Timing delivery PE precoce
            '(preeclampsia OR pre-eclampsia) AND ("timing of delivery" OR "expectant management" OR "planned delivery") AND ("early onset" OR preterm) AND "open access"[filter]',
            # PlGF-guided management
            '(preeclampsia OR pre-eclampsia) AND PlGF AND (management OR "clinical decision" OR "guided delivery") AND "open access"[filter]',
        ],
    },
    # ── Cluster 6 : MgSO4 protocoles ─────────────────────────────────
    {
        "id": 6,
        "name": "MgSO4 protocols controversy",
        "prefix": "MGS",
        "target": 15,
        "description": "Magpie Trial → Zuspan vs Pritchard → duree optimale",
        "queries": [
            # Magpie Trial
            '("Magpie Trial" OR "magnesium sulphate" OR "magnesium sulfate") AND (eclampsia OR preeclampsia) AND ("clinical trial"[pt]) AND "open access"[filter]',
            # Zuspan vs Pritchard
            '("magnesium sulfate" OR "magnesium sulphate") AND (Zuspan OR Pritchard) AND (protocol OR regimen OR comparison) AND preeclampsia AND "open access"[filter]',
            # Duree traitement
            '("magnesium sulfate" OR "magnesium sulphate") AND preeclampsia AND (duration OR "postpartum" OR "maintenance dose") AND "open access"[filter]',
        ],
    },
    # ── Cluster 7 : Biomarqueurs emergents vs etablis ─────────────────
    {
        "id": 7,
        "name": "Emerging vs established biomarkers",
        "prefix": "EMB",
        "target": 20,
        "description": "sFlt-1/PlGF (standard) vs cfDNA, PP13, ADAM12, machine learning",
        "queries": [
            # Cell-free DNA/RNA
            '(preeclampsia OR pre-eclampsia) AND ("cell-free DNA" OR "cell-free RNA" OR cfDNA OR "liquid biopsy") AND (prediction OR biomarker) AND "open access"[filter]',
            # PP13, ADAM12 (biomarqueurs abandonnes?)
            '(preeclampsia OR pre-eclampsia) AND (PP13 OR ADAM12 OR "placental protein 13") AND (biomarker OR prediction) AND "open access"[filter]',
            # Multi-biomarqueurs et combinaisons
            '(preeclampsia OR pre-eclampsia) AND ("multi-marker" OR "combined biomarker" OR "multivariate") AND prediction AND "open access"[filter]',
            # Machine learning / IA prediction
            '(preeclampsia OR pre-eclampsia) AND ("machine learning" OR "artificial intelligence" OR "deep learning") AND prediction AND "open access"[filter]',
            # NT-proBNP et biomarqueurs cardiaques
            '(preeclampsia OR pre-eclampsia) AND ("NT-proBNP" OR troponin OR "cardiac biomarker") AND "open access"[filter]',
        ],
    },
    # ── Cluster 8 : PE precoce vs tardive ─────────────────────────────
    {
        "id": 8,
        "name": "Early-onset vs late-onset: two diseases?",
        "prefix": "ELO",
        "target": 20,
        "description": "Hypothese des 2 entites → physiopathologies → biomarqueurs → management differents",
        "queries": [
            # Early vs late onset
            '(preeclampsia OR pre-eclampsia) AND ("early-onset" OR "late-onset" OR "early onset" OR "late onset") AND (pathophysiology OR mechanism OR comparison) AND "open access"[filter]',
            # Placental vs maternal PE
            '(preeclampsia OR pre-eclampsia) AND ("placental" OR "maternal") AND (subtype OR phenotype OR "two-stage") AND "open access"[filter]',
            # Biomarqueurs differents selon le type
            '(preeclampsia OR pre-eclampsia) AND ("early-onset" OR "late-onset") AND (biomarker OR sFlt-1 OR PlGF) AND (difference OR comparison) AND "open access"[filter]',
            # Physiopathologie revues recentes
            '(preeclampsia OR pre-eclampsia) AND (pathophysiology OR pathogenesis) AND ("endothelial dysfunction" OR angiogenesis OR "oxidative stress") AND review[pt] AND "open access"[filter]',
        ],
    },
    # ── Cluster 9 : Calcium et supplementation ────────────────────────
    {
        "id": 9,
        "name": "Calcium supplementation controversy",
        "prefix": "CAL",
        "target": 15,
        "description": "WHO recommande vs ACOG ne recommande pas, contexte geographique",
        "queries": [
            # Calcium et PE
            '(preeclampsia OR pre-eclampsia) AND (calcium OR "calcium supplementation") AND prevention AND "open access"[filter]',
            # WHO guidelines calcium
            '(preeclampsia OR pre-eclampsia) AND calcium AND (WHO OR "World Health Organization" OR guideline) AND "open access"[filter]',
            # Etudes par population (pays en developpement)
            '(preeclampsia OR pre-eclampsia) AND calcium AND ("low income" OR "developing country" OR Africa OR "low calcium intake") AND "open access"[filter]',
        ],
    },
    # ── Cluster 10 : PE et risque cardiovasculaire long-terme ─────────
    {
        "id": 10,
        "name": "PE and long-term cardiovascular risk",
        "prefix": "CVR",
        "target": 20,
        "description": "PE → risque CV x4 → suivi recommande mais peu fait → guidelines AHA/ESC",
        "queries": [
            # PE et risque CV
            '(preeclampsia OR pre-eclampsia) AND ("cardiovascular risk" OR "cardiovascular disease" OR "long-term outcome") AND (postpartum OR "follow-up") AND "open access"[filter]',
            # Hypertension post-PE
            '(preeclampsia OR pre-eclampsia) AND (hypertension OR "chronic hypertension") AND ("long term" OR "years after" OR "future risk") AND "open access"[filter]',
            # AHA/ESC guidelines
            '(preeclampsia OR pre-eclampsia) AND ("American Heart Association" OR AHA OR ESC OR "European Society of Cardiology") AND "cardiovascular" AND "open access"[filter]',
            # Suivi post-partum
            '(preeclampsia OR pre-eclampsia) AND ("postpartum follow-up" OR "postnatal care" OR "postpartum surveillance") AND cardiovascular AND "open access"[filter]',
            # HELLP et consequences long-terme
            '("HELLP syndrome" OR (preeclampsia AND severe)) AND ("long-term" OR outcome OR "years after") AND "open access"[filter]',
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Fonctions NCBI
# ═══════════════════════════════════════════════════════════════════════════════


def _api_params() -> dict:
    p = {"retmode": "json"}
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    return p


def search_pmc(query: str, max_results: int = 20) -> list[str]:
    params = {**_api_params(), "db": "pmc", "term": query, "retmax": max_results, "sort": "relevance"}
    try:
        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        count = data.get("esearchresult", {}).get("count", "0")
        logger.info(f"    Search: {count} total, {len(ids)} returned")
        return ids
    except Exception as e:
        logger.error(f"    Search failed: {e}")
        return []


def fetch_metadata(pmc_ids: list[str]) -> list[dict]:
    if not pmc_ids:
        return []
    params = {**_api_params(), "db": "pmc", "id": ",".join(pmc_ids)}
    try:
        resp = requests.get(f"{EUTILS_BASE}/esummary.fcgi", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for uid, info in data.get("result", {}).items():
            if uid == "uids":
                continue
            results.append({
                "pmc_id": f"PMC{uid}",
                "title": info.get("title", ""),
                "source": info.get("source", ""),
                "pubdate": info.get("pubdate", ""),
            })
        return results
    except Exception as e:
        logger.error(f"    Metadata failed: {e}")
        return []


def download_pdf(pmc_id: str, output_path: Path) -> bool:
    """Telecharge le PDF via l'API OA (tar.gz FTP) puis fallback Europe PMC."""
    import io
    import tarfile

    # Methode 1 : API OA → FTP tar.gz → extraire le PDF
    try:
        oa_resp = requests.get(
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmc_id}",
            timeout=15,
        )
        if oa_resp.status_code == 200:
            ftp_match = re.search(r'href="(ftp://[^"]+\.tar\.gz)"', oa_resp.text)
            if ftp_match:
                https_url = ftp_match.group(1).replace(
                    "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/",
                    "https://ftp.ncbi.nlm.nih.gov/pub/pmc/",
                )
                resp = requests.get(https_url, timeout=120, headers={
                    "User-Agent": "OSMOSIS-Corpus-Builder/1.0 (mailto:fredpottier@gmail.com)"
                })
                if resp.status_code == 200 and len(resp.content) > 1000:
                    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
                        for member in tar.getmembers():
                            if member.name.lower().endswith(".pdf"):
                                pdf_file = tar.extractfile(member)
                                if pdf_file:
                                    pdf_content = pdf_file.read()
                                    if pdf_content[:5].startswith(b"%PDF") and len(pdf_content) > 10000:
                                        output_path.write_bytes(pdf_content)
                                        return True
    except Exception:
        pass

    # Methode 2 : Europe PMC direct
    try:
        url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_id}&blobtype=pdf"
        resp = requests.get(url, timeout=60, headers={
            "User-Agent": "OSMOSIS-Corpus-Builder/1.0 (mailto:fredpottier@gmail.com)"
        })
        if resp.status_code == 200 and resp.content[:5].startswith(b"%PDF") and len(resp.content) > 10000:
            output_path.write_bytes(resp.content)
            return True
    except Exception:
        pass

    return False


def sanitize(title: str, max_len: int = 70) -> str:
    clean = re.sub(r'[<>:"/\\|?*\'\u2019\u2018\u201c\u201d]', '', title)
    clean = re.sub(r'\s+', '_', clean).strip('_')
    clean = re.sub(r'[^\w\-.]', '', clean)
    return clean[:max_len]


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


def build_corpus(
    output_dir: Path,
    max_total: int = 200,
    dry_run: bool = False,
    cluster_filter: int | None = None,
):
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    total_downloaded = 0
    total_failed = 0
    seen_ids: set[str] = set()

    clusters_to_process = CLUSTERS
    if cluster_filter is not None:
        clusters_to_process = [c for c in CLUSTERS if c["id"] == cluster_filter]

    for cluster in clusters_to_process:
        if total_downloaded >= max_total:
            break

        cid = cluster["id"]
        prefix = cluster["prefix"]
        target = cluster["target"]
        name = cluster["name"]

        logger.info(f"\n{'='*70}")
        logger.info(f"CLUSTER {cid}: {name} (target: {target} docs)")
        logger.info(f"  {cluster['description']}")

        cluster_downloaded = 0
        cluster_ids: list[str] = []

        # Collecter les IDs de toutes les sous-requetes du cluster
        for qi, query in enumerate(cluster["queries"]):
            if cluster_downloaded >= target:
                break

            remaining = target - cluster_downloaded
            logger.info(f"  Query {qi+1}/{len(cluster['queries'])}: {query[:70]}...")

            time.sleep(RATE_DELAY)
            pmc_ids = search_pmc(query, max_results=min(remaining + 5, 30))

            # Deduplication globale
            new_ids = [pid for pid in pmc_ids if pid not in seen_ids]
            seen_ids.update(pmc_ids)
            cluster_ids.extend(new_ids)

        # Deduplicate cluster_ids
        cluster_ids = list(dict.fromkeys(cluster_ids))[:target]
        logger.info(f"  → {len(cluster_ids)} unique IDs for cluster {cid}")

        if not cluster_ids:
            continue

        # Fetch metadata en batch
        time.sleep(RATE_DELAY)
        all_meta = fetch_metadata(cluster_ids)

        # Download
        for meta in all_meta:
            if total_downloaded >= max_total or cluster_downloaded >= target:
                break

            pmc_id = meta["pmc_id"]
            title = meta.get("title", "untitled")
            year = meta.get("pubdate", "")[:4] or "XXXX"

            idx = total_downloaded + 1
            filename = f"{prefix}_{idx:03d}_{year}_{sanitize(title)}.pdf"
            filepath = output_dir / filename

            if dry_run:
                logger.info(f"  DRY: {pmc_id} | {year} | {title[:55]}")
                manifest.append({
                    **meta, "cluster": cid, "cluster_name": name,
                    "filename": filename, "status": "dry_run",
                })
                total_downloaded += 1
                cluster_downloaded += 1
                continue

            if filepath.exists():
                total_downloaded += 1
                cluster_downloaded += 1
                continue

            time.sleep(RATE_DELAY)
            if download_pdf(pmc_id, filepath):
                size_kb = filepath.stat().st_size // 1024
                logger.info(f"  OK [{cluster_downloaded+1}/{target}]: {filename[:50]} ({size_kb}KB)")
                manifest.append({
                    **meta, "cluster": cid, "cluster_name": name,
                    "filename": filename, "status": "ok", "size_kb": size_kb,
                })
                total_downloaded += 1
                cluster_downloaded += 1
            else:
                logger.warning(f"  FAIL: {pmc_id}")
                manifest.append({
                    **meta, "cluster": cid, "cluster_name": name,
                    "filename": filename, "status": "failed",
                })
                total_failed += 1

        logger.info(f"  Cluster {cid} done: {cluster_downloaded}/{target}")

    # Manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_downloaded": total_downloaded,
            "total_failed": total_failed,
            "clusters": [{
                "id": c["id"], "name": c["name"], "prefix": c["prefix"],
                "target": c["target"], "description": c["description"],
            } for c in clusters_to_process],
            "articles": manifest,
        }, f, indent=2, ensure_ascii=False)

    # Summary par cluster
    logger.info(f"\n{'='*70}")
    logger.info(f"SUMMARY")
    from collections import Counter
    by_cluster = Counter(a["cluster"] for a in manifest if a.get("status") in ("ok", "dry_run"))
    for c in clusters_to_process:
        count = by_cluster.get(c["id"], 0)
        logger.info(f"  Cluster {c['id']:2d} [{c['prefix']}] {c['name'][:40]:40s} {count}/{c['target']}")
    logger.info(f"  TOTAL: {total_downloaded} downloaded, {total_failed} failed")
    logger.info(f"  Manifest: {manifest_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download preeclampsia corpus from PMC")
    parser.add_argument("--output", default="data/burst/PreEclampsia")
    parser.add_argument("--max", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cluster", type=int, default=None, help="Download only one cluster (1-10)")
    args = parser.parse_args()

    build_corpus(Path(args.output), max_total=args.max, dry_run=args.dry_run, cluster_filter=args.cluster)
