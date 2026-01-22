#!/usr/bin/env python3
"""
SCOPE Mining Analysis - Dry Run Script
=======================================

Script d'analyse pour valider le pipeline SCOPE avant intégration dans Pass 2.

Ce script:
1. Mine les CandidatePairs sur toutes les sections (ou un échantillon)
2. Vérifie avec le LLM (Claude 3 Haiku)
3. Génère un rapport d'analyse SANS écrire en base

Usage:
    # Depuis le container app
    python scripts/scope_analysis_dryrun.py --sample 50
    python scripts/scope_analysis_dryrun.py --all --output data/scope_report.json

Ref: doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from neo4j import GraphDatabase

from knowbase.relations.scope_candidate_miner import (
    ScopeCandidateMiner,
    get_mining_stats,
)
from knowbase.relations.scope_verifier import (
    ScopeVerifier,
    candidate_to_raw_assertion,
)
from knowbase.relations.types import (
    DiscursiveAbstainReason,
    RelationType,
    ScopeMiningConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data classes pour le rapport
# =============================================================================

@dataclass
class AssertedRelation:
    """Relation validée par le verifier."""
    subject: str
    object: str
    relation_type: str
    direction: str
    confidence: float
    marker: Optional[str]
    section_id: str
    document_id: str
    scope_setter_text: str


@dataclass
class AbstainedCandidate:
    """Candidat rejeté par le verifier."""
    pivot: str
    other: str
    reason: str
    justification: Optional[str]
    section_id: str


@dataclass
class SectionReport:
    """Rapport pour une section."""
    section_id: str
    document_id: str
    doc_items: int
    concepts: int
    candidates_mined: int
    asserted: int
    abstained: int
    abstain_reasons: Dict[str, int] = field(default_factory=dict)


@dataclass
class AnalysisReport:
    """Rapport complet de l'analyse SCOPE."""
    # Metadata
    timestamp: str
    config: Dict

    # Stats globales
    sections_processed: int = 0
    total_doc_items: int = 0
    total_concepts: int = 0
    total_candidates: int = 0
    total_asserted: int = 0
    total_abstained: int = 0

    # Taux
    abstain_rate: float = 0.0

    # Distribution des raisons d'ABSTAIN
    abstain_reasons_distribution: Dict[str, int] = field(default_factory=dict)

    # Distribution des types de relations
    relation_types_distribution: Dict[str, int] = field(default_factory=dict)

    # Détails
    section_reports: List[SectionReport] = field(default_factory=list)
    asserted_relations: List[AssertedRelation] = field(default_factory=list)
    sample_abstained: List[AbstainedCandidate] = field(default_factory=list)


# =============================================================================
# Fonctions principales
# =============================================================================

def get_sections_to_process(driver, tenant_id: str, sample_size: Optional[int] = None) -> List[str]:
    """Récupère les sections à traiter."""
    query = """
    MATCH (sc:SectionContext {tenant_id: $tenant_id})
    MATCH (sc)-[:CONTAINS]->(di:DocItem)
    MATCH (pc:ProtoConcept)-[:ANCHORED_IN]->(di)
    WITH sc, count(DISTINCT pc) as concept_count
    WHERE concept_count >= 2
    RETURN sc.context_id as section_id
    ORDER BY concept_count DESC
    """

    if sample_size:
        query += f" LIMIT {sample_size}"

    with driver.session() as session:
        result = session.run(query, tenant_id=tenant_id)
        return [r["section_id"] for r in result]


