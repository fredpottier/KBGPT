#!/usr/bin/env python3
"""
🌊 OSMOSE - Analyse des Coûts LLM (OpenAI vs Gemini)

Analyse les logs de tokens du dernier import et compare les coûts
entre OpenAI et Google Gemini.

Usage:
    docker logs knowbase-worker --tail 20000 2>&1 | python scripts/analyze_llm_costs.py

    # Ou depuis le conteneur:
    docker-compose exec app bash -c "docker logs knowbase-worker --tail 20000 2>&1 | python scripts/analyze_llm_costs.py"
"""

import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

# === TARIFS OpenAI (Novembre 2024) ===
OPENAI_PRICES = {
    "gpt-4o-mini": {
        "input": 0.150 / 1_000_000,   # $0.150 per 1M input tokens
        "output": 0.600 / 1_000_000,  # $0.600 per 1M output tokens
    },
    "gpt-4o": {
        "input": 2.50 / 1_000_000,    # $2.50 per 1M input tokens
        "output": 10.00 / 1_000_000,  # $10.00 per 1M output tokens
    },
    "gpt-4o-2024-11-20": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-4-turbo": {
        "input": 10.00 / 1_000_000,
        "output": 30.00 / 1_000_000,
    },
    "text-embedding-3-large": {
        "input": 0.130 / 1_000_000,   # $0.13 per 1M tokens
        "output": 0.0,
    }
}

# === TARIFS Google Gemini (Novembre 2024) ===
# https://ai.google.dev/pricing
GEMINI_PRICES = {
    "gemini-1.5-flash": {
        "input": 0.075 / 1_000_000,   # $0.075 per 1M input tokens (< 128k context)
        "output": 0.300 / 1_000_000,  # $0.300 per 1M output tokens
        "input_cached": 0.01875 / 1_000_000,  # $0.01875 per 1M cached tokens
    },
    "gemini-1.5-flash-8b": {
        "input": 0.0375 / 1_000_000,  # $0.0375 per 1M input tokens
        "output": 0.150 / 1_000_000,  # $0.150 per 1M output tokens
        "input_cached": 0.01 / 1_000_000,
    },
    "gemini-1.5-pro": {
        "input": 1.25 / 1_000_000,    # $1.25 per 1M input tokens (< 128k context)
        "output": 5.00 / 1_000_000,   # $5.00 per 1M output tokens
        "input_cached": 0.3125 / 1_000_000,
    },
    "gemini-2.0-flash-exp": {
        "input": 0.0,                 # FREE (experimental)
        "output": 0.0,
    }
}

# === MAPPING OpenAI → Gemini équivalent ===
GEMINI_EQUIVALENT = {
    "gpt-4o-mini": "gemini-1.5-flash-8b",     # Mini → Flash 8B (le plus économique)
    "gpt-4o": "gemini-1.5-flash",             # GPT-4o → Flash (bon rapport qualité/prix)
    "gpt-4o-2024-11-20": "gemini-1.5-flash",
    "gpt-4-turbo": "gemini-1.5-pro",          # Turbo → Pro (haute qualité)
}


def parse_log_line(line: str) -> Tuple[str, str, int, int, float]:
    """
    Parse une ligne de log TOKEN_TRACKER.

    Returns:
        (model, task, input_tokens, output_tokens, cost)
    """
    # Pattern: [TOKEN_TRACKER] model (task) - In: X, Out: Y, Cost: $Z -
    pattern = r'\[TOKEN_TRACKER\]\s+(\S+)\s+\(([^)]+)\)\s+-\s+In:\s+(\d+),\s+Out:\s+(\d+),\s+Cost:\s+\$([0-9.]+)'
    match = re.search(pattern, line)

    if match:
        model = match.group(1)
        task = match.group(2)
        input_tokens = int(match.group(3))
        output_tokens = int(match.group(4))
        cost = float(match.group(5))
        return (model, task, input_tokens, output_tokens, cost)

    return None


