#!/usr/bin/env python3
"""
OSMOSE Burst Mode - Benchmark LLM Extraction
Compare vLLM (Qwen 2.5 14B AWQ) vs ChatGPT (gpt-4o-mini) pour l'extraction de concepts.

Usage:
    python scripts/benchmark_llm_extraction.py --vllm-url http://IP:8000 --chunks 5

Output:
    - Console: Résumé comparatif
    - Fichier: data/benchmark_llm_YYYYMMDD_HHMMSS.json
"""

import asyncio
import json
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Optional, Any
import httpx
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()


# ============================================================================
# Configuration
# ============================================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"  # Modèle utilisé en production

VLLM_MODEL = "/models/Qwen--Qwen2.5-14B-Instruct-AWQ"

# Prompt d'extraction (identique à concept_extractor.py)
EXTRACTION_PROMPT_FR = """Extrait les concepts clés du texte suivant.

Pour chaque concept, identifie :
- name : le nom du concept (2-50 caractères, utilise les noms officiels complets)
- type : un parmi [ENTITY, PRACTICE, STANDARD, TOOL, ROLE]
- definition : une brève définition (1 phrase)
- relationships : liste de noms de concepts liés (max 3)

TEXTE DU SEGMENT :
{text}

Retourne un objet JSON avec cette structure exacte:
{{"concepts": [{{"name": "...", "type": "...", "definition": "...", "relationships": [...]}}]}}

Extrait 10-20 concepts. Sois exhaustif - inclus toutes les entités nommées, méthodologies, normes, outils et termes du domaine."""


# ============================================================================
# Domain Context (simplifié pour benchmark)
# ============================================================================

def get_domain_context_section(tenant_id: str = "default") -> str:
    """Récupère le domain context depuis PostgreSQL."""
    try:
        from knowbase.ontology.domain_context_store import get_domain_context_store
        store = get_domain_context_store()
        profile = store.get_profile(tenant_id)

        if not profile:
            return ""

        section = f"""[DOMAIN CONTEXT - Priority: {profile.context_priority.upper()}]
{profile.llm_injection_prompt}"""

        if profile.common_acronyms:
            acronyms_list = [
                f"- {acronym}: {expansion}"
                for acronym, expansion in list(profile.common_acronyms.items())[:15]
            ]
            section += f"\n\nCommon acronyms in this domain:\n" + "\n".join(acronyms_list)

        if profile.key_concepts:
            section += f"\n\nKey concepts to recognize:\n{', '.join(profile.key_concepts[:10])}"

        section += "\n[END DOMAIN CONTEXT]"
        return section
    except Exception as e:
        print(f"Warning: Could not load domain context: {e}")
        return ""


# ============================================================================
# Sample Chunks (pour tests sans DB)
# ============================================================================

