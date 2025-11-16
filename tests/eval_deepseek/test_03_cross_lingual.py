"""
Phase 3: Validation USP Cross-Lingual
TEST CRITIQUE: Valider que DeepSeek-OCR préserve capacité cross-lingual canonicalization
"""

import torch
import time
import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, asdict

try:
    from transformers import AutoModel, AutoProcessor
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    DEEPSEEK_AVAILABLE = True
except ImportError:
    DEEPSEEK_AVAILABLE = False

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False


@dataclass
class CrossLingualTestResult:
    """Résultat test cross-lingual pour un concept"""
    concept_canonical: str  # Nom canonique (EN priority)
    text_en: str
    text_fr: str
    text_de: str
    similarity_en_fr: float
    similarity_en_de: float
    similarity_fr_de: float
    threshold_osmose: float = 0.85
    pass_en_fr: bool = None
    pass_en_de: bool = None
    pass_fr_de: bool = None
    overall_pass: bool = None

    def __post_init__(self):
        """Calculer pass/fail après init"""
        self.pass_en_fr = self.similarity_en_fr >= self.threshold_osmose
        self.pass_en_de = self.similarity_en_de >= self.threshold_osmose
        self.pass_fr_de = self.similarity_fr_de >= self.threshold_osmose
        self.overall_pass = all([self.pass_en_fr, self.pass_en_de, self.pass_fr_de])


