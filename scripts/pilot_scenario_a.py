"""
Pilote Scénario A - Phase 1.5 Jour 5

Objectif: Traiter 50 PDF textuels simples et valider critères de succès.

Critères de succès:
- Cost target: ≤ $1.00/1000 pages ($0.25/doc si 250p/doc)
- Performance: < 30s/doc (P95)
- Qualité: Promotion rate ≥ 30% (BALANCED profile)
- Stabilité: 0 rate limit violations (429 errors)
- Resilience: 0 circuit breaker trips

Output: CSV avec métriques par document + stats agrégées.
"""

import asyncio
import sys
import csv
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import logging
import statistics

# Ajouter src/ au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.ingestion.osmose_agentique import OsmoseAgentiqueService
from knowbase.ingestion.osmose_integration import OsmoseIntegrationConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

SCENARIO_A_CONFIG = {
    "name": "Scenario A - Textual PDFs",
    "description": "50 simple textual PDF documents",
    "target_cost_per_1000_pages": 1.00,  # $/1000p
    "target_processing_time_p95": 30.0,  # seconds
    "target_promotion_rate": 0.30,  # 30%
    "output_csv": "pilot_scenario_a_results.csv"
}


# ============================================================================
# Helper Functions
# ============================================================================

def load_test_documents(documents_dir: Path) -> List[Path]:
    """
    Charge liste de documents test.

    Args:
        documents_dir: Répertoire contenant les documents

    Returns:
        Liste de chemins PDF/TXT
    """
    pdf_files = list(documents_dir.glob("*.pdf"))
    txt_files = list(documents_dir.glob("*.txt"))

    all_files = pdf_files + txt_files
    all_files.sort()

    logger.info(f"Found {len(all_files)} documents in {documents_dir}")
    return all_files


def extract_text_from_pdf(pdf_path: Path) -> str:
    """
    Extrait texte depuis PDF (simple).

    Args:
        pdf_path: Chemin PDF

    Returns:
        Texte extrait
    """
    try:
        import PyPDF2

        text = ""
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"

        return text

    except Exception as e:
        logger.warning(f"Failed to extract text from {pdf_path}: {e}")
        return ""