SAMPLE_CHUNKS = [
    {
        "id": "sample_1",
        "text": """La directive NIS2 renforce considérablement les exigences en matière de cybersécurité
pour les entreprises européennes. SAP S/4HANA Cloud offre des fonctionnalités de conformité intégrées
permettant d'automatiser les contrôles SOX et GDPR. Le Chief Information Security Officer (CISO) doit
maintenant superviser la mise en œuvre du Zero Trust Architecture et coordonner avec le Data Protection
Officer (DPO) pour assurer la conformité réglementaire.""",
        "language": "fr",
        "source": "cybersecurity_compliance.pptx"
    },
    {
        "id": "sample_2",
        "text": """L'approche DevSecOps intègre la sécurité dès le début du cycle de développement.
Les équipes utilisent des outils comme SonarQube pour l'analyse statique du code et Snyk pour
la détection des vulnérabilités dans les dépendances. Le pipeline CI/CD inclut des tests de sécurité
automatisés avec OWASP ZAP pour les tests dynamiques. La méthodologie Agile SAFe permet une
intégration fluide des pratiques de sécurité dans les sprints.""",
        "language": "fr",
        "source": "devsecops_practices.pptx"
    },
    {
        "id": "sample_3",
        "text": """Le ransomware LockBit 3.0 a causé des dommages estimés à 500 millions d'euros
en Europe. Les mesures de protection incluent la segmentation réseau, les sauvegardes air-gapped,
et la formation des utilisateurs contre le phishing. Le framework MITRE ATT&CK permet de cartographier
les tactiques adverses. L'ANSSI recommande l'implémentation du référentiel EBIOS Risk Manager
pour l'analyse des risques cyber.""",
        "language": "fr",
        "source": "ransomware_defense.pptx"
    },
    {
        "id": "sample_4",
        "text": """SAP Business Technology Platform (BTP) permet d'étendre les fonctionnalités de
SAP S/4HANA via des extensions side-by-side. Le SAP Integration Suite connecte les systèmes on-premise
aux services cloud. Les développeurs utilisent SAP CAP (Cloud Application Programming) et SAP Fiori
pour créer des applications métier. Le modèle Clean Core garantit que les personnalisations
n'impactent pas les mises à jour du système central.""",
        "language": "fr",
        "source": "sap_btp_overview.pptx"
    },
    {
        "id": "sample_5",
        "text": """L'Intelligence Artificielle générative transforme les processus métier. ChatGPT et
Claude sont utilisés pour l'automatisation du support client. SAP Joule intègre l'IA dans les
processus ERP. Les modèles de langage (LLM) comme GPT-4, Llama 3, et Qwen permettent l'extraction
automatique de connaissances. Le RAG (Retrieval-Augmented Generation) améliore la précision
des réponses en s'appuyant sur une base documentaire.""",
        "language": "fr",
        "source": "generative_ai_enterprise.pptx"
    }
]


# ============================================================================
# LLM Clients
# ============================================================================

async def call_vllm(
    text: str,
    domain_context: str,
    vllm_url: str,
    timeout: float = 60.0
) -> Dict[str, Any]:
    """Appelle vLLM pour extraction de concepts."""
    prompt = EXTRACTION_PROMPT_FR.format(text=text)
    if domain_context:
        prompt = prompt + "\n\n" + domain_context

    payload = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.1
    }

    start_time = datetime.now()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{vllm_url}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

        elapsed = (datetime.now() - start_time).total_seconds()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return {
            "success": True,
            "content": content,
            "elapsed_seconds": elapsed,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "model": "vLLM/Qwen-2.5-14B-AWQ"
        }
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": elapsed,
            "model": "vLLM/Qwen-2.5-14B-AWQ"
        }


async def call_openai(
    text: str,
    domain_context: str,
    timeout: float = 60.0
) -> Dict[str, Any]:
    """Appelle OpenAI ChatGPT pour extraction de concepts."""
    prompt = EXTRACTION_PROMPT_FR.format(text=text)
    if domain_context:
        prompt = prompt + "\n\n" + domain_context

    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.1
    }

    start_time = datetime.now()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}"
                }
            )
            response.raise_for_status()
            data = response.json()

        elapsed = (datetime.now() - start_time).total_seconds()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return {
            "success": True,
            "content": content,
            "elapsed_seconds": elapsed,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "model": f"OpenAI/{OPENAI_MODEL}"
        }
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": elapsed,
            "model": f"OpenAI/{OPENAI_MODEL}"
        }


# ============================================================================
# Parsing & Analysis
# ============================================================================

def parse_concepts(response_content: str) -> List[Dict]:
    """Parse JSON concepts depuis réponse LLM."""
    import re
    try:
        # Chercher JSON dans la réponse
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if not json_match:
            return []

        data = json.loads(json_match.group(0))
        return data.get("concepts", [])
    except:
        return []


