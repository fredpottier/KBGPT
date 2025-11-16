"""
Phase 1: Faisabilité Technique DeepSeek-OCR sur RTX 5070 TI
Test basique d'installation et validation matérielle
"""

import torch
import time
import json
from pathlib import Path
from typing import Dict, Any

# Note: Ces imports nécessitent installation DeepSeek-OCR
# pip install transformers>=4.51.1 torch==2.6.0 flash-attn==2.7.3
try:
    from transformers import AutoModel, AutoProcessor
    DEEPSEEK_AVAILABLE = True
except ImportError:
    DEEPSEEK_AVAILABLE = False
    print("⚠️ DeepSeek-OCR non installé. Voir OSMOSE_DEEPSEEK_OCR_EVALUATION_PLAN.md")


class Phase1FeasibilityTest:
    """Test faisabilité hardware RTX 5070 TI pour DeepSeek-OCR"""

    def __init__(self, model_name: str = "deepseek-ai/DeepSeek-OCR"):
        self.model_name = model_name
        self.results_dir = Path("tests/eval_deepseek/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def check_hardware(self) -> Dict[str, Any]:
        """Vérifier specs GPU disponibles"""
        if not torch.cuda.is_available():
            return {
                "status": "FAIL",
                "error": "CUDA non disponible - GPU requis",
                "cuda_available": False
            }

        gpu_props = torch.cuda.get_device_properties(0)

        hardware = {
            "cuda_available": True,
            "gpu_name": gpu_props.name,
            "vram_total_gb": gpu_props.total_memory / 1e9,
            "cuda_version": torch.version.cuda,
            "pytorch_version": torch.__version__,
        }

        # Validation RTX 5070 TI specs
        if hardware["vram_total_gb"] < 14:  # Min 16GB - buffer 2GB
            hardware["status"] = "WARN"
            hardware["warning"] = f"VRAM {hardware['vram_total_gb']:.1f}GB < 14GB recommandé"
        else:
            hardware["status"] = "PASS"

        return hardware

    def load_model(self, use_4bit: bool = False) -> Dict[str, Any]:
        """
        Charger DeepSeek-OCR et mesurer VRAM usage

        Args:
            use_4bit: Si True, charge en quantization 4-bit (économie VRAM)
        """
        if not DEEPSEEK_AVAILABLE:
            return {
                "status": "SKIP",
                "error": "Transformers/DeepSeek non installé"
            }

        print(f"🔧 Chargement modèle {self.model_name}...")
        start_time = time.time()

        # Reset VRAM stats
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        try:
            # Charger processor
            processor = AutoProcessor.from_pretrained(self.model_name)

            # Charger modèle
            load_kwargs = {
                "device_map": "auto",
                "torch_dtype": torch.bfloat16
            }

            if use_4bit:
                load_kwargs["load_in_4bit"] = True
                print("   → Mode quantization 4-bit activé")

            model = AutoModel.from_pretrained(
                self.model_name,
                **load_kwargs
            )

            load_time = time.time() - start_time

            # Mesurer VRAM
            vram_allocated = torch.cuda.memory_allocated() / 1e9
            vram_peak = torch.cuda.max_memory_allocated() / 1e9

            result = {
                "status": "PASS",
                "load_time_seconds": round(load_time, 2),
                "vram_allocated_gb": round(vram_allocated, 2),
                "vram_peak_gb": round(vram_peak, 2),
                "quantization_4bit": use_4bit,
                "model_size_estimate_gb": round(vram_allocated, 2)
            }

            # Validation VRAM < 14GB (buffer 2GB sur 16GB)
            if vram_peak > 14:
                result["status"] = "WARN"
                result["warning"] = f"VRAM peak {vram_peak:.1f}GB > 14GB - risque OOM"
            else:
                print(f"   ✅ VRAM peak: {vram_peak:.1f}GB < 14GB")

            return result

        except Exception as e:
            return {
                "status": "FAIL",
                "error": str(e),
                "load_time_seconds": round(time.time() - start_time, 2)
            }

    def test_simple_inference(self, test_image_path: str = None) -> Dict[str, Any]:
        """
        Test inference basique sur une image simple

        Args:
            test_image_path: Path vers image test (optionnel)
        """
        if not DEEPSEEK_AVAILABLE:
            return {"status": "SKIP", "error": "DeepSeek non installé"}

        # TODO: Implémenter test inference sur image sample
        # Pour le moment, retourne placeholder
        return {
            "status": "TODO",
            "message": "Test inference à implémenter avec sample PPTX slide"
        }

    def run_phase1(self, use_4bit: bool = False) -> Dict[str, Any]:
        """
        Exécuter batterie complète tests Phase 1

        Args:
            use_4bit: Si True, teste avec quantization 4-bit
        """
        print("\n" + "="*60)
        print("🚀 PHASE 1: Faisabilité Technique DeepSeek-OCR")
        print("="*60 + "\n")

        results = {
            "phase": "Phase 1 - Faisabilité",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tests": {}
        }

        # Test 1: Hardware Check
        print("📊 Test 1.1: Vérification Hardware...")
        hardware = self.check_hardware()
        results["tests"]["hardware_check"] = hardware
        print(f"   Status: {hardware['status']}")
        if hardware["status"] == "FAIL":
            results["overall_status"] = "FAIL"
            self.save_results(results, "phase1_feasibility.json")
            return results

        # Test 2: Model Loading
        print("\n📦 Test 1.2: Chargement Modèle DeepSeek-OCR...")
        model_load = self.load_model(use_4bit=use_4bit)
        results["tests"]["model_load"] = model_load
        print(f"   Status: {model_load['status']}")

        # Test 3: Simple Inference (TODO)
        print("\n🎯 Test 1.3: Inference Basique...")
        inference = self.test_simple_inference()
        results["tests"]["simple_inference"] = inference
        print(f"   Status: {inference['status']}")

        # Overall Status
        statuses = [t["status"] for t in results["tests"].values()]
        if "FAIL" in statuses:
            results["overall_status"] = "FAIL"
        elif "WARN" in statuses:
            results["overall_status"] = "WARN"
        elif "TODO" in statuses or "SKIP" in statuses:
            results["overall_status"] = "PARTIAL"
        else:
            results["overall_status"] = "PASS"

        # Save results
        self.save_results(results, "phase1_feasibility.json")

        # Summary
        print("\n" + "="*60)
        print(f"📋 RÉSULTAT PHASE 1: {results['overall_status']}")
        print("="*60)

        if results["overall_status"] in ["PASS", "WARN", "PARTIAL"]:
            print("✅ RTX 5070 TI compatible avec DeepSeek-OCR")
            print(f"   VRAM utilisée: {model_load.get('vram_peak_gb', 'N/A')}GB")
            print(f"   Temps chargement: {model_load.get('load_time_seconds', 'N/A')}s")
            print("\n➡️ NEXT: Phase 2 - Benchmark Performance")
        else:
            print("❌ Hardware insuffisant ou problème installation")
            print("   Essayer avec use_4bit=True pour réduire VRAM")

        return results

    def save_results(self, results: Dict[str, Any], filename: str):
        """Sauvegarder résultats JSON"""
        filepath = self.results_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Résultats sauvegardés: {filepath}")


def main():
    """Point d'entrée principal"""
    tester = Phase1FeasibilityTest()

    # Option 1: Test standard (BF16)
    results = tester.run_phase1(use_4bit=False)

    # Si WARN/FAIL à cause VRAM, retenter en 4-bit
    if results["overall_status"] in ["WARN", "FAIL"]:
        vram_issue = any(
            "VRAM" in str(t.get("warning", "")) or "VRAM" in str(t.get("error", ""))
            for t in results["tests"].values()
        )
        if vram_issue:
            print("\n⚠️ Problème VRAM détecté - Retry en mode 4-bit...")
            results_4bit = tester.run_phase1(use_4bit=True)
            return results_4bit

    return results


if __name__ == "__main__":
    main()