async def analyze_section(
    section_id: str,
    miner: ScopeCandidateMiner,
    verifier: ScopeVerifier,
    report: AnalysisReport,
    collect_details: bool = True,
) -> SectionReport:
    """Analyse une section et met à jour le rapport."""

    # 1. Mining
    mining_result = miner.mine_section(section_id)
    candidates = mining_result.candidates

    section_report = SectionReport(
        section_id=section_id,
        document_id=mining_result.candidates[0].document_id if candidates else "",
        doc_items=mining_result.stats.get("doc_items", 0),
        concepts=mining_result.stats.get("concepts", 0),
        candidates_mined=len(candidates),
        asserted=0,
        abstained=0,
    )

    if not candidates:
        return section_report

    # 2. Verification
    batch_result = await verifier.verify_batch(candidates, max_concurrent=3)

    section_report.asserted = batch_result.asserted
    section_report.abstained = batch_result.abstained

    # 3. Collecter les détails
    for cand, vr in zip(candidates, batch_result.results):
        if vr.verdict == "ASSERT":
            # Relation validée
            report.relation_types_distribution[vr.relation_type.value] = \
                report.relation_types_distribution.get(vr.relation_type.value, 0) + 1

            if collect_details:
                bundle = cand.evidence_bundle
                setter = bundle.get_scope_setter()

                report.asserted_relations.append(AssertedRelation(
                    subject=cand.pivot_surface_form if vr.direction == "A_TO_B" else cand.other_surface_form,
                    object=cand.other_surface_form if vr.direction == "A_TO_B" else cand.pivot_surface_form,
                    relation_type=vr.relation_type.value,
                    direction=vr.direction,
                    confidence=vr.confidence,
                    marker=vr.marker_found,
                    section_id=section_id,
                    document_id=cand.document_id,
                    scope_setter_text=setter.text_excerpt[:200] if setter else "",
                ))
        else:
            # ABSTAIN
            reason_str = vr.abstain_reason.value if vr.abstain_reason else "UNKNOWN"
            section_report.abstain_reasons[reason_str] = \
                section_report.abstain_reasons.get(reason_str, 0) + 1
            report.abstain_reasons_distribution[reason_str] = \
                report.abstain_reasons_distribution.get(reason_str, 0) + 1

            # Garder un échantillon des ABSTAIN
            if collect_details and len(report.sample_abstained) < 50:
                report.sample_abstained.append(AbstainedCandidate(
                    pivot=cand.pivot_surface_form,
                    other=cand.other_surface_form,
                    reason=reason_str,
                    justification=vr.abstain_justification,
                    section_id=section_id,
                ))

    return section_report


async def run_analysis(
    driver,
    tenant_id: str,
    sample_size: Optional[int],
    config: ScopeMiningConfig,
    max_pairs_per_section: int = 20,
) -> AnalysisReport:
    """Exécute l'analyse complète."""

    # Modifier la config pour le test
    config.max_pairs_per_scope = max_pairs_per_section

    miner = ScopeCandidateMiner(driver, config=config, tenant_id=tenant_id)
    verifier = ScopeVerifier(config=config)

    report = AnalysisReport(
        timestamp=datetime.now().isoformat(),
        config={
            "top_k_pivots": config.top_k_pivots,
            "max_concepts_per_scope": config.max_concepts_per_scope,
            "max_pairs_per_scope": config.max_pairs_per_scope,
            "require_min_spans": config.require_min_spans,
            "allowed_relation_types": [rt.value for rt in config.allowed_relation_types],
        },
    )

    # Récupérer les sections
    logger.info("Récupération des sections avec concepts...")
    sections = get_sections_to_process(driver, tenant_id, sample_size)
    logger.info(f"Sections à traiter: {len(sections)}")

    # Traiter les sections
    for i, section_id in enumerate(sections):
        if (i + 1) % 10 == 0:
            logger.info(f"Progress: {i + 1}/{len(sections)} sections...")

        try:
            section_report = await analyze_section(
                section_id, miner, verifier, report,
                collect_details=(i < 100),  # Détails pour les 100 premières
            )

            report.sections_processed += 1
            report.total_doc_items += section_report.doc_items
            report.total_concepts += section_report.concepts
            report.total_candidates += section_report.candidates_mined
            report.total_asserted += section_report.asserted
            report.total_abstained += section_report.abstained

            report.section_reports.append(section_report)

        except Exception as e:
            logger.error(f"Erreur section {section_id}: {e}")

    # Calculer le taux d'ABSTAIN
    if report.total_candidates > 0:
        report.abstain_rate = report.total_abstained / report.total_candidates

    return report