def analyze_concepts(concepts: List[Dict]) -> Dict[str, Any]:
    """Analyse les concepts extraits."""
    if not concepts:
        return {"count": 0, "types": {}, "avg_definition_length": 0}

    types_count = {}
    total_def_length = 0

    for c in concepts:
        ctype = c.get("type", "UNKNOWN")
        types_count[ctype] = types_count.get(ctype, 0) + 1
        total_def_length += len(c.get("definition", ""))

    return {
        "count": len(concepts),
        "types": types_count,
        "avg_definition_length": total_def_length / len(concepts) if concepts else 0,
        "concept_names": [c.get("name", "") for c in concepts[:10]]
    }


# ============================================================================
# Main Benchmark
# ============================================================================

async def run_benchmark(
    vllm_url: str,
    chunks: List[Dict],
    tenant_id: str = "default"
) -> Dict[str, Any]:
    """Execute benchmark sur liste de chunks."""

    print(f"\n{'='*60}")
    print("OSMOSE Burst Mode - LLM Extraction Benchmark")
    print(f"{'='*60}")
    print(f"vLLM URL: {vllm_url}")
    print(f"OpenAI Model: {OPENAI_MODEL}")
    print(f"Chunks to test: {len(chunks)}")
    print(f"{'='*60}\n")

    # Récupérer domain context
    domain_context = get_domain_context_section(tenant_id)
    if domain_context:
        print(f"✅ Domain context loaded ({len(domain_context)} chars)")
    else:
        print("⚠️ No domain context (running without)")
    print()

    results = []

    for i, chunk in enumerate(chunks, 1):
        print(f"[{i}/{len(chunks)}] Processing: {chunk.get('source', 'unknown')}...")

        # Appel parallèle vLLM et OpenAI
        vllm_result, openai_result = await asyncio.gather(
            call_vllm(chunk["text"], domain_context, vllm_url),
            call_openai(chunk["text"], domain_context)
        )

        # Parser les concepts
        vllm_concepts = parse_concepts(vllm_result.get("content", "")) if vllm_result["success"] else []
        openai_concepts = parse_concepts(openai_result.get("content", "")) if openai_result["success"] else []

        # Analyser
        vllm_analysis = analyze_concepts(vllm_concepts)
        openai_analysis = analyze_concepts(openai_concepts)

        chunk_result = {
            "chunk_id": chunk.get("id", f"chunk_{i}"),
            "source": chunk.get("source", "unknown"),
            "text_length": len(chunk["text"]),
            "vllm": {
                **vllm_result,
                "concepts_count": vllm_analysis["count"],
                "concepts_types": vllm_analysis["types"],
                "concepts_names": vllm_analysis.get("concept_names", [])
            },
            "openai": {
                **openai_result,
                "concepts_count": openai_analysis["count"],
                "concepts_types": openai_analysis["types"],
                "concepts_names": openai_analysis.get("concept_names", [])
            }
        }

        results.append(chunk_result)

        # Affichage résumé
        print(f"   vLLM:   {vllm_analysis['count']:2d} concepts | {vllm_result['elapsed_seconds']:.2f}s | {'✅' if vllm_result['success'] else '❌'}")
        print(f"   OpenAI: {openai_analysis['count']:2d} concepts | {openai_result['elapsed_seconds']:.2f}s | {'✅' if openai_result['success'] else '❌'}")
        print()

    # Statistiques globales
    stats = compute_global_stats(results)

    return {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "vllm_url": vllm_url,
            "openai_model": OPENAI_MODEL,
            "tenant_id": tenant_id,
            "domain_context_present": bool(domain_context)
        },
        "results": results,
        "statistics": stats
    }


