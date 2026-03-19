"""
Téléchargement du corpus biomédical depuis PubMed Central (PMC).
4 sujets : PCT, CRISPR, PD-1/PD-L1, Microbiome intestinal.
+ requêtes cross-topic pour maximiser le concept linking.

Usage:
    python app/scripts/download_pmc_corpus.py [--max-per-query 25] [--output-dir data/corpus/biomedical]
"""

import argparse
import io
import json
import os
import re
import sys
import time

# Fix encodage Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# Configuration des requêtes
# ---------------------------------------------------------------------------

@dataclass
class SearchQuery:
    """Une requête de recherche PMC."""
    topic: str          # Dossier de destination
    query: str          # Requête PubMed/PMC
    max_results: int = 25
    description: str = ""
    is_cross_topic: bool = False


# --- Requêtes par sujet (reviews et méta-analyses prioritaires) ---

QUERIES: list[SearchQuery] = [
    # ====== PCT (Procalcitonine) ======
    SearchQuery(
        topic="pct",
        query="procalcitonin antibiotic stewardship review",
        max_results=20,
        description="PCT -- Reviews antibiotic stewardship",
    ),
    SearchQuery(
        topic="pct",
        query="procalcitonin sepsis biomarker systematic review",
        max_results=15,
        description="PCT -- Systematic reviews sepsis",
    ),
    SearchQuery(
        topic="pct",
        query="procalcitonin guided antibiotic therapy clinical",
        max_results=15,
        description="PCT -- Essais cliniques guides PCT",
    ),
    SearchQuery(
        topic="pct",
        query="procalcitonin cutoff threshold antibiotic duration",
        max_results=10,
        description="PCT -- Seuils quantitatifs",
    ),
    SearchQuery(
        topic="pct",
        query="procalcitonin meta-analysis antibiotic",
        max_results=10,
        description="PCT -- Meta-analyses",
    ),

    # ====== CRISPR ======
    SearchQuery(
        topic="crispr",
        query="CRISPR Cas9 gene therapy clinical review",
        max_results=20,
        description="CRISPR -- Reviews therapie genique",
    ),
    SearchQuery(
        topic="crispr",
        query="CRISPR gene editing clinical trial results",
        max_results=15,
        description="CRISPR -- Essais cliniques",
    ),
    SearchQuery(
        topic="crispr",
        query="CRISPR sickle cell disease thalassemia",
        max_results=12,
        description="CRISPR -- Drepanocytose / thalassemie",
    ),
    SearchQuery(
        topic="crispr",
        query="CRISPR delivery lipid nanoparticle vivo",
        max_results=10,
        description="CRISPR -- Methodes de delivrance",
    ),
    SearchQuery(
        topic="crispr",
        query="CRISPR off-target effects safety review",
        max_results=10,
        description="CRISPR -- Securite / off-target",
    ),

    # ====== PD-1 / PD-L1 ======
    SearchQuery(
        topic="pd1",
        query="PD-1 PD-L1 checkpoint inhibitor review",
        max_results=20,
        description="PD-1 -- Reviews checkpoint inhibitors",
    ),
    SearchQuery(
        topic="pd1",
        query="anti-PD-1 immunotherapy clinical trial efficacy",
        max_results=15,
        description="PD-1 -- Essais cliniques immunotherapie",
    ),
    SearchQuery(
        topic="pd1",
        query="pembrolizumab nivolumab survival outcome",
        max_results=15,
        description="PD-1 -- Efficacite pembrolizumab/nivolumab",
    ),
    SearchQuery(
        topic="pd1",
        query="PD-L1 biomarker predictive response immunotherapy",
        max_results=12,
        description="PD-1 -- Biomarqueurs predictifs",
    ),
    SearchQuery(
        topic="pd1",
        query="immune checkpoint inhibitor adverse events toxicity",
        max_results=10,
        description="PD-1 -- Toxicite / effets secondaires",
    ),

    # ====== Microbiome intestinal ======
    SearchQuery(
        topic="microbiome",
        query="gut microbiome human health disease review",
        max_results=20,
        description="Microbiome -- Reviews sante/maladie",
    ),
    SearchQuery(
        topic="microbiome",
        query="gut microbiota dysbiosis systematic review",
        max_results=15,
        description="Microbiome -- Systematic reviews dysbiose",
    ),
    SearchQuery(
        topic="microbiome",
        query="fecal microbiota transplantation clinical trial",
        max_results=12,
        description="Microbiome -- FMT essais cliniques",
    ),
    SearchQuery(
        topic="microbiome",
        query="gut brain axis microbiome neurological review",
        max_results=10,
        description="Microbiome -- Axe cerveau-intestin",
    ),
    SearchQuery(
        topic="microbiome",
        query="probiotics prebiotics gut microbiome review",
        max_results=10,
        description="Microbiome -- Probiotiques/prebiotiques",
    ),

    # ====== CROSS-TOPIC (articles-ponts) ======
    SearchQuery(
        topic="cross_crispr_pd1",
        query="CRISPR PD-1 knockout T cell",
        max_results=15,
        description="PONT: CRISPR x PD-1 (knockout PD-1)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_crispr_pd1",
        query="CRISPR CAR-T checkpoint inhibitor",
        max_results=12,
        description="PONT: CRISPR x PD-1 (CAR-T + checkpoint)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_microbiome_pd1",
        query="gut microbiome immunotherapy checkpoint inhibitor response",
        max_results=15,
        description="PONT: Microbiome x PD-1 (reponse immunotherapie)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_microbiome_pd1",
        query="microbiome anti-PD-1 response cancer",
        max_results=10,
        description="PONT: Microbiome x PD-1 (reponse anti-PD-1)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_microbiome_pct",
        query="microbiome sepsis procalcitonin infection",
        max_results=10,
        description="PONT: Microbiome x PCT (sepsis)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_microbiome_pct",
        query="gut microbiota infection biomarker procalcitonin",
        max_results=10,
        description="PONT: Microbiome x PCT (biomarqueurs infection)",
        is_cross_topic=True,
    ),
    SearchQuery(
        topic="cross_crispr_microbiome",
        query="CRISPR microbiome engineering phage",
        max_results=10,
        description="PONT: CRISPR × Microbiome (édition microbiome)",
        is_cross_topic=True,
    ),
]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BIOC_BASE = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"