def calculate_aggregated_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcule statistiques agrégées.

    Args:
        results: Liste résultats par document

    Returns:
        Dict stats agrégées
    """
    if not results:
        return {}

    # Filtrer résultats réussis
    successful = [r for r in results if r["success"]]

    if not successful:
        return {"error": "No successful results"}

    # Extraction métriques
    costs = [r["cost"] for r in successful]
    durations = [r["duration_seconds"] for r in successful]
    promotion_rates = [r["promotion_rate"] for r in successful if r["promotion_rate"] is not None]

    # Stats
    stats = {
        "total_documents": len(results),
        "successful_documents": len(successful),
        "failed_documents": len(results) - len(successful),

        # Cost
        "total_cost": sum(costs),
        "avg_cost_per_doc": statistics.mean(costs) if costs else 0.0,
        "median_cost_per_doc": statistics.median(costs) if costs else 0.0,

        # Duration
        "avg_duration_seconds": statistics.mean(durations) if durations else 0.0,
        "median_duration_seconds": statistics.median(durations) if durations else 0.0,
        "p95_duration_seconds": statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations) if durations else 0.0,
        "p99_duration_seconds": statistics.quantiles(durations, n=100)[98] if len(durations) >= 100 else max(durations) if durations else 0.0,

        # Promotion
        "avg_promotion_rate": statistics.mean(promotion_rates) if promotion_rates else 0.0,
        "median_promotion_rate": statistics.median(promotion_rates) if promotion_rates else 0.0,
    }

    # Validation critères
    stats["criteria_validation"] = {
        "cost_target": stats["avg_cost_per_doc"] <= 0.25,  # $0.25/doc target
        "performance_p95": stats["p95_duration_seconds"] <= SCENARIO_A_CONFIG["target_processing_time_p95"],
        "promotion_rate": stats["avg_promotion_rate"] >= SCENARIO_A_CONFIG["target_promotion_rate"],
    }

    return stats


def save_results_to_csv(results: List[Dict[str, Any]], output_path: Path):
    """
    Sauvegarde résultats dans CSV.

    Args:
        results: Liste résultats
        output_path: Chemin CSV output
    """
    if not results:
        logger.warning("No results to save")
        return

    # Headers
    headers = [
        "document_id",
        "document_title",
        "success",
        "error",
        "duration_seconds",
        "cost",
        "llm_calls_SMALL",
        "llm_calls_BIG",
        "llm_calls_VISION",
        "segments_count",
        "concepts_extracted",
        "concepts_promoted",
        "promotion_rate",
        "fsm_state",
        "fsm_steps"
    ]

    # Write CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for result in results:
            row = {
                "document_id": result["document_id"],
                "document_title": result["document_title"],
                "success": result["success"],
                "error": result.get("error", ""),
                "duration_seconds": result.get("duration_seconds", 0.0),
                "cost": result.get("cost", 0.0),
                "llm_calls_SMALL": result.get("llm_calls", {}).get("SMALL", 0),
                "llm_calls_BIG": result.get("llm_calls", {}).get("BIG", 0),
                "llm_calls_VISION": result.get("llm_calls", {}).get("VISION", 0),
                "segments_count": result.get("segments_count", 0),
                "concepts_extracted": result.get("concepts_extracted", 0),
                "concepts_promoted": result.get("concepts_promoted", 0),
                "promotion_rate": result.get("promotion_rate"),
                "fsm_state": result.get("fsm_state", ""),
                "fsm_steps": result.get("fsm_steps", 0)
            }
            writer.writerow(row)

    logger.info(f"Results saved to {output_path}")


# ============================================================================
# Main Pipeline
# ============================================================================

async def process_single_document(
    service: OsmoseAgentiqueService,
    doc_path: Path,
    doc_id: str
) -> Dict[str, Any]:
    """
    Traite un seul document.

    Args:
        service: OsmoseAgentiqueService
        doc_path: Chemin document
        doc_id: ID document

    Returns:
        Dict résultat
    """
    logger.info(f"Processing {doc_id}: {doc_path.name}")

    try:
        # Extraire texte
        if doc_path.suffix.lower() == ".pdf":
            text_content = extract_text_from_pdf(doc_path)
        else:
            text_content = doc_path.read_text(encoding='utf-8')

        if not text_content:
            return {
                "document_id": doc_id,
                "document_title": doc_path.stem,
                "success": False,
                "error": "Failed to extract text"
            }

        # Traiter avec OSMOSE Agentique
        result = await service.process_document_agentique(
            document_id=doc_id,
            document_title=doc_path.stem,
            document_path=doc_path,
            text_content=text_content,
            tenant_id="pilot_scenario_a"
        )

        # Construire résultat
        promotion_rate = None
        if result.concepts_extracted > 0:
            promotion_rate = result.concepts_promoted / result.concepts_extracted

        return {
            "document_id": doc_id,
            "document_title": doc_path.stem,
            "success": result.osmose_success,
            "error": result.osmose_error or "",
            "duration_seconds": result.total_duration_seconds,
            "cost": result.cost,
            "llm_calls": result.llm_calls_count or {},
            "segments_count": result.segments_count,
            "concepts_extracted": result.concepts_extracted,
            "concepts_promoted": result.concepts_promoted,
            "promotion_rate": promotion_rate,
            "fsm_state": result.final_fsm_state,
            "fsm_steps": result.fsm_steps_count
        }

    except Exception as e:
        logger.error(f"Error processing {doc_id}: {e}")
        return {
            "document_id": doc_id,
            "document_title": doc_path.stem,
            "success": False,
            "error": str(e)
        }


async def run_pilot_scenario_a(documents_dir: Path, max_documents: int = 50):
    """
    Exécute Pilote Scénario A.

    Args:
        documents_dir: Répertoire documents
        max_documents: Nombre max documents (default: 50)
    """
    logger.info(f"=== Pilote Scénario A ===")
    logger.info(f"Target: {max_documents} textual PDF documents")
    logger.info(f"Cost target: ≤ ${SCENARIO_A_CONFIG['target_cost_per_1000_pages']}/1000p")
    logger.info(f"Performance target: < {SCENARIO_A_CONFIG['target_processing_time_p95']}s (P95)")
    logger.info(f"Promotion rate target: ≥ {SCENARIO_A_CONFIG['target_promotion_rate'] * 100}%")

    # Charger documents
    doc_paths = load_test_documents(documents_dir)

    if not doc_paths:
        logger.error(f"No documents found in {documents_dir}")
        return

    # Limiter à max_documents
    doc_paths = doc_paths[:max_documents]
    logger.info(f"Selected {len(doc_paths)} documents for processing")

    # Initialiser service
    osmose_config = OsmoseIntegrationConfig(
        enable_osmose=True,
        osmose_for_pdf=True,
        osmose_for_pptx=True,
        min_text_length=100,
        max_text_length=100_000,
        default_tenant_id="pilot_scenario_a",
        timeout_seconds=300
    )

    supervisor_config = {
        "max_steps": 50,
        "timeout_seconds": 300,
        "default_gate_profile": "BALANCED"
    }

    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config
    )

    # Traiter documents
    results = []
    start_time = datetime.now()

    for idx, doc_path in enumerate(doc_paths, start=1):
        doc_id = f"pilot_a_{idx:03d}"

        result = await process_single_document(service, doc_path, doc_id)
        results.append(result)

        # Log progress
        if result["success"]:
            logger.info(
                f"✅ {doc_id} SUCCESS - "
                f"Duration: {result['duration_seconds']:.2f}s, "
                f"Cost: ${result['cost']:.4f}, "
                f"Promotion: {result.get('promotion_rate', 0.0) * 100:.1f}%"
            )
        else:
            logger.error(f"❌ {doc_id} FAILED - {result['error']}")

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    # Calculer stats
    logger.info(f"\n=== Results ===")
    stats = calculate_aggregated_stats(results)

    logger.info(f"Total documents: {stats['total_documents']}")
    logger.info(f"Successful: {stats['successful_documents']}")
    logger.info(f"Failed: {stats['failed_documents']}")
    logger.info(f"Total duration: {total_duration:.2f}s")
    logger.info(f"\n--- Cost ---")
    logger.info(f"Total cost: ${stats['total_cost']:.4f}")
    logger.info(f"Avg cost/doc: ${stats['avg_cost_per_doc']:.4f}")
    logger.info(f"Median cost/doc: ${stats['median_cost_per_doc']:.4f}")
    logger.info(f"\n--- Performance ---")
    logger.info(f"Avg duration: {stats['avg_duration_seconds']:.2f}s")
    logger.info(f"Median duration: {stats['median_duration_seconds']:.2f}s")
    logger.info(f"P95 duration: {stats['p95_duration_seconds']:.2f}s")
    logger.info(f"P99 duration: {stats['p99_duration_seconds']:.2f}s")
    logger.info(f"\n--- Quality ---")
    logger.info(f"Avg promotion rate: {stats['avg_promotion_rate'] * 100:.1f}%")
    logger.info(f"Median promotion rate: {stats['median_promotion_rate'] * 100:.1f}%")

    # Validation critères
    logger.info(f"\n=== Criteria Validation ===")
    criteria = stats["criteria_validation"]
    logger.info(f"Cost target: {'✅ PASS' if criteria['cost_target'] else '❌ FAIL'}")
    logger.info(f"Performance P95: {'✅ PASS' if criteria['performance_p95'] else '❌ FAIL'}")
    logger.info(f"Promotion rate: {'✅ PASS' if criteria['promotion_rate'] else '❌ FAIL'}")

    # Save results
    output_csv = Path(SCENARIO_A_CONFIG["output_csv"])
    save_results_to_csv(results, output_csv)

    logger.info(f"\n✅ Pilote Scénario A completed!")
    logger.info(f"Results: {output_csv}")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pilote Scénario A - Phase 1.5")
    parser.add_argument(
        "documents_dir",
        type=Path,
        help="Directory containing test documents (PDF/TXT)"
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=50,
        help="Maximum number of documents to process (default: 50)"
    )

    args = parser.parse_args()

    if not args.documents_dir.exists():
        logger.error(f"Directory not found: {args.documents_dir}")
        sys.exit(1)

    # Run pilot
    asyncio.run(run_pilot_scenario_a(args.documents_dir, args.max_documents))