def compute_global_stats(results: List[Dict]) -> Dict[str, Any]:
    """Calcule statistiques globales."""
    vllm_times = [r["vllm"]["elapsed_seconds"] for r in results if r["vllm"]["success"]]
    openai_times = [r["openai"]["elapsed_seconds"] for r in results if r["openai"]["success"]]

    vllm_concepts = [r["vllm"]["concepts_count"] for r in results if r["vllm"]["success"]]
    openai_concepts = [r["openai"]["concepts_count"] for r in results if r["openai"]["success"]]

    return {
        "vllm": {
            "success_rate": sum(1 for r in results if r["vllm"]["success"]) / len(results) * 100,
            "avg_time_seconds": sum(vllm_times) / len(vllm_times) if vllm_times else 0,
            "avg_concepts": sum(vllm_concepts) / len(vllm_concepts) if vllm_concepts else 0,
            "total_concepts": sum(vllm_concepts)
        },
        "openai": {
            "success_rate": sum(1 for r in results if r["openai"]["success"]) / len(results) * 100,
            "avg_time_seconds": sum(openai_times) / len(openai_times) if openai_times else 0,
            "avg_concepts": sum(openai_concepts) / len(openai_concepts) if openai_concepts else 0,
            "total_concepts": sum(openai_concepts)
        }
    }


def print_summary(benchmark_result: Dict):
    """Affiche résumé du benchmark."""
    stats = benchmark_result["statistics"]

    print(f"\n{'='*60}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"{'Metric':<25} {'vLLM':<15} {'OpenAI':<15}")
    print(f"{'-'*55}")
    print(f"{'Success Rate':<25} {stats['vllm']['success_rate']:.1f}%{'':<10} {stats['openai']['success_rate']:.1f}%")
    print(f"{'Avg Response Time':<25} {stats['vllm']['avg_time_seconds']:.2f}s{'':<10} {stats['openai']['avg_time_seconds']:.2f}s")
    print(f"{'Avg Concepts/Chunk':<25} {stats['vllm']['avg_concepts']:.1f}{'':<12} {stats['openai']['avg_concepts']:.1f}")
    print(f"{'Total Concepts':<25} {stats['vllm']['total_concepts']:<15} {stats['openai']['total_concepts']}")
    print(f"{'='*60}")

    # Comparaison qualitative
    if stats['vllm']['avg_concepts'] > 0 and stats['openai']['avg_concepts'] > 0:
        ratio = stats['vllm']['avg_concepts'] / stats['openai']['avg_concepts']
        if ratio > 1.1:
            print(f"📊 vLLM extrait {(ratio-1)*100:.0f}% plus de concepts")
        elif ratio < 0.9:
            print(f"📊 OpenAI extrait {(1/ratio-1)*100:.0f}% plus de concepts")
        else:
            print("📊 Quantité de concepts comparable")

    if stats['vllm']['avg_time_seconds'] > 0 and stats['openai']['avg_time_seconds'] > 0:
        speed_ratio = stats['openai']['avg_time_seconds'] / stats['vllm']['avg_time_seconds']
        if speed_ratio > 1.2:
            print(f"⚡ vLLM est {speed_ratio:.1f}x plus rapide")
        elif speed_ratio < 0.8:
            print(f"⚡ OpenAI est {1/speed_ratio:.1f}x plus rapide")
        else:
            print("⚡ Vitesse comparable")


# ============================================================================
# Entry Point
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Benchmark vLLM vs OpenAI for concept extraction")
    parser.add_argument("--vllm-url", required=True, help="vLLM server URL (e.g., http://IP:8000)")
    parser.add_argument("--chunks", type=int, default=5, help="Number of sample chunks to test")
    parser.add_argument("--tenant", default="default", help="Tenant ID for domain context")
    parser.add_argument("--output", default=None, help="Output JSON file path")

    args = parser.parse_args()

    # Sélectionner chunks
    chunks = SAMPLE_CHUNKS[:args.chunks]

    # Exécuter benchmark
    result = await run_benchmark(args.vllm_url, chunks, args.tenant)

    # Afficher résumé
    print_summary(result)

    # Sauvegarder résultats
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data/benchmark_llm_{timestamp}.json"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n📁 Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
