#!/usr/bin/env python3
"""
poc_wiki_article.py — Génère des articles wiki depuis les evidence packs.

Concept Assembly Engine (Couche 4 OSMOSE) — Phase 2 : Article Generation.
Transforme les evidence packs JSON en articles wiki structurés via
SectionPlanner (déterministe) + ConstrainedGenerator (LLM par section).

Usage :
    docker compose exec app python scripts/poc_wiki_article.py
    docker compose exec app python scripts/poc_wiki_article.py --pack data/poc_wiki/evidence_pack_edpb.json
    docker compose exec app python scripts/poc_wiki_article.py --pack-dir data/poc_wiki/ --output-dir data/poc_wiki/
    docker compose exec app python scripts/poc_wiki_article.py --plan-only
"""

import argparse
import glob
import json
import logging
import os
import re
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("[OSMOSE] poc_wiki_article")


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def find_evidence_packs(pack_path: str | None, pack_dir: str) -> list[str]:
    """Trouve les fichiers evidence pack à traiter."""
    if pack_path:
        if not os.path.exists(pack_path):
            raise FileNotFoundError(f"Pack introuvable : {pack_path}")
        return [pack_path]

    pattern = os.path.join(pack_dir, "evidence_pack_*.json")
    packs = sorted(glob.glob(pattern))
    if not packs:
        raise FileNotFoundError(
            f"Aucun evidence pack trouvé dans {pack_dir}. "
            "Lancez d'abord poc_evidence_pack.py"
        )
    return packs


def process_pack(
    pack_path: str,
    output_dir: str,
    plan_only: bool,
) -> dict:
    """Traite un evidence pack : plan + génération article."""
    from knowbase.wiki.models import EvidencePack
    from knowbase.wiki.section_planner import SectionPlanner

    # Charger le pack
    with open(pack_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pack = EvidencePack.model_validate(data)
    concept_name = pack.concept.canonical_name
    slug = slugify(concept_name)

    logger.info(f"Pack chargé : {concept_name} ({len(pack.units)} units)")

    # Étape 1 : Planification
    planner = SectionPlanner()
    plan = planner.plan(pack)

    plan_path = os.path.join(output_dir, f"article_plan_{slug}.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan.model_dump(), f, indent=2, ensure_ascii=False)
    logger.info(f"Plan sauvegardé : {plan_path}")

    stats = {
        "concept": concept_name,
        "sections": len(plan.sections),
        "units_assigned": plan.total_units_assigned,
        "unassigned": len(plan.unassigned_unit_ids),
    }

    for s in plan.sections:
        logger.info(
            f"  [{s.section_type}] {s.title} — "
            f"{len(s.unit_ids)} units, "
            f"{'déterministe' if s.is_deterministic else 'LLM'}"
        )

    if plan_only:
        logger.info("Mode --plan-only : génération LLM ignorée.")
        return stats

    # Étape 2 : Génération
    from knowbase.wiki.constrained_generator import ConstrainedGenerator

    generator = ConstrainedGenerator()
    article = generator.generate(pack, plan)

    # Sauvegarder JSON
    article_json_path = os.path.join(output_dir, f"article_{slug}.json")
    with open(article_json_path, "w", encoding="utf-8") as f:
        json.dump(article.model_dump(), f, indent=2, ensure_ascii=False)
    logger.info(f"Article JSON : {article_json_path}")

    # Sauvegarder Markdown
    markdown = generator.render_markdown(article)
    article_md_path = os.path.join(output_dir, f"article_{slug}.md")
    with open(article_md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    logger.info(f"Article Markdown : {article_md_path}")

    stats.update({
        "total_citations": article.total_citations,
        "average_confidence": article.average_confidence,
        "gaps": len(article.all_gaps),
    })

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="POC Wiki Article — Concept Assembly Engine Phase 2 (OSMOSE)"
    )
    parser.add_argument(
        "--pack",
        type=str,
        default=None,
        help="Chemin vers un evidence pack JSON spécifique",
    )
    parser.add_argument(
        "--pack-dir",
        type=str,
        default="data/poc_wiki/",
        help="Répertoire contenant les evidence packs (défaut : data/poc_wiki/)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/poc_wiki/",
        help="Répertoire de sortie (défaut : data/poc_wiki/)",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Planification seule, sans appel LLM",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info("POC WIKI ARTICLE — Concept Assembly Engine Phase 2")
    logger.info(f"Mode : {'plan-only' if args.plan_only else 'complet (plan + LLM)'}")
    logger.info("=" * 60)

    try:
        pack_paths = find_evidence_packs(args.pack, args.pack_dir)
    except FileNotFoundError as e:
        logger.error(str(e))
        return

    logger.info(f"Packs à traiter : {len(pack_paths)}")

    start_total = time.time()
    results = []

    for pack_path in pack_paths:
        logger.info(f"\n{'─' * 40}")
        logger.info(f"Fichier : {pack_path}")
        logger.info(f"{'─' * 40}")

        start = time.time()
        try:
            stats = process_pack(pack_path, output_dir, args.plan_only)
            stats["elapsed"] = round(time.time() - start, 1)
            stats["status"] = "OK"
            results.append(stats)
        except Exception as e:
            logger.error(f"ERREUR : {e}", exc_info=True)
            results.append({"concept": pack_path, "status": "ERREUR", "error": str(e)})

    total_elapsed = time.time() - start_total

    logger.info(f"\n{'=' * 60}")
    logger.info("RÉSUMÉ")
    logger.info(f"{'=' * 60}")
    for r in results:
        if r["status"] == "OK":
            logger.info(
                f"  {r['concept']}: {r['sections']} sections, "
                f"{r['units_assigned']} units assignés, "
                f"{r.get('total_citations', '—')} citations, "
                f"confiance={r.get('average_confidence', '—')}, "
                f"{r.get('gaps', '—')} lacunes, "
                f"{r['elapsed']}s"
            )
        else:
            logger.info(f"  {r['concept']}: ERREUR — {r.get('error', '?')}")
    logger.info(f"Durée totale : {total_elapsed:.1f}s")
    logger.info(f"Output : {output_dir}")


if __name__ == "__main__":
    main()