def calculate_gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calcule le coût Gemini pour un appel équivalent."""
    gemini_model = GEMINI_EQUIVALENT.get(model, "gemini-1.5-flash")
    pricing = GEMINI_PRICES.get(gemini_model, GEMINI_PRICES["gemini-1.5-flash"])

    cost = (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
    return cost


def main():
    print("=" * 80)
    print("🌊 OSMOSE - Analyse des Coûts LLM (OpenAI vs Gemini)")
    print("=" * 80)
    print()

    # Lire depuis stdin
    lines = sys.stdin.readlines()

    # Filtrer lignes TOKEN_TRACKER
    token_lines = [l for l in lines if "[TOKEN_TRACKER]" in l]

    if not token_lines:
        print("❌ Aucune ligne [TOKEN_TRACKER] trouvée dans les logs")
        print()
        print("Usage:")
        print("  docker logs knowbase-worker --tail 20000 2>&1 | python scripts/analyze_llm_costs.py")
        sys.exit(1)

    # Statistiques par modèle et tâche
    stats = defaultdict(lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "openai_cost": 0.0,
        "gemini_cost": 0.0,
    })

    # Parser les logs
    for line in token_lines:
        parsed = parse_log_line(line)
        if parsed:
            model, task, input_tok, output_tok, openai_cost = parsed

            key = f"{model} ({task})"
            stats[key]["calls"] += 1
            stats[key]["input_tokens"] += input_tok
            stats[key]["output_tokens"] += output_tok
            stats[key]["openai_cost"] += openai_cost

            # Calculer coût Gemini équivalent
            gemini_cost = calculate_gemini_cost(model, input_tok, output_tok)
            stats[key]["gemini_cost"] += gemini_cost

    # Afficher résultats
    print(f"📊 Logs analysés: {len(token_lines)} lignes TOKEN_TRACKER")
    print(f"📋 Appels LLM uniques détectés: {len(stats)}")
    print()

    # Totaux globaux
    total_calls = sum(s["calls"] for s in stats.values())
    total_input = sum(s["input_tokens"] for s in stats.values())
    total_output = sum(s["output_tokens"] for s in stats.values())
    total_openai = sum(s["openai_cost"] for s in stats.values())
    total_gemini = sum(s["gemini_cost"] for s in stats.values())

    # Détail par type d'appel
    print("=" * 80)
    print("📈 DÉTAIL PAR TYPE D'APPEL LLM")
    print("=" * 80)
    print()

    for key in sorted(stats.keys()):
        s = stats[key]
        model_task = key
        model = key.split(" (")[0]
        gemini_equiv = GEMINI_EQUIVALENT.get(model, "gemini-1.5-flash")

        savings = s["openai_cost"] - s["gemini_cost"]
        savings_pct = (savings / s["openai_cost"] * 100) if s["openai_cost"] > 0 else 0

        print(f"🔹 {model_task}")
        print(f"   Appels:         {s['calls']:,}")
        print(f"   Tokens IN:      {s['input_tokens']:,} (avg: {s['input_tokens']//s['calls'] if s['calls'] > 0 else 0})")
        print(f"   Tokens OUT:     {s['output_tokens']:,} (avg: {s['output_tokens']//s['calls'] if s['calls'] > 0 else 0})")
        print(f"   OpenAI ({model}):")
        print(f"     Coût total:   ${s['openai_cost']:.4f}")
        print(f"   Gemini ({gemini_equiv}):")
        print(f"     Coût total:   ${s['gemini_cost']:.4f}")
        print(f"   💰 Économie:    ${savings:.4f} ({savings_pct:+.1f}%)")
        print()

    # Résumé global
    print("=" * 80)
    print("💰 RÉSUMÉ GLOBAL - COMPARAISON OPENAI vs GEMINI")
    print("=" * 80)
    print()

    print(f"📊 Volume total:")
    print(f"   Appels LLM:          {total_calls:,}")
    print(f"   Tokens INPUT:        {total_input:,}")
    print(f"   Tokens OUTPUT:       {total_output:,}")
    print(f"   Tokens TOTAL:        {total_input + total_output:,}")
    print()

    print(f"💵 Coûts OpenAI:")
    print(f"   Coût total:          ${total_openai:.4f}")
    print(f"   Coût par appel:      ${total_openai/total_calls:.6f}")
    print(f"   Coût par 1k tokens:  ${total_openai / ((total_input + total_output) / 1000):.6f}")
    print()

    print(f"💚 Coûts Gemini (équivalent):")
    print(f"   Coût total:          ${total_gemini:.4f}")
    print(f"   Coût par appel:      ${total_gemini/total_calls:.6f}")
    print(f"   Coût par 1k tokens:  ${total_gemini / ((total_input + total_output) / 1000):.6f}")
    print()

    savings_total = total_openai - total_gemini
    savings_pct_total = (savings_total / total_openai * 100) if total_openai > 0 else 0

    print(f"🎯 ÉCONOMIE TOTALE:")
    print(f"   Montant:             ${savings_total:.4f}")
    print(f"   Pourcentage:         {savings_pct_total:+.1f}%")
    print()

    if savings_total > 0:
        print(f"✅ Gemini serait {savings_pct_total:.1f}% MOINS CHER qu'OpenAI pour cet import")
    elif savings_total < 0:
        print(f"⚠️  OpenAI serait {-savings_pct_total:.1f}% moins cher que Gemini pour cet import")
    else:
        print(f"⚖️  Coûts équivalents entre OpenAI et Gemini")

    print()

    # Projection pour 100 documents
    print("=" * 80)
    print("📊 PROJECTION POUR 100 DOCUMENTS (même volumétrie)")
    print("=" * 80)
    print()
    print(f"OpenAI:  ${total_openai * 100:.2f}")
    print(f"Gemini:  ${total_gemini * 100:.2f}")
    print(f"Économie: ${savings_total * 100:.2f} ({savings_pct_total:+.1f}%)")
    print()

    # Recommendations
    print("=" * 80)
    print("💡 RECOMMANDATIONS")
    print("=" * 80)
    print()

    print("🔹 Modèles équivalents suggérés:")
    for openai_model, gemini_model in GEMINI_EQUIVALENT.items():
        if any(openai_model in k for k in stats.keys()):
            gemini_price = GEMINI_PRICES[gemini_model]
            print(f"   {openai_model:20} → {gemini_model:25} (${gemini_price['input']*1_000_000:.3f}/M in, ${gemini_price['output']*1_000_000:.3f}/M out)")

    print()
    print("🔹 Optimisations possibles:")
    print("   • Utiliser Gemini Flash 8B pour extraction simple (75% moins cher)")
    print("   • Activer le caching Gemini pour réduire coûts input de 75%")
    print("   • Tester Gemini 2.0 Flash Exp (GRATUIT en preview)")
    print()

    print("=" * 80)
    print("✅ Analyse terminée")
    print("=" * 80)


if __name__ == "__main__":
    main()