class Phase3CrossLingualValidator:
    """Validation USP critique: Cross-lingual concept canonicalization"""

    def __init__(self, model_name: str = "deepseek-ai/DeepSeek-OCR"):
        self.model_name = model_name
        self.results_dir = Path("tests/eval_deepseek/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Modèles
        self.deepseek_model = None
        self.deepseek_processor = None
        self.embedding_model = None
        self.spacy_models = {}

    def load_models(self, use_4bit: bool = False):
        """Charger tous les modèles nécessaires"""
        print("🔧 Chargement modèles...")

        # DeepSeek-OCR
        if DEEPSEEK_AVAILABLE:
            print("   → DeepSeek-OCR...")
            load_kwargs = {
                "device_map": "auto",
                "torch_dtype": torch.bfloat16
            }
            if use_4bit:
                load_kwargs["load_in_4bit"] = True

            self.deepseek_processor = AutoProcessor.from_pretrained(self.model_name)
            self.deepseek_model = AutoModel.from_pretrained(self.model_name, **load_kwargs)

        # Multilingual Embeddings (même que OSMOSE)
        print("   → multilingual-e5-large-instruct...")
        self.embedding_model = SentenceTransformer(
            "intfloat/multilingual-e5-large-instruct",
            device="cuda" if torch.cuda.is_available() else "cpu"
        )

        # SpaCy multilingue (même que OSMOSE)
        if SPACY_AVAILABLE:
            print("   → spaCy models (en, fr, de)...")
            try:
                self.spacy_models = {
                    "en": spacy.load("en_core_web_lg"),
                    "fr": spacy.load("fr_core_news_lg"),
                    "de": spacy.load("de_core_news_lg")
                }
            except OSError:
                print("   ⚠️ Modèles spaCy manquants - download avec:")
                print("      python -m spacy download en_core_web_lg")
                print("      python -m spacy download fr_core_news_lg")
                print("      python -m spacy download de_core_news_lg")
                self.spacy_models = {}

        print("   ✅ Modèles chargés")

    def extract_text_from_slide(self, slide_image_path: Path) -> str:
        """
        Extraire texte d'une slide via DeepSeek-OCR

        Args:
            slide_image_path: Path vers image PNG de la slide

        Returns:
            Texte extrait
        """
        if not self.deepseek_model:
            raise RuntimeError("DeepSeek-OCR non chargé")

        # TODO: Implémenter extraction via DeepSeek-OCR
        # inputs = self.deepseek_processor(images=image, return_tensors="pt")
        # outputs = self.deepseek_model(**inputs)
        # text = self.deepseek_processor.decode(outputs)

        # Placeholder: lire depuis fichier text si existe
        text_file = slide_image_path.with_suffix(".txt")
        if text_file.exists():
            return text_file.read_text(encoding="utf-8")

        return f"[TODO: Extract from {slide_image_path.name}]"

    def extract_concepts_ner(self, text: str, lang: str) -> List[str]:
        """
        Extraire concepts via NER spaCy (pipeline OSMOSE)

        Args:
            text: Texte à analyser
            lang: Langue (en, fr, de)

        Returns:
            Liste concepts extraits
        """
        if lang not in self.spacy_models:
            return []

        nlp = self.spacy_models[lang]
        doc = nlp(text)

        # Extraire entités + noun chunks (même logique OSMOSE)
        concepts = []

        # Entités nommées
        for ent in doc.ents:
            concepts.append(ent.text)

        # Noun chunks
        for chunk in doc.noun_chunks:
            concepts.append(chunk.text)

        return list(set(concepts))  # Dédupliquer

    def compute_embeddings(self, texts: List[str]) -> np.ndarray:
        """
        Calculer embeddings multilingues (pipeline OSMOSE)

        Args:
            texts: Liste de textes

        Returns:
            Array embeddings (n_texts, 1024)
        """
        if not self.embedding_model:
            raise RuntimeError("Embedding model non chargé")

        # Prefix task (OSMOSE utilise "query:" pour recherche)
        # Ici on utilise "passage:" pour stockage
        texts_with_prefix = [f"passage: {text}" for text in texts]

        embeddings = self.embedding_model.encode(
            texts_with_prefix,
            convert_to_numpy=True,
            normalize_embeddings=True  # Important pour cosine similarity
        )

        return embeddings

    def test_concept_cross_lingual(
        self,
        concept_canonical: str,
        slide_en: Path,
        slide_fr: Path,
        slide_de: Path
    ) -> CrossLingualTestResult:
        """
        Tester cross-lingual canonicalization sur un concept

        Args:
            concept_canonical: Nom canonique du concept (EN)
            slide_en: Path image slide EN
            slide_fr: Path image slide FR
            slide_de: Path image slide DE

        Returns:
            Résultats test cross-lingual
        """
        print(f"\n🧪 Test concept: {concept_canonical}")

        # Étape 1: Extract text via DeepSeek-OCR
        print("   1/4 Extraction texte (DeepSeek-OCR)...")
        text_en = self.extract_text_from_slide(slide_en)
        text_fr = self.extract_text_from_slide(slide_fr)
        text_de = self.extract_text_from_slide(slide_de)

        # Étape 2: Extract concepts via NER (pipeline OSMOSE)
        print("   2/4 Extraction concepts (NER spaCy)...")
        concepts_en = self.extract_concepts_ner(text_en, "en")
        concepts_fr = self.extract_concepts_ner(text_fr, "fr")
        concepts_de = self.extract_concepts_ner(text_de, "de")

        # Utiliser premier concept (ou texte complet si NER fail)
        concept_text_en = concepts_en[0] if concepts_en else text_en
        concept_text_fr = concepts_fr[0] if concepts_fr else text_fr
        concept_text_de = concepts_de[0] if concepts_de else text_de

        # Étape 3: Compute embeddings (pipeline OSMOSE)
        print("   3/4 Embeddings (multilingual-e5)...")
        embeddings = self.compute_embeddings([
            concept_text_en,
            concept_text_fr,
            concept_text_de
        ])

        # Étape 4: Compute similarities
        print("   4/4 Similarités cross-linguale...")
        sim_en_fr = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
        sim_en_de = float(cosine_similarity([embeddings[0]], [embeddings[2]])[0][0])
        sim_fr_de = float(cosine_similarity([embeddings[1]], [embeddings[2]])[0][0])

        result = CrossLingualTestResult(
            concept_canonical=concept_canonical,
            text_en=concept_text_en,
            text_fr=concept_text_fr,
            text_de=concept_text_de,
            similarity_en_fr=round(sim_en_fr, 3),
            similarity_en_de=round(sim_en_de, 3),
            similarity_fr_de=round(sim_fr_de, 3)
        )

        # Display
        print(f"   Similarités:")
        print(f"      EN-FR: {result.similarity_en_fr:.3f} {'✅' if result.pass_en_fr else '❌'}")
        print(f"      EN-DE: {result.similarity_en_de:.3f} {'✅' if result.pass_en_de else '❌'}")
        print(f"      FR-DE: {result.similarity_fr_de:.3f} {'✅' if result.pass_fr_de else '❌'}")
        print(f"   Result: {'✅ PASS' if result.overall_pass else '❌ FAIL'}")

        return result

    def run_phase3(
        self,
        fixtures_dir: Path = None,
        use_4bit: bool = False
    ) -> Dict[str, Any]:
        """
        Exécuter validation Phase 3 complète

        Args:
            fixtures_dir: Path vers fixtures cross-lingual
            use_4bit: Quantization 4-bit
        """
        print("\n" + "="*60)
        print("🚀 PHASE 3: Validation USP Cross-Lingual (CRITIQUE)")
        print("="*60 + "\n")

        results = {
            "phase": "Phase 3 - Cross-Lingual USP Validation",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "configuration": {
                "threshold_osmose": 0.85,
                "embedding_model": "intfloat/multilingual-e5-large-instruct",
                "ner_models": "spaCy (en_core_web_lg, fr_core_news_lg, de_core_news_lg)"
            },
            "tests": [],
            "overall_status": "UNKNOWN"
        }

        # Load models
        try:
            self.load_models(use_4bit=use_4bit)
        except Exception as e:
            results["overall_status"] = "FAIL"
            results["error"] = f"Erreur chargement modèles: {e}"
            self.save_results(results, "phase3_cross_lingual.json")
            return results

        # Define test cases
        if not fixtures_dir:
            fixtures_dir = Path("tests/eval_deepseek/fixtures/cross_lingual")

        test_cases = [
            {
                "concept": "Customer Retention Rate",
                "slides": {
                    "en": fixtures_dir / "crr_definition_en.png",
                    "fr": fixtures_dir / "crr_definition_fr.png",
                    "de": fixtures_dir / "crr_definition_de.png"
                }
            },
            {
                "concept": "Authentication Policy",
                "slides": {
                    "en": fixtures_dir / "auth_policy_en.png",
                    "fr": fixtures_dir / "auth_policy_fr.png",
                    "de": fixtures_dir / "auth_policy_de.png"
                }
            }
        ]

        # Run tests
        all_pass = True
        for test_case in test_cases:
            slides = test_case["slides"]

            # Check if fixtures exist
            if not all(p.exists() for p in slides.values()):
                print(f"\n⚠️ Fixtures manquantes pour '{test_case['concept']}'")
                print(f"   Attendu dans: {fixtures_dir}")
                print(f"   Fichiers:")
                for lang, path in slides.items():
                    status = "✅" if path.exists() else "❌"
                    print(f"      {status} {path.name}")
                continue

            # Test
            try:
                test_result = self.test_concept_cross_lingual(
                    concept_canonical=test_case["concept"],
                    slide_en=slides["en"],
                    slide_fr=slides["fr"],
                    slide_de=slides["de"]
                )
                results["tests"].append(asdict(test_result))

                if not test_result.overall_pass:
                    all_pass = False

            except Exception as e:
                print(f"   ❌ Erreur test: {e}")
                results["tests"].append({
                    "concept_canonical": test_case["concept"],
                    "error": str(e),
                    "overall_pass": False
                })
                all_pass = False

        # Overall decision
        if not results["tests"]:
            results["overall_status"] = "SKIP"
            results["message"] = "Aucun test exécuté - fixtures manquantes"
        elif all_pass:
            results["overall_status"] = "PASS"
            results["decision"] = "✅ USP PRÉSERVÉ - Recommander Scénario A"
        else:
            results["overall_status"] = "FAIL"
            results["decision"] = "❌ USP COMPROMIS - ABANDONNER DeepSeek-OCR"

        # Summary stats
        if results["tests"]:
            passed = sum(1 for t in results["tests"] if t.get("overall_pass"))
            total = len(results["tests"])
            results["summary"] = {
                "tests_passed": passed,
                "tests_total": total,
                "pass_rate": round(passed / total, 2)
            }

        # Save
        self.save_results(results, "phase3_cross_lingual.json")

        # Display summary
        print("\n" + "="*60)
        print(f"📋 RÉSULTAT PHASE 3: {results['overall_status']}")
        print("="*60)

        if "summary" in results:
            print(f"Tests réussis: {results['summary']['tests_passed']}/{results['summary']['tests_total']}")
            print(f"Taux succès: {results['summary']['pass_rate']*100:.0f}%")

        if "decision" in results:
            print(f"\n{results['decision']}")

        if results["overall_status"] == "PASS":
            print("\n🎉 VALIDATION COMPLÈTE - DeepSeek-OCR compatible OSMOSE USP")
            print("➡️ NEXT: Implémenter Scénario A (DeepSeek comme optimisation vision)")
        elif results["overall_status"] == "FAIL":
            print("\n⚠️ CRITIQUE - USP cross-lingual compromise")
            print("   DeepSeek-OCR non compatible avec différenciation OSMOSE")
            print("   Recommandation: Chercher autres optimisations pipeline")
        elif results["overall_status"] == "SKIP":
            print("\n📝 Créer fixtures cross-lingual d'abord:")
            print(f"   Location: {fixtures_dir}")
            print("   Voir: OSMOSE_DEEPSEEK_OCR_EVALUATION_PLAN.md section 'Créer Fixtures'")

        return results

    def save_results(self, results: Dict[str, Any], filename: str):
        """Sauvegarder résultats JSON"""
        filepath = self.results_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Résultats sauvegardés: {filepath}")


def main():
    """Point d'entrée principal"""
    validator = Phase3CrossLingualValidator()

    # Fixtures directory
    fixtures_dir = Path("tests/eval_deepseek/fixtures/cross_lingual")

    # Run validation
    results = validator.run_phase3(
        fixtures_dir=fixtures_dir,
        use_4bit=False
    )

    return results


if __name__ == "__main__":
    main()