def print_report(report: AnalysisReport):
    """Affiche le rapport de manière lisible."""

    print("\n" + "=" * 70)
    print("SCOPE ANALYSIS REPORT - DRY RUN")
    print("=" * 70)
    print(f"Timestamp: {report.timestamp}")
    print(f"\nConfig:")
    for k, v in report.config.items():
        print(f"  {k}: {v}")

    print("\n" + "-" * 70)
    print("STATISTIQUES GLOBALES")
    print("-" * 70)
    print(f"Sections traitées: {report.sections_processed}")
    print(f"DocItems total: {report.total_doc_items}")
    print(f"Concepts total: {report.total_concepts}")
    print(f"Candidates minés: {report.total_candidates}")
    print(f"\nRésultats vérification:")
    print(f"  ASSERT: {report.total_asserted} ({report.total_asserted / max(1, report.total_candidates) * 100:.1f}%)")
    print(f"  ABSTAIN: {report.total_abstained} ({report.abstain_rate * 100:.1f}%)")

    print("\n" + "-" * 70)
    print("DISTRIBUTION DES RAISONS D'ABSTAIN")
    print("-" * 70)
    for reason, count in sorted(report.abstain_reasons_distribution.items(), key=lambda x: -x[1]):
        pct = count / max(1, report.total_abstained) * 100
        print(f"  {reason}: {count} ({pct:.1f}%)")

    print("\n" + "-" * 70)
    print("DISTRIBUTION DES TYPES DE RELATIONS (ASSERT)")
    print("-" * 70)
    for rel_type, count in sorted(report.relation_types_distribution.items(), key=lambda x: -x[1]):
        pct = count / max(1, report.total_asserted) * 100
        print(f"  {rel_type}: {count} ({pct:.1f}%)")

    print("\n" + "-" * 70)
    print(f"RELATIONS VALIDÉES (échantillon: {min(20, len(report.asserted_relations))})")
    print("-" * 70)
    for rel in report.asserted_relations[:20]:
        print(f"\n  {rel.subject[:30]} --[{rel.relation_type}]--> {rel.object[:30]}")
        print(f"    confidence: {rel.confidence}, marker: {rel.marker}")
        print(f"    scope: \"{rel.scope_setter_text[:60]}...\"")

    print("\n" + "-" * 70)
    print(f"ABSTAIN SAMPLE ({min(10, len(report.sample_abstained))})")
    print("-" * 70)
    for ab in report.sample_abstained[:10]:
        print(f"  {ab.pivot[:25]} <-> {ab.other[:25]}")
        print(f"    reason: {ab.reason}")

    print("\n" + "=" * 70)
    print("FIN DU RAPPORT")
    print("=" * 70)


def save_report(report: AnalysisReport, output_path: str):
    """Sauvegarde le rapport en JSON."""

    # Convertir en dict sérialisable
    def to_dict(obj):
        if hasattr(obj, "__dict__"):
            return {k: to_dict(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, list):
            return [to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: to_dict(v) for k, v in obj.items()}
        else:
            return obj

    report_dict = to_dict(report)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    logger.info(f"Rapport sauvegardé: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="SCOPE Mining Analysis - Dry Run")
    parser.add_argument("--sample", type=int, default=50, help="Nombre de sections à analyser (défaut: 50)")
    parser.add_argument("--all", action="store_true", help="Analyser toutes les sections")
    parser.add_argument("--output", type=str, default=None, help="Fichier de sortie JSON")
    parser.add_argument("--max-pairs", type=int, default=20, help="Max pairs par section (défaut: 20)")
    parser.add_argument("--tenant", type=str, default="default", help="Tenant ID")

    args = parser.parse_args()

    # Connexion Neo4j
    driver = GraphDatabase.driver(
        "bolt://neo4j:7687",
        auth=("neo4j", "graphiti_neo4j_pass")
    )

    try:
        # Config
        config = ScopeMiningConfig()
        sample_size = None if args.all else args.sample

        logger.info(f"Démarrage analyse SCOPE (sample={sample_size or 'ALL'}, max_pairs={args.max_pairs})")

        # Exécuter l'analyse
        report = asyncio.run(run_analysis(
            driver,
            args.tenant,
            sample_size,
            config,
            args.max_pairs,
        ))

        # Afficher le rapport
        print_report(report)

        # Sauvegarder si demandé
        if args.output:
            save_report(report, args.output)
        else:
            # Sauvegarde par défaut
            default_output = f"data/scope_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            save_report(report, default_output)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
