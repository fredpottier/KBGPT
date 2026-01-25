"""
POC Lecture Stratifiee OSMOSIS v2

Orchestrateur principal pour valider l'ADR_STRATIFIED_READING_MODEL.
Ce code est ISOLE du pipeline OSMOSIS existant.

Usage:
    python -m poc.poc_stratified_reader --doc <path_to_pdf>
    python -m poc.poc_stratified_reader --batch <folder_path>
    python -m poc.poc_stratified_reader --test  # Mode test avec mock LLM
    python -m poc.poc_stratified_reader --v2    # Utiliser le nouveau pipeline semantique

V2 Changes:
    - SemanticAssertionExtractor remplace InformationExtractor
    - Extraction d'assertions puis liaison semantique
    - Support multilingue (concepts FR <-> texte EN)
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import asdict

from poc.models.schemas import (
    DocumentStructure,
    QualityMetrics,
    DependencyStructure
)
from poc.extractors.document_analyzer import DocumentAnalyzer
from poc.extractors.concept_identifier import ConceptIdentifier
from poc.extractors.information_extractor import InformationExtractor
from poc.validators.frugality_guard import FrugalityGuard
from poc.validators.anchor_validator import AnchorValidator
from poc.utils.text_extractor import TextExtractor, ExtractionResult
from poc.utils.chunker import SimpleChunker

# V2: Nouveau pipeline semantique
try:
    from poc.extractors.semantic_assertion_extractor import SemanticAssertionExtractor
    SEMANTIC_EXTRACTOR_AVAILABLE = True
except ImportError:
    SEMANTIC_EXTRACTOR_AVAILABLE = False


class StratifiedReader:
    """
    Orchestrateur du POC Lecture Stratifiee.

    Phases:
    0. Extraction texte brut (PDF -> texte)
    1.1 Analyse structurelle (structure de dependance, themes)
    1.2 Identification concepts situes (frugalite stricte)
    1.3 Extraction Information (avec anchors)
    1.4 Detection relations (mediated par Information)
    """

    # Documents de test du POC
    POC_DOCUMENTS = {
        "CENTRAL": {
            "name": "SAP GDPR Industry Guide",
            "expected_structure": DependencyStructure.CENTRAL,
            "expected_concept_range": (15, 40),
            "path_hint": "SAP*GDPR*.pdf"
        },
        "TRANSVERSAL": {
            "name": "CNIL Guide GDPR Sous-traitants",
            "expected_structure": DependencyStructure.TRANSVERSAL,
            "expected_concept_range": (20, 50),
            "path_hint": "*CNIL*GDPR*.pdf"
        },
        "CONTEXTUAL": {
            "name": "Euro NCAP Safe Driving",
            "expected_structure": DependencyStructure.CONTEXTUAL,
            "expected_concept_range": (10, 35),
            "path_hint": "*Euro*NCAP*Safe*.pdf"
        },
        "HOSTILE": {
            "name": "Euro NCAP VRU Protocol",
            "expected_structure": DependencyStructure.CONTEXTUAL,  # ou TRANSVERSAL
            "expected_concept_range": (0, 10),  # Doit etre < 10
            "path_hint": "*Euro*NCAP*VRU*.pdf"
        }
    }

    def __init__(
        self,
        llm_client=None,
        use_mock: bool = False,
        output_dir: Optional[str] = None,
        use_v2: bool = False
    ):
        """
        Args:
            llm_client: Client LLM (QwenClient ou autre)
            use_mock: Utiliser un mock LLM pour les tests
            output_dir: Repertoire pour les resultats
            use_v2: Utiliser le pipeline V2 (SemanticAssertionExtractor)
        """
        self.llm_client = llm_client if not use_mock else None
        self.use_mock = use_mock
        self.use_v2 = use_v2

        # allow_fallback=True UNIQUEMENT en mode test
        allow_fallback = use_mock

        # Composants
        self.text_extractor = TextExtractor(use_ocr=False)
        self.chunker = SimpleChunker(chunk_size=1000, overlap=200)
        self.document_analyzer = DocumentAnalyzer(
            llm_client=self.llm_client,
            allow_fallback=allow_fallback
        )
        self.concept_identifier = ConceptIdentifier(
            llm_client=self.llm_client,
            allow_fallback=allow_fallback
        )

        # V2: Semantic Assertion Extractor vs V1: Information Extractor
        if use_v2 and SEMANTIC_EXTRACTOR_AVAILABLE:
            print("[POC] Pipeline V2: SemanticAssertionExtractor")
            self.information_extractor = SemanticAssertionExtractor(
                llm_client=self.llm_client,
                allow_fallback=allow_fallback
            )
        else:
            if use_v2 and not SEMANTIC_EXTRACTOR_AVAILABLE:
                print("[POC] WARN: V2 demande mais SemanticAssertionExtractor non disponible")
            self.information_extractor = InformationExtractor(
                llm_client=self.llm_client,
                allow_fallback=allow_fallback
            )

        self.frugality_guard = FrugalityGuard()
        self.anchor_validator = AnchorValidator()

        # Output
        self.output_dir = Path(output_dir) if output_dir else Path("poc/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_document(
        self,
        file_path: str,
        doc_type: str = "NORMAL"
    ) -> DocumentStructure:
        """
        Traite un document complet.

        Args:
            file_path: Chemin vers le document
            doc_type: Type attendu (CENTRAL, TRANSVERSAL, CONTEXTUAL, HOSTILE)

        Returns:
            DocumentStructure avec tous les resultats
        """
        print(f"\n{'='*60}")
        print(f"[POC] Traitement: {Path(file_path).name}")
        print(f"[POC] Type attendu: {doc_type}")
        print(f"{'='*60}\n")

        # Phase 0: Extraction texte
        print("[Phase 0] Extraction texte...")
        extraction = self.text_extractor.extract(file_path)
        if not extraction.success:
            raise ValueError(f"Extraction echouee: {extraction.error}")
        print(f"  -> {extraction.char_count} caracteres, {extraction.page_count} pages")

        # Chunking
        print("[Phase 0] Chunking...")
        chunks, chunks_dict = self.chunker.chunk(extraction.text, extraction.doc_id)
        print(f"  -> {len(chunks)} chunks crees")

        # Phase 1.1: Analyse structurelle
        print("\n[Phase 1.1] Analyse structurelle...")
        analysis = self.document_analyzer.analyze(
            doc_title=extraction.title,
            content=extraction.text,
            toc=self.document_analyzer.extract_toc_from_content(extraction.text)
        )
        # Extraire la langue (V2) - detectee ou par defaut
        doc_language = analysis.get('language', self._detect_language(extraction.text))
        print(f"  -> Langue: {doc_language}")
        print(f"  -> Sujet: {analysis['subject'][:50]}...")
        print(f"  -> Structure: {analysis['structure_decision'].chosen.value}")
        print(f"  -> Themes: {len(analysis['themes'])}")

        # Phase 1.2: Identification concepts
        print("\n[Phase 1.2] Identification concepts...")
        concept_result = self.concept_identifier.identify(
            subject=analysis['subject'],
            structure=analysis['structure_decision'].chosen.value,
            themes=analysis['themes'],
            content=extraction.text,
            doc_type=doc_type,
            language=doc_language  # V2: passer la langue
        )
        print(f"  -> {concept_result.concept_count} concepts identifies")
        print(f"  -> {len(concept_result.refused_terms)} termes refuses")

        # Verifier frugalite
        frugality = self.frugality_guard.validate(concept_result.concepts, doc_type)
        print(f"  -> Frugalite: {frugality.status.value} - {frugality.message}")

        # Phase 1.3: Extraction Information (V1) ou Semantic Assertions (V2)
        if self.use_v2:
            print("\n[Phase 1.3] Extraction Semantique V2...")
            print("  -> Etape 1: Extraction des assertions")
            print("  -> Etape 2: Liaison semantique aux concepts")
        else:
            print("\n[Phase 1.3] Extraction Information V1...")
        all_informations, concept_to_info = self.information_extractor.extract_all(
            concepts=concept_result.concepts,
            chunks=chunks_dict
        )
        print(f"  -> {len(all_informations)} Information extraites")

        # Mettre a jour les concepts avec leurs Information
        for concept in concept_result.concepts:
            concept.information_ids = concept_to_info.get(concept.id, [])

        # Validation anchors
        anchor_result = self.anchor_validator.validate_all(all_informations, chunks_dict)
        print(f"  -> Anchors valides: {anchor_result.success_rate:.1%}")

        # Construire le DocumentStructure final
        doc_structure = DocumentStructure(
            doc_id=extraction.doc_id,
            doc_title=extraction.title,
            source_path=extraction.source_path,
            structure_decision=analysis['structure_decision'],
            subject=analysis['subject'],
            themes=analysis['themes'],
            concepts=concept_result.concepts,
            informations=all_informations,
            refused_terms=concept_result.refused_terms,
            metrics=QualityMetrics(
                concept_count=concept_result.concept_count,
                information_count=len(all_informations),
                info_per_concept_avg=(
                    len(all_informations) / concept_result.concept_count
                    if concept_result.concept_count > 0 else 0
                ),
                anchor_success_rate=anchor_result.success_rate,
                refusal_count=len(concept_result.refused_terms)
            )
        )

        # Sauvegarder le resultat
        self._save_result(doc_structure)

        # Afficher le resume
        self._print_summary(doc_structure, doc_type)

        return doc_structure

    def process_batch(self, folder_path: str) -> Dict[str, DocumentStructure]:
        """
        Traite un lot de documents.

        Args:
            folder_path: Dossier contenant les documents

        Returns:
            Dict[doc_id -> DocumentStructure]
        """
        folder = Path(folder_path)
        results = {}

        # Chercher les PDFs
        pdf_files = list(folder.glob("*.pdf"))
        print(f"\n[POC] {len(pdf_files)} documents trouves dans {folder}")

        for pdf_path in pdf_files:
            # Detecter le type attendu
            doc_type = self._detect_doc_type(pdf_path.name)

            try:
                result = self.process_document(str(pdf_path), doc_type)
                results[result.doc_id] = result
            except Exception as e:
                print(f"[ERREUR] {pdf_path.name}: {e}")

        # Rapport global
        self._print_batch_report(results)

        return results

    def _detect_doc_type(self, filename: str) -> str:
        """Detecte le type de document par son nom"""
        filename_lower = filename.lower()

        if "vru" in filename_lower:
            return "HOSTILE"
        elif "sap" in filename_lower:
            return "CENTRAL"
        elif "cnil" in filename_lower:
            return "TRANSVERSAL"
        elif "safe" in filename_lower and "driving" in filename_lower:
            return "CONTEXTUAL"
        else:
            return "NORMAL"

    def _detect_language(self, text: str) -> str:
        """Detecte la langue du document par heuristique"""
        # Prendre un echantillon
        sample = text[:5000].lower()

        # Mots francais courants
        fr_words = ['le', 'la', 'les', 'de', 'du', 'des', 'est', 'sont', 'pour',
                    'avec', 'dans', 'sur', 'par', 'qui', 'que', 'une', 'aux']
        # Mots anglais courants
        en_words = ['the', 'is', 'are', 'for', 'with', 'in', 'to', 'of', 'and',
                    'that', 'this', 'from', 'be', 'have', 'has', 'was', 'were']
        # Mots allemands courants
        de_words = ['der', 'die', 'das', 'und', 'ist', 'sind', 'mit', 'von',
                    'fur', 'auf', 'dem', 'den', 'ein', 'eine', 'werden']

        words = sample.split()

        fr_count = sum(1 for w in words if w in fr_words)
        en_count = sum(1 for w in words if w in en_words)
        de_count = sum(1 for w in words if w in de_words)

        if fr_count > en_count and fr_count > de_count:
            return "fr"
        elif de_count > en_count:
            return "de"
        return "en"

    def _save_result(self, doc: DocumentStructure) -> None:
        """Sauvegarde le resultat en JSON"""
        output_file = self.output_dir / f"{doc.doc_id}_result.json"

        # Convertir en dict serializable
        data = {
            "doc_id": doc.doc_id,
            "doc_title": doc.doc_title,
            "source_path": doc.source_path,
            "structure": {
                "chosen": doc.structure_decision.chosen.value,
                "justification": doc.structure_decision.justification,
                "rejected": doc.structure_decision.rejected
            },
            "subject": doc.subject,
            "themes": [
                {"name": t.name, "children": [c.name for c in t.children]}
                for t in doc.themes
            ],
            "concepts": [
                {
                    "id": c.id,
                    "name": c.name,
                    "role": c.role.value,
                    "theme_ref": c.theme_ref,
                    "information_count": len(c.information_ids)
                }
                for c in doc.concepts
            ],
            "informations_count": len(doc.informations),
            "refused_terms": [
                {"term": r.term, "reason": r.reason}
                for r in doc.refused_terms
            ],
            "metrics": {
                "concept_count": doc.metrics.concept_count,
                "information_count": doc.metrics.information_count,
                "info_per_concept_avg": doc.metrics.info_per_concept_avg,
                "anchor_success_rate": doc.metrics.anchor_success_rate,
                "refusal_count": doc.metrics.refusal_count,
                "is_frugal": doc.metrics.is_frugal
            },
            "extracted_at": doc.extracted_at.isoformat()
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n[POC] Resultat sauvegarde: {output_file}")

    def _print_summary(self, doc: DocumentStructure, expected_type: str) -> None:
        """Affiche un resume du traitement"""
        print(f"\n{'='*60}")
        print(f"RESUME: {doc.doc_title}")
        print(f"{'='*60}")
        print(f"Structure detectee : {doc.structure_decision.chosen.value}")
        print(f"Concepts extraits  : {doc.metrics.concept_count}")
        print(f"Information        : {doc.metrics.information_count}")
        print(f"Info/Concept avg   : {doc.metrics.info_per_concept_avg:.1f}")
        print(f"Anchor success     : {doc.metrics.anchor_success_rate:.1%}")
        print(f"Termes refuses     : {doc.metrics.refusal_count}")
        print(f"Frugalite OK       : {doc.metrics.is_frugal}")

        # Validation attendue
        expected_config = self.POC_DOCUMENTS.get(expected_type, {})
        expected_range = expected_config.get("expected_concept_range", (5, 60))

        if expected_range[0] <= doc.metrics.concept_count <= expected_range[1]:
            print(f"\n[OK] Nombre de concepts dans la plage attendue {expected_range}")
        else:
            print(f"\n[WARN] Concepts hors plage attendue {expected_range}")

    def _print_batch_report(self, results: Dict[str, DocumentStructure]) -> None:
        """Affiche un rapport global pour un batch"""
        print(f"\n{'='*60}")
        print("RAPPORT GLOBAL POC")
        print(f"{'='*60}")

        for doc_id, doc in results.items():
            status = "OK" if doc.metrics.is_frugal else "FAIL"
            print(f"[{status}] {doc.doc_title[:40]:<40} | "
                  f"C:{doc.metrics.concept_count:2d} | "
                  f"I:{doc.metrics.information_count:3d} | "
                  f"A:{doc.metrics.anchor_success_rate:.0%}")

        # Stats globales
        total_concepts = sum(d.metrics.concept_count for d in results.values())
        total_infos = sum(d.metrics.information_count for d in results.values())
        avg_anchor = (
            sum(d.metrics.anchor_success_rate for d in results.values()) / len(results)
            if results else 0
        )
        frugal_count = sum(1 for d in results.values() if d.metrics.is_frugal)

        print(f"\n{'='*60}")
        print(f"Documents traites : {len(results)}")
        print(f"Documents frugaux : {frugal_count}/{len(results)}")
        print(f"Total concepts    : {total_concepts}")
        print(f"Total Information : {total_infos}")
        print(f"Anchor success avg: {avg_anchor:.1%}")


def main():
    """Point d'entree CLI"""
    parser = argparse.ArgumentParser(
        description="POC Lecture Stratifiee OSMOSIS v2"
    )
    parser.add_argument(
        "--doc",
        type=str,
        help="Chemin vers un document PDF"
    )
    parser.add_argument(
        "--batch",
        type=str,
        help="Dossier contenant les documents PDF"
    )
    parser.add_argument(
        "--type",
        type=str,
        default="NORMAL",
        choices=["CENTRAL", "TRANSVERSAL", "CONTEXTUAL", "HOSTILE", "NORMAL"],
        help="Type de document attendu"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Mode test avec mock LLM"
    )
    parser.add_argument(
        "--llm",
        type=str,
        default="vllm",
        choices=["vllm", "openai"],
        help="Provider LLM: vllm ou openai"
    )
    parser.add_argument(
        "--vllm-url",
        type=str,
        default="http://3.123.41.100:8000",
        help="URL du serveur vLLM"
    )
    parser.add_argument(
        "--openai-model",
        type=str,
        default="gpt-4o",
        help="Modele OpenAI (gpt-4o, gpt-4-turbo)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="poc/output",
        help="Repertoire de sortie"
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Utiliser le pipeline V2 (SemanticAssertionExtractor)"
    )

    args = parser.parse_args()

    # Creer le client LLM si pas en mode test
    llm_client = None
    if not args.test:
        if args.llm == "vllm":
            from poc.clients.vllm_client import VLLMClient
            llm_client = VLLMClient(base_url=args.vllm_url)
            print(f"[POC] Connexion vLLM: {args.vllm_url}")
            if llm_client.health_check():
                print("[POC] vLLM OK")
            else:
                print("[POC] ERREUR: vLLM non accessible")
                sys.exit(1)
        elif args.llm == "openai":
            from poc.clients.openai_client import OpenAIClient
            llm_client = OpenAIClient(model=args.openai_model)
            print(f"[POC] Connexion OpenAI: {args.openai_model}")
            if llm_client.health_check():
                print("[POC] OpenAI OK")
            else:
                print("[POC] ERREUR: OpenAI non accessible")
                sys.exit(1)

    # Creer le reader
    reader = StratifiedReader(
        llm_client=llm_client,
        use_mock=args.test or llm_client is None,
        output_dir=args.output,
        use_v2=args.v2
    )

    if args.doc:
        reader.process_document(args.doc, args.type)
    elif args.batch:
        reader.process_batch(args.batch)
    else:
        print("Usage: python -m poc.poc_stratified_reader --doc <path> ou --batch <folder>")
        print("       Ajouter --test pour mode sans LLM")
        sys.exit(1)


if __name__ == "__main__":
    main()