# Délai entre requêtes (3 req/s sans clé API)
REQUEST_DELAY = 0.4  # secondes


def esearch_pmc(query: str, retmax: int = 25) -> list[str]:
    """Recherche PMC et retourne les PMC IDs."""
    url = f"{EUTILS_BASE}/esearch.fcgi"
    params = {
        "db": "pmc",
        "term": query,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        return ids
    except Exception as e:
        print(f"  [ERREUR] esearch: {e}")
        return []


def fetch_article_bioc(pmc_id: str) -> Optional[dict]:
    """Télécharge un article via BioC JSON API. Retourne le JSON structuré."""
    # Normaliser l'ID
    if not pmc_id.startswith("PMC"):
        pmc_id = f"PMC{pmc_id}"

    url = f"{BIOC_BASE}/BioC_json/{pmc_id}/unicode"
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 404:
            return None  # Article pas en Open Access
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ERREUR] BioC fetch {pmc_id}: {e}")
        return None


def fetch_article_metadata(pmc_id: str) -> dict:
    """Récupère les métadonnées via esummary."""
    url = f"{EUTILS_BASE}/esummary.fcgi"
    params = {
        "db": "pmc",
        "id": pmc_id,
        "retmode": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        article = result.get(str(pmc_id), {})
        return {
            "title": article.get("title", ""),
            "authors": [a.get("name", "") for a in article.get("authors", [])],
            "journal": article.get("fulljournalname", ""),
            "pubdate": article.get("pubdate", ""),
            "doi": article.get("doi", ""),
            "pmcid": f"PMC{pmc_id}",
        }
    except Exception:
        return {"pmcid": f"PMC{pmc_id}"}


# ---------------------------------------------------------------------------
# Conversion BioC JSON → Markdown
# ---------------------------------------------------------------------------

def bioc_to_markdown(bioc_data, metadata: dict) -> str:
    """Convertit les données BioC JSON en markdown structuré.
    bioc_data peut être une list (racine BioC) ou un dict (document unique).
    """
    # BioC retourne une liste à la racine — extraire le premier élément
    if isinstance(bioc_data, list):
        if not bioc_data:
            return ""
        bioc_data = bioc_data[0]

    lines: list[str] = []

    # Titre — extraire depuis BioC front matter si pas dans metadata
    title = metadata.get("title", "")
    if not title:
        # Chercher dans les passages front
        for doc in bioc_data.get("documents", []):
            for passage in doc.get("passages", []):
                infons = passage.get("infons", {})
                if infons.get("type") == "front" and infons.get("section_type") == "TITLE":
                    title = passage.get("text", "Untitled")
                    break
            if title:
                break
    if not title:
        title = "Untitled"

    lines.append(f"# {title}")
    lines.append("")

    # Métadonnées — enrichir depuis BioC si esummary n'a pas tout
    authors = metadata.get("authors", [])
    if not authors:
        # Extraire depuis BioC infons (name_0, name_1, ...)
        for doc in bioc_data.get("documents", []):
            for passage in doc.get("passages", []):
                infons = passage.get("infons", {})
                if infons.get("type") == "front":
                    for key, val in infons.items():
                        if key.startswith("name_"):
                            # Format: "surname:Doe;given-names:John"
                            parts = dict(p.split(":", 1) for p in val.split(";") if ":" in p)
                            name = f"{parts.get('given-names', '')} {parts.get('surname', '')}".strip()
                            if name:
                                authors.append(name)
                    break
            if authors:
                break

    if authors:
        lines.append(f"**Authors:** {', '.join(authors[:10])}")
        if len(authors) > 10:
            lines[-1] += f" et al. ({len(authors)} authors)"

    journal = metadata.get("journal", "")
    pubdate = metadata.get("pubdate", "")
    doi = metadata.get("doi", "")
    pmcid = metadata.get("pmcid", "")

    if journal:
        lines.append(f"**Journal:** {journal}")
    if pubdate:
        lines.append(f"**Published:** {pubdate}")
    if doi:
        lines.append(f"**DOI:** {doi}")
    if pmcid:
        lines.append(f"**PMC ID:** {pmcid}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Corps de l'article
    documents = bioc_data.get("documents", [])
    if not documents:
        return "\n".join(lines) + "\n*No full text available.*\n"

    current_section = ""
    MAJOR_SECTIONS = {"ABSTRACT", "INTRO", "METHODS", "RESULTS",
                      "DISCUSS", "CONCL", "CONCLUSIONS", "CASE",
                      "BACKGROUND", "FINDINGS", "MATERIALS"}

    for doc in documents:
        for passage in doc.get("passages", []):
            infons = passage.get("infons", {})
            section_type = infons.get("section_type", "")
            ptype = infons.get("type", "")
            text = passage.get("text", "").strip()

            if not text:
                continue

            # Skip front matter (déjà dans les métadonnées)
            if ptype == "front":
                continue

            # Déterminer si c'est un titre (title, title_1, title_2, abstract_title_1, etc.)
            is_title = "title" in ptype and ptype != "front"

            if is_title:
                if section_type in MAJOR_SECTIONS:
                    lines.append(f"## {text}")
                else:
                    lines.append(f"### {text}")
                lines.append("")
                current_section = section_type
                continue

            # Texte normal (paragraph, abstract, list, table, etc.)
            lines.append(text)
            lines.append("")

    return "\n".join(lines)


def slugify(text: str) -> str:
    """Crée un slug à partir d'un titre."""
    text = text.lower().strip()
    # Supprimer les caractères spéciaux
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '_', text)
    text = re.sub(r'-+', '_', text)
    # Tronquer à 80 chars
    return text[:80].rstrip('_')


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def download_corpus(output_dir: str, max_per_query: Optional[int] = None):
    """Télécharge le corpus biomédical complet."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Stats globales
    all_pmc_ids: set[str] = set()  # Pour déduplication globale
    stats = {
        "total_downloaded": 0,
        "total_skipped_dup": 0,
        "total_skipped_no_oa": 0,
        "total_errors": 0,
        "by_topic": {},
    }

    print("=" * 70)
    print("TÉLÉCHARGEMENT CORPUS BIOMÉDICAL — PubMed Central")
    print(f"Répertoire de sortie : {output_path.absolute()}")
    print(f"Nombre de requêtes : {len(QUERIES)}")
    print("=" * 70)

    for qi, sq in enumerate(QUERIES, 1):
        effective_max = max_per_query if max_per_query else sq.max_results
        topic_dir = output_path / sq.topic
        topic_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{qi}/{len(QUERIES)}] {sq.description}")
        print(f"  Requête : {sq.query[:80]}...")
        print(f"  Max résultats : {effective_max}")

        # Recherche
        pmc_ids = esearch_pmc(sq.query, retmax=effective_max)
        print(f"  → {len(pmc_ids)} résultats PMC")
        time.sleep(REQUEST_DELAY)

        topic_count = 0
        for i, pmc_id in enumerate(pmc_ids):
            # Déduplication globale
            if pmc_id in all_pmc_ids:
                stats["total_skipped_dup"] += 1
                continue
            all_pmc_ids.add(pmc_id)

            # Vérifier si déjà téléchargé (reprise)
            existing = list(topic_dir.glob(f"PMC{pmc_id}_*.md"))
            if existing:
                print(f"  [{i+1}/{len(pmc_ids)}] PMC{pmc_id} — déjà téléchargé, skip")
                topic_count += 1
                stats["total_downloaded"] += 1
                continue

            # Métadonnées
            metadata = fetch_article_metadata(pmc_id)
            time.sleep(REQUEST_DELAY)

            # Téléchargement BioC
            bioc_data = fetch_article_bioc(pmc_id)
            time.sleep(REQUEST_DELAY)

            if bioc_data is None:
                print(f"  [{i+1}/{len(pmc_ids)}] PMC{pmc_id} — pas en Open Access, skip")
                stats["total_skipped_no_oa"] += 1
                continue

            # Conversion en markdown
            try:
                markdown = bioc_to_markdown(bioc_data, metadata)
            except Exception as e:
                print(f"  [{i+1}/{len(pmc_ids)}] PMC{pmc_id} — erreur conversion: {e}")
                stats["total_errors"] += 1
                continue

            # Vérifier que l'article a du contenu substantiel
            word_count = len(markdown.split())
            if word_count < 200:
                print(f"  [{i+1}/{len(pmc_ids)}] PMC{pmc_id} — trop court ({word_count} mots), skip")
                stats["total_skipped_no_oa"] += 1
                continue

            # Sauvegarder
            title_slug = slugify(metadata.get("title", "untitled"))
            filename = f"PMC{pmc_id}_{title_slug}.md"
            filepath = topic_dir / filename

            filepath.write_text(markdown, encoding="utf-8")
            topic_count += 1
            stats["total_downloaded"] += 1

            title_short = metadata.get("title", "?")[:60]
            print(f"  [{i+1}/{len(pmc_ids)}] PMC{pmc_id} — ✓ {word_count} mots — {title_short}...")

        # Stats par topic
        topic_key = sq.topic
        if topic_key not in stats["by_topic"]:
            stats["by_topic"][topic_key] = 0
        stats["by_topic"][topic_key] += topic_count

    # Résumé final
    print("\n" + "=" * 70)
    print("RÉSUMÉ")
    print("=" * 70)
    print(f"Articles téléchargés : {stats['total_downloaded']}")
    print(f"Doublons ignorés    : {stats['total_skipped_dup']}")
    print(f"Non Open Access     : {stats['total_skipped_no_oa']}")
    print(f"Erreurs             : {stats['total_errors']}")
    print()
    print("Par sujet :")
    for topic, count in sorted(stats["by_topic"].items()):
        print(f"  {topic:30s} : {count} articles")
    print()

    # Sauvegarder les stats
    stats_file = output_path / "download_stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"Stats sauvegardées : {stats_file}")

    # Sauvegarder la liste des PMC IDs pour traçabilité
    ids_file = output_path / "pmc_ids.txt"
    with open(ids_file, "w") as f:
        for pid in sorted(all_pmc_ids):
            f.write(f"PMC{pid}\n")
    print(f"Liste IDs          : {ids_file}")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge le corpus biomédical depuis PMC")
    parser.add_argument(
        "--output-dir",
        default="data/corpus/biomedical",
        help="Répertoire de sortie (défaut: data/corpus/biomedical)",
    )
    parser.add_argument(
        "--max-per-query",
        type=int,
        default=None,
        help="Limite max par requête (écrase les defaults individuels)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les requêtes sans télécharger",
    )

    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN — Requêtes prévues ===\n")
        total = 0
        for i, sq in enumerate(QUERIES, 1):
            n = args.max_per_query or sq.max_results
            tag = " [CROSS-TOPIC]" if sq.is_cross_topic else ""
            print(f"[{i:2d}] {sq.topic:30s} max={n:3d}  {sq.description}{tag}")
            total += n
        print(f"\nTotal max articles : {total}")
        print(f"(avec déduplication, le nombre réel sera inférieur)")
    else:
        download_corpus(args.output_dir, args.max_per_query)
