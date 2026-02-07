# tests/claimfirst/test_claim_prompt_v2.py
"""
Test comparatif Prompt V1 vs V2 pour l'extraction de claims.

Objectif : mesurer l'augmentation de claims catégorie A (composables avec S/P/O)
en enrichissant le prompt avec le Domain Context et le Section Context.

Usage :
    Nécessite OPENAI_API_KEY. Exécuter depuis le container app :
    docker-compose exec app python -m tests.claimfirst.test_claim_prompt_v2
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================================
# PROMPT V1 (actuel)
# ============================================================================

PROMPT_V1 = """Tu es un expert en extraction d'assertions documentées.

Tu reçois des unités de texte numérotées (U1, U2, etc.) provenant d'un document.
Ta tâche est d'identifier les CLAIMS - des affirmations précises et documentées.

## Charte de la bonne Claim

1. Dit UNE chose précise (pas de liste, pas de généralité)
2. Supportée par le texte verbatim (tu POINTES vers l'unité, tu ne COPIES PAS)
3. Jamais exhaustive (mieux vaut plusieurs claims précises qu'une vague)
4. Contextuelle si applicable (version, région, édition)
5. N'infère rien (ne déduis pas ce qui n'est pas dit explicitement)
6. Peut NE PAS exister si le texte est trop vague

## Types de Claims

- FACTUAL: Assertion factuelle vérifiable ("TLS 1.2 is supported")
- PRESCRIPTIVE: Obligation/interdiction ("Customers must enable MFA")
- DEFINITIONAL: Définition/description ("SAP BTP is a platform...")
- CONDITIONAL: Assertion conditionnelle ("If data exceeds 1TB, then...")
- PERMISSIVE: Permission ("Customers may configure...")
- PROCEDURAL: Étape/processus ("To enable SSO, first configure...")

## Format de réponse (JSON)

Retourne un tableau JSON de claims. Exemple:
[
  {{
    "claim_text": "Formulation synthétique de la claim",
    "claim_type": "FACTUAL",
    "unit_id": "U1",
    "confidence": 0.95,
    "scope": {{"version": null, "region": null, "edition": null, "conditions": []}}
  }}
]

## Règles STRICTES

- NE COPIE JAMAIS le texte. Utilise UNIQUEMENT les unit_ids.
- Si une unité ne contient pas de claim claire, IGNORE-LA.
- Si le texte est vague ou générique, retourne un tableau vide [].
- Préfère l'abstention à l'invention.

## Unités à analyser

{units_text}

## Contexte du document

Titre: {doc_title}
Type: {doc_type}

Retourne UNIQUEMENT le tableau JSON, sans explication."""


# ============================================================================
# PROMPT V2 (enrichi)
# ============================================================================

PROMPT_V2 = """Tu es un expert en extraction de connaissances structurées à partir de documents.

Tu reçois des unités de texte numérotées (U1, U2, etc.) provenant d'un document.
Ta tâche est d'identifier les CLAIMS — des affirmations précises, documentées et utiles
pour construire un graphe de connaissances.

{domain_context}
## Contexte documentaire

Titre : {doc_title}
Type : {doc_type}
Sujet principal : {doc_subject}
Section actuelle : {section_title}
Concepts clés de cette section : {section_concepts}

## Grille de valeur (IMPORTANT)

Toutes les claims n'ont pas la même valeur. Privilégie dans cet ordre :

**FORTE VALEUR** — Claims relationnelles entre deux entités nommées :
- X utilise / est basé sur / nécessite Y
- X remplace / succède à Y
- X est intégré dans / embarqué dans Y
- X est compatible avec / supporte Y
→ Pour ces claims, remplis le champ `structured_form`.

**VALEUR MOYENNE** — Claims factuelles spécifiques avec un sujet identifiable :
- X offre telle capacité précise
- X a telle limitation / contrainte
→ `structured_form` = null

**NE PAS EXTRAIRE** :
- Fragments sans verbe ni sujet identifiable ("reduce costs", "improve tracking")
- Actions utilisateur génériques sans spécificité ("You can define...", "Users can create...")
  SAUF si elles révèlent une capacité technique spécifique
- Reformulations de titres de section
- Textes juridiques, disclaimers, copyrights

## Types de Claims

- FACTUAL : Assertion factuelle vérifiable
- PRESCRIPTIVE : Obligation ou interdiction
- DEFINITIONAL : Définition ou description
- CONDITIONAL : Assertion conditionnelle
- PERMISSIVE : Permission ou autorisation
- PROCEDURAL : Étape ou processus

## Format de réponse (JSON)

[
  {{
    "claim_text": "Formulation synthétique et autonome de la claim",
    "claim_type": "FACTUAL",
    "unit_id": "U1",
    "confidence": 0.95,
    "scope": {{"version": null, "region": null, "edition": null, "conditions": []}},
    "structured_form": {{
      "subject": "Nom de l'entité sujet",
      "predicate": "USES|REQUIRES|REPLACES|BASED_ON|INTEGRATED_IN|SUPPORTS|ENABLES|CONFIGURES",
      "object": "Nom de l'entité objet"
    }}
  }}
]

Notes sur structured_form :
- Remplis-le UNIQUEMENT si la claim exprime une relation claire entre deux entités nommées.
- Le subject et l'object doivent être des noms propres ou termes techniques, pas des descriptions.
- Si pas de relation → "structured_form": null
- Prédicats autorisés : USES, REQUIRES, REPLACES, BASED_ON, INTEGRATED_IN, SUPPORTS,
  ENABLES, CONFIGURES, COMPATIBLE_WITH, PROVIDES, EXTENDS, DEPENDS_ON

## Règles

- NE COPIE PAS le texte. Pointe vers les unit_ids.
- Si une unité ne contient pas de claim utile, IGNORE-LA.
- La claim doit être autonome et compréhensible sans lire l'unité source.
- Préfère l'abstention à l'invention. Préfère la précision à la quantité.

## Unités à analyser

{units_text}

Retourne UNIQUEMENT le tableau JSON, sans explication."""


# ============================================================================
# DONNÉES DE TEST (passages réels de Neo4j)
# ============================================================================

TEST_PASSAGES = [
    # ── 1. Intégration: Manufacturing Execution Connect ──
    {
        "id": "P01_mfg_connect",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Manufacturing Execution",
        "section_concepts": "MES, manufacturing execution, process control, data exchange, transition",
        "text": (
            "Manufacturing Execution Connect (classic) provides features for exchanging "
            "data with an industrial (process) control system or other external system. "
            "You can use Manufacturing Execution Connect (classic) as a part of a "
            "flexible transition to SAP S/4HANA."
        ),
    },
    # ── 2. Intégration: Ariba Procurement Planning ──
    {
        "id": "P02_ariba_procurement",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Procurement Integration",
        "section_concepts": "procurement, sourcing, SAP Ariba, planning, manufacturing",
        "text": (
            "SAP S/4HANA supports the integration with an external procurement planning "
            "system (currently SAP Ariba Procurement Planning) to plan the sourcing of "
            "items from an early stage. This allows you to ensure timely procurement "
            "before the manufacturing process starts, to optimize the project planning, "
            "and to reduce costs."
        ),
    },
    # ── 3. Analytics: Framework + Embedded Stories ──
    {
        "id": "P03_analytics_framework",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Embedded Analytics",
        "section_concepts": "analytics, reporting, virtual data models, embedded stories, real-time",
        "text": (
            "The Analytics framework allows the customers to consolidate business data "
            "from different virtual data models, work with real-time data, and build reports. "
            "With these reports, customers can easily visualize and interpret the data which "
            "in turn will help the decision-makers for better analysis. Analytics framework "
            "is enhanced with embedded stories which allows you to analyze data that help "
            "in accurate decision making wherein Customers can also view and analyze stories "
            "that are embedded within analytics framework"
        ),
    },
    # ── 4. Logistics: Embedded EWM ──
    {
        "id": "P04_embedded_ewm",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Warehouse Management",
        "section_concepts": "EWM, warehouse, inbound, outbound, catch weight, inventory",
        "text": (
            "Leverage embedded EWM to perform standardized inbound & outbound processing "
            "with internal movements and physical inventory & reporting in one system "
            "(master data, customizing & UX). Track alternative quantities with int. "
            "Catch Weight Management"
        ),
    },
    # ── 5. Technology: ML in S/4HANA ──
    {
        "id": "P05_ml_embedded",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Predictive Analytics and Machine Learning",
        "section_concepts": "ML, forecasting, regression, clustering, predictive, embedded analytics",
        "text": (
            "Moderate ML requirements like Forecasting, Trending, Influencers using "
            "Algorithms like Regression, Clustering, Classification, Time-Series etc. "
            "can be handled embedded in S/4HANA."
        ),
    },
    # ── 6. Cross-system: Portfolio Management ──
    {
        "id": "P06_portfolio_mgmt",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Project Portfolio Management",
        "section_concepts": "portfolio, project management, resource planning, HR integration, finance",
        "text": (
            "Portfolio Management integrates information from existing project management, "
            "human resources, and financial systems to provide an overview of the project "
            "portfolio and resource availability, and it provides easy drilldown to details."
        ),
    },
    # ── 7. Architecture: BOPF Framework ──
    {
        "id": "P07_bopf",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Development Framework",
        "section_concepts": "BOPF, ABAP, business objects, framework, development, lifecycle",
        "text": (
            "The Business Object Processing Framework is an ABAP object-oriented framework "
            "that provides a set of generic services and functionalities to speed up, "
            "standardize, and modularize your development. BOPF manages the entire life "
            "cycle of your business objects and covers all aspects of your business "
            "application development."
        ),
    },
    # ── 8. Finance: Consolidation ──
    {
        "id": "P08_consolidation",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Financial Consolidation",
        "section_concepts": "consolidation, financial statements, closing, accounting principles",
        "text": (
            "Consolidation enables you to periodically schedule, generate and monitor "
            "your consolidated financial statements. This process offers a high degree "
            "of flexibility with regard to the timing of closings as well as the "
            "configuration of different accounting principles."
        ),
    },
    # ── 9. Manufacturing: JIT Inbound ──
    {
        "id": "P09_jit_inbound",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Just-in-Time Processing",
        "section_concepts": "JIT, inbound, customer calls, fulfillment, monitoring",
        "text": (
            "The JIT inbound process starts with the receipt of JIT calls from your "
            "customer. Depending on your business scenario and material, the fulfillment "
            "of this request can trigger various different activities. You can monitor "
            "the fulfillment progress to ensure successful completion."
        ),
    },
    # ── 10. Intégration: SAP GTS ──
    {
        "id": "P10_gts_integration",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Global Trade Services",
        "section_concepts": "GTS, trade compliance, international supply chain, customs, export control",
        "text": (
            "SAP S/4HANA supports the integration with SAP Global Trade Services to "
            "offer additional processes for your international supply chain."
        ),
    },
    # ── 11. Stratégie: HCM Roadmap ──
    {
        "id": "P11_hcm_future",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Human Capital Management",
        "section_concepts": "HCM, HR, localization, user experience, innovation, roadmap",
        "text": (
            "No plans to further \"simplify\" SAP ERP HCM: future innovations will be "
            "limited to and focused primarily on localization support and user experience "
            "renewal. No changes are planned to this investment strategy."
        ),
    },
    # ── 12. Finance: Commodity Risk Management ──
    {
        "id": "P12_commodity_risk",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Commodity Management",
        "section_concepts": "commodity, risk, hedging, derivatives, futures, options, trading",
        "text": (
            "Identify and qualify Financial risks associated with commodity price "
            "volatility resulting from physical commodity sales, procurement and "
            "trading processes and mitigate by hedging them with commodity derivatives. "
            "This includes management of full e2e life cycle of Commodity Futures, "
            "Listed and OTC Commodity Options, Commodity Swaps and Forwards"
        ),
    },
    # ── 13. AI: Joule + Sales Order ──
    {
        "id": "P13_joule_sales",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Joule AI Assistant",
        "section_concepts": "Joule, AI, sales order, fulfillment, troubleshooting, compliance",
        "text": (
            "Joule helps resolve and explain sales order fulfillment issues, including "
            "incomplete data, delivery, credit, billing, shipping, and trade compliance "
            "blocks."
        ),
    },
    # ── 14. Compliance: Environment Management ──
    {
        "id": "P14_env_management",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Environment, Health and Safety",
        "section_concepts": "EHS, environment, compliance, emissions, reporting, monitoring",
        "text": (
            "You use the environment management solution to record, collect, process, "
            "monitor, and organize environmental data to stay compliant with the applicable "
            "environmental requirements for your company. You can use manual or automatic "
            "methods to collect and calculate emission inventory data, record that data, "
            "and prepare it for export and reporting. You can manage and report deviations "
            "if they occur."
        ),
    },
    # ── 15. Manufacturing: Process Orders ──
    {
        "id": "P15_process_orders",
        "doc_title": "SAP S/4HANA 2023 Feature Scope Description",
        "doc_type": "technical",
        "doc_subject": "SAP S/4HANA",
        "section_title": "Production Planning and Detailed Scheduling",
        "section_concepts": "PP/DS, planned orders, process orders, MRP, production, reservations",
        "text": (
            "In this case, you convert planned orders into process orders. Again, you can "
            "convert your planned orders manually or automatically using an order conversion "
            "run. The material to be produced, the order quantity, and the order dates are "
            "copied from the planned order to the process order and the dependent requirements "
            "for the components are converted into reservations. With the conversion to process "
            "orders, the responsibility is passed on from the MRP controller to the production "
            "supervisor."
        ),
    },
]

# Domain context simulé (basé sur ce qui devrait être configuré)
DOMAIN_CONTEXT_BLOCK = """## Contexte métier

Domaine : Solutions ERP, cloud et plateformes technologiques SAP
Acronymes courants :
- FI-CA : Contract Accounting (sous-module Finance)
- BTP : Business Technology Platform
- IAS : Identity Authentication Service
- EWM : Extended Warehouse Management
- C/4HANA : Suite CRM cloud SAP (remplace CRM on-premise)
- IFRS 15 : Norme comptable internationale (revenue recognition)
- SSO : Single Sign-On
Concepts clés : SAP S/4HANA, SAP Cloud Platform, Material Ledger, Fiori, ABAP, HANA
"""


def segment_into_units(text: str) -> List[dict]:
    """Segmente un texte en unités (simplifié pour le test)."""
    # Split sur les phrases
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    units = []
    for i, sent in enumerate(sentences):
        sent = sent.strip()
        if len(sent) > 15:
            units.append({"id": f"U{i+1}", "text": sent})
    return units


def format_units(units: List[dict]) -> str:
    """Formate les unités pour le prompt."""
    lines = []
    for u in units:
        lines.append(f"{u['id']}: {u['text']}")
    return "\n".join(lines)


def call_openai(prompt: str, system_msg: str = "Tu es un expert en extraction d'assertions.") -> str:
    """Appelle l'API OpenAI."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return response.choices[0].message.content


def parse_claims(response: str) -> List[dict]:
    """Parse la réponse JSON."""
    text = response.strip()
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        print(f"  [ERREUR JSON] {text[:200]}")
        return []


def analyze_claims(claims: List[dict]) -> dict:
    """Analyse les claims extraites."""
    total = len(claims)
    with_sf = [c for c in claims if c.get("structured_form")]
    types = {}
    for c in claims:
        t = c.get("claim_type", "?")
        types[t] = types.get(t, 0) + 1

    # Catégoriser
    cat_a = []  # Relationnel avec S/P/O
    cat_b = []  # Factuel spécifique sans S/P/O
    cat_c = []  # Faible valeur

    for c in claims:
        text = c.get("claim_text", "")
        sf = c.get("structured_form")

        if sf and sf.get("subject") and sf.get("predicate") and sf.get("object"):
            cat_a.append(c)
        elif len(text) > 40 and not text.lower().startswith("you can"):
            cat_b.append(c)
        else:
            cat_c.append(c)

    return {
        "total": total,
        "with_structured_form": len(with_sf),
        "types": types,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "cat_c": cat_c,
        "pct_a": round(len(cat_a) / total * 100, 1) if total > 0 else 0,
    }


def run_test():
    """Exécute le test comparatif V1 vs V2."""
    print("=" * 80)
    print("TEST COMPARATIF PROMPT V1 vs V2 — Extraction de Claims")
    print("=" * 80)

    results = {"v1": [], "v2": []}

    for passage in TEST_PASSAGES:
        print(f"\n{'─' * 70}")
        print(f"PASSAGE : {passage['section_title']}")
        print(f"Doc     : {passage['doc_title']}")
        print(f"Texte   : {passage['text'][:120]}...")
        print(f"{'─' * 70}")

        units = segment_into_units(passage["text"])
        units_text = format_units(units)

        # ── V1 ──
        prompt_v1 = PROMPT_V1.format(
            units_text=units_text,
            doc_title=passage["doc_title"],
            doc_type=passage["doc_type"],
        )

        print("\n  [V1] Appel LLM...")
        t0 = time.time()
        resp_v1 = call_openai(prompt_v1)
        t1 = time.time()
        claims_v1 = parse_claims(resp_v1)
        analysis_v1 = analyze_claims(claims_v1)
        results["v1"].append(analysis_v1)

        print(f"  [V1] {analysis_v1['total']} claims en {t1-t0:.1f}s")
        print(f"  [V1] Cat A (composable) : {len(analysis_v1['cat_a'])} ({analysis_v1['pct_a']}%)")
        for c in claims_v1:
            sf_tag = " ★ S/P/O" if c.get("structured_form") else ""
            print(f"       • [{c.get('claim_type', '?')}] {c.get('claim_text', '?')[:90]}{sf_tag}")

        # ── V2 ──
        prompt_v2 = PROMPT_V2.format(
            units_text=units_text,
            doc_title=passage["doc_title"],
            doc_type=passage["doc_type"],
            doc_subject=passage["doc_subject"],
            section_title=passage["section_title"],
            section_concepts=passage["section_concepts"],
            domain_context=DOMAIN_CONTEXT_BLOCK,
        )

        print(f"\n  [V2] Appel LLM...")
        t0 = time.time()
        resp_v2 = call_openai(prompt_v2)
        t1 = time.time()
        claims_v2 = parse_claims(resp_v2)
        analysis_v2 = analyze_claims(claims_v2)
        results["v2"].append(analysis_v2)

        print(f"  [V2] {analysis_v2['total']} claims en {t1-t0:.1f}s")
        print(f"  [V2] Cat A (composable) : {len(analysis_v2['cat_a'])} ({analysis_v2['pct_a']}%)")
        for c in claims_v2:
            sf = c.get("structured_form")
            if sf:
                sf_tag = f" ★ {sf.get('subject','')} → {sf.get('predicate','')} → {sf.get('object','')}"
            else:
                sf_tag = ""
            print(f"       • [{c.get('claim_type', '?')}] {c.get('claim_text', '?')[:80]}{sf_tag}")

    # ── Synthèse ──
    print(f"\n{'=' * 80}")
    print("SYNTHÈSE")
    print(f"{'=' * 80}")

    for version in ["v1", "v2"]:
        total_claims = sum(r["total"] for r in results[version])
        total_a = sum(len(r["cat_a"]) for r in results[version])
        total_b = sum(len(r["cat_b"]) for r in results[version])
        total_c = sum(len(r["cat_c"]) for r in results[version])
        pct_a = round(total_a / total_claims * 100, 1) if total_claims > 0 else 0

        label = "PROMPT V1 (actuel)" if version == "v1" else "PROMPT V2 (enrichi)"
        print(f"\n  {label}")
        print(f"    Total claims     : {total_claims}")
        print(f"    Cat A (composable): {total_a} ({pct_a}%)")
        print(f"    Cat B (factuel)   : {total_b}")
        print(f"    Cat C (faible)    : {total_c}")

    # Structured forms V2
    total_sf = sum(r["with_structured_form"] for r in results["v2"])
    print(f"\n  Structured Forms (V2 uniquement) : {total_sf}")
    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERREUR : OPENAI_API_KEY non définie")
        sys.exit(1)
    run_test()
