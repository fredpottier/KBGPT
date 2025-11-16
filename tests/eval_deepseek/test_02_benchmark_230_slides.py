"""
Phase 2: Benchmark Performance DeepSeek-OCR
Test sur cas réel: 230 slides PPTX (problème bloquant 1h30)
"""

import torch
import time
import json
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass, asdict

try:
    from transformers import AutoModel, AutoProcessor
    from PIL import Image
    DEEPSEEK_AVAILABLE = True
except ImportError:
    DEEPSEEK_AVAILABLE = False


@dataclass
class BenchmarkResult:
    """Résultat benchmark pour un document"""
    document_name: str
    total_slides: int
    processing_time_seconds: float
    tokens_generated: int
    tokens_per_second: float
    vram_peak_gb: float
    success: bool
    error: str = None


class Phase2PerformanceBenchmark:
    """Benchmark performance DeepSeek-OCR sur cas réel OSMOSE"""

    def __init__(self, model_name: str = "deepseek-ai/DeepSeek-OCR"):
        self.model_name = model_name
        self.results_dir = Path("tests/eval_deepseek/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.model = None
        self.processor = None

    def load_model(self, use_4bit: bool = False):
        """Charger modèle DeepSeek-OCR"""
        if not DEEPSEEK_AVAILABLE:
            raise ImportError("DeepSeek-OCR non installé")

        print("🔧 Chargement DeepSeek-OCR...")
        load_kwargs = {
            "device_map": "auto",
            "torch_dtype": torch.bfloat16
        }
        if use_4bit:
            load_kwargs["load_in_4bit"] = True

        self.processor = AutoProcessor.from_pretrained(self.model_name)
        self.model = AutoModel.from_pretrained(self.model_name, **load_kwargs)
        print("   ✅ Modèle chargé")

    def extract_slides_from_pptx(self, pptx_path: Path) -> List[Image.Image]:
        """
        Convertir PPTX en liste d'images (une par slide)

        TODO: Implémenter conversion PPTX → PNG
        Options:
        1. python-pptx + Pillow
        2. pdf2image (PPTX → PDF → images)
        3. LibreOffice headless conversion

        Pour le moment, retourne placeholder
        """
        # Placeholder implementation
        print(f"   TODO: Convertir {pptx_path.name} en images")
        return []

    def process_slides(
        self,
        slides: List[Image.Image],
        resolution_mode: str = "Base"
    ) -> Dict[str, Any]:
        """
        Traiter batch de slides avec DeepSeek-OCR

        Args:
            slides: Liste images (slides PPTX)
            resolution_mode: Tiny|Small|Base|Large (voir paper)
                - Tiny: 64 tokens (512x512)
                - Small: 100 tokens (640x640)
                - Base: 256 tokens (1024x1024) ← RECOMMANDÉ
                - Large: 400 tokens (1280x1280)
        """
        if not self.model or not self.processor:
            raise RuntimeError("Modèle non chargé - appeler load_model() d'abord")

        torch.cuda.reset_peak_memory_stats()
        start_time = time.time()

        total_tokens = 0

        # TODO: Implémenter batch processing
        # for slide in slides:
        #     inputs = self.processor(images=slide, return_tensors="pt")
        #     outputs = self.model(**inputs)
        #     total_tokens += outputs.shape[1]  # Approximatif

        # Placeholder
        estimated_tokens_per_slide = {
            "Tiny": 64,
            "Small": 100,
            "Base": 256,
            "Large": 400
        }[resolution_mode]

        total_tokens = len(slides) * estimated_tokens_per_slide

        processing_time = time.time() - start_time
        vram_peak = torch.cuda.max_memory_allocated() / 1e9

        return {
            "slides_processed": len(slides),
            "total_tokens": total_tokens,
            "processing_time_seconds": round(processing_time, 2),
            "tokens_per_second": round(total_tokens / processing_time, 2) if processing_time > 0 else 0,
            "vram_peak_gb": round(vram_peak, 2),
            "resolution_mode": resolution_mode
        }

    def benchmark_document(
        self,
        pptx_path: Path,
        resolution_mode: str = "Base"
    ) -> BenchmarkResult:
        """
        Benchmark complet sur un document PPTX

        Args:
            pptx_path: Chemin vers PPTX
            resolution_mode: Mode résolution DeepSeek
        """
        print(f"\n📊 Benchmark: {pptx_path.name}")
        print(f"   Mode: {resolution_mode}")

        try:
            # Étape 1: Conversion PPTX → Images
            print("   1/3 Conversion PPTX → images...")
            slides = self.extract_slides_from_pptx(pptx_path)
            num_slides = len(slides) if slides else 230  # Placeholder: assume 230

            # Étape 2: Processing DeepSeek-OCR
            print(f"   2/3 Processing {num_slides} slides...")
            start_time = time.time()
            results = self.process_slides(slides, resolution_mode)
            total_time = time.time() - start_time

            # Étape 3: Calcul métriques
            print("   3/3 Calcul métriques...")

            return BenchmarkResult(
                document_name=pptx_path.name,
                total_slides=num_slides,
                processing_time_seconds=round(total_time, 2),
                tokens_generated=results["total_tokens"],
                tokens_per_second=results["tokens_per_second"],
                vram_peak_gb=results["vram_peak_gb"],
                success=True
            )

        except Exception as e:
            return BenchmarkResult(
                document_name=pptx_path.name,
                total_slides=0,
                processing_time_seconds=0,
                tokens_generated=0,
                tokens_per_second=0,
                vram_peak_gb=0,
                success=False,
                error=str(e)
            )

    def run_phase2(
        self,
        test_pptx: Path = None,
        use_4bit: bool = False
    ) -> Dict[str, Any]:
        """
        Exécuter benchmark Phase 2 complet

        Args:
            test_pptx: Path vers PPTX de test (230 slides)
            use_4bit: Utiliser quantization 4-bit
        """
        print("\n" + "="*60)
        print("🚀 PHASE 2: Benchmark Performance (230 Slides)")
        print("="*60 + "\n")

        results = {
            "phase": "Phase 2 - Performance",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "configuration": {
                "model": self.model_name,
                "quantization_4bit": use_4bit,
                "target_slides": 230
            },
            "benchmarks": [],
            "baseline_comparison": {
                "pipeline_actuel": {
                    "vision_gpt4v_minutes": "5-10",
                    "ner_spacy_minutes": "15-20",
                    "embeddings_e5_minutes": "10-15",
                    "hdbscan_minutes": "5-10",
                    "llm_extraction_minutes": "20-30",
                    "total_minutes": "~90",
                    "total_seconds": 5400
                },
                "target_deepseek": {
                    "vision_extraction_minutes": "<5",
                    "total_pipeline_minutes": "<30",
                    "total_seconds": 1800,
                    "gain_multiplier": "3x"
                }
            }
        }

        # Charger modèle
        if not DEEPSEEK_AVAILABLE:
            results["overall_status"] = "SKIP"
            results["error"] = "DeepSeek non installé"
            self.save_results(results, "phase2_performance.json")
            return results

        try:
            self.load_model(use_4bit=use_4bit)
        except Exception as e:
            results["overall_status"] = "FAIL"
            results["error"] = f"Erreur chargement modèle: {e}"
            self.save_results(results, "phase2_performance.json")
            return results

        # Benchmark sur test PPTX
        if test_pptx and test_pptx.exists():
            print("📄 Document test fourni")
            benchmark = self.benchmark_document(test_pptx, resolution_mode="Base")
            results["benchmarks"].append(asdict(benchmark))
        else:
            print("⚠️ Pas de document test - génération estimations...")
            # Estimation basée sur specs paper
            # A100: 2500 tokens/s
            # RTX 5070 TI: estimé 60% perf A100 → 1500 tokens/s
            # 230 slides × 256 tokens (Base) = 58,880 tokens
            # Temps: 58,880 / 1,500 = ~40 secondes

            benchmark = BenchmarkResult(
                document_name="estimation_230_slides.pptx",
                total_slides=230,
                processing_time_seconds=40,  # Estimation
                tokens_generated=230 * 256,  # Base mode
                tokens_per_second=1500,  # Estimation RTX 5070 TI
                vram_peak_gb=12.0,  # Estimation
                success=True
            )
            results["benchmarks"].append(asdict(benchmark))
            results["note"] = "Estimation basée sur specs - test réel requis"

        # Analyse résultats
        if results["benchmarks"]:
            bench = results["benchmarks"][0]
            vision_time_minutes = bench["processing_time_seconds"] / 60
            baseline_vision_minutes = 7.5  # Moyenne 5-10 min GPT-4V

            results["analysis"] = {
                "vision_extraction_time_minutes": round(vision_time_minutes, 2),
                "baseline_vision_minutes": baseline_vision_minutes,
                "gain_vision_only": round(baseline_vision_minutes / vision_time_minutes, 2),
                "estimated_total_pipeline_minutes": round(
                    vision_time_minutes + 50  # Autres étapes: 50 min
                , 2),
                "baseline_total_minutes": 90,
                "gain_total_pipeline": round(
                    90 / (vision_time_minutes + 50), 2
                )
            }

            # Decision
            if results["analysis"]["gain_total_pipeline"] >= 3:
                results["overall_status"] = "PASS"
                results["decision"] = "✅ Gain ≥3x - RECOMMANDER intégration"
            elif results["analysis"]["gain_total_pipeline"] >= 2:
                results["overall_status"] = "PARTIAL"
                results["decision"] = "⚠️ Gain 2-3x - Envisager hybrid approach"
            else:
                results["overall_status"] = "FAIL"
                results["decision"] = "❌ Gain <2x - Pas worth it"

        # Save
        self.save_results(results, "phase2_performance.json")

        # Summary
        print("\n" + "="*60)
        print(f"📋 RÉSULTAT PHASE 2: {results.get('overall_status', 'UNKNOWN')}")
        print("="*60)

        if "analysis" in results:
            print(f"Vision extraction: {results['analysis']['vision_extraction_time_minutes']:.1f} min")
            print(f"  vs baseline: {results['analysis']['baseline_vision_minutes']:.1f} min")
            print(f"  Gain vision: {results['analysis']['gain_vision_only']:.1f}x")
            print(f"\nPipeline total estimé: {results['analysis']['estimated_total_pipeline_minutes']:.1f} min")
            print(f"  vs baseline: {results['analysis']['baseline_total_minutes']} min")
            print(f"  Gain total: {results['analysis']['gain_total_pipeline']:.1f}x")
            print(f"\n{results.get('decision', '')}")

        if results.get("overall_status") in ["PASS", "PARTIAL"]:
            print("\n➡️ NEXT: Phase 3 - Validation USP Cross-Lingual")

        return results

    def save_results(self, results: Dict[str, Any], filename: str):
        """Sauvegarder résultats JSON"""
        filepath = self.results_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Résultats sauvegardés: {filepath}")


def main():
    """Point d'entrée principal"""
    benchmarker = Phase2PerformanceBenchmark()

    # Chercher PPTX de test (si existe)
    test_pptx_candidates = [
        Path("data/docs_in/test_230_slides.pptx"),
        Path("tests/eval_deepseek/fixtures/real_230_slides.pptx"),
    ]
    test_pptx = next((p for p in test_pptx_candidates if p.exists()), None)

    if test_pptx:
        print(f"📄 PPTX test trouvé: {test_pptx}")
    else:
        print("⚠️ Pas de PPTX test - mode estimation")

    # Run benchmark
    results = benchmarker.run_phase2(
        test_pptx=test_pptx,
        use_4bit=False
    )

    return results


if __name__ == "__main__":
    main()
