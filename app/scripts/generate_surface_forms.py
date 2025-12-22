#!/usr/bin/env python3
"""
🌊 OSMOSE Phase 2.7 - Palier 3: Surface Forms Generator

Génère des variantes linguistiques pour améliorer le matching full-text.

Approche hybride:
1. Dictionnaire de traductions connues (acronymes réglementaires)
2. Variantes typographiques automatiques (casing, pluriel, tirets)
3. Optionnel: LLM pour variantes complexes

Usage:
    docker exec knowbase-app python /app/scripts/generate_surface_forms.py
    docker exec knowbase-app python /app/scripts/generate_surface_forms.py --use-llm
    docker exec knowbase-app python /app/scripts/generate_surface_forms.py --dry-run
"""

import argparse
import logging
import re
import sys
from typing import Dict, List, Set, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Dictionnaire de traductions FR ↔ EN pour acronymes réglementaires
# =============================================================================

TRANSLATIONS_FR_EN = {
    # GDPR / RGPD
    "GDPR": ["RGPD", "Règlement Général sur la Protection des Données"],
    "General Data Protection Regulation": ["RGPD", "Règlement Général sur la Protection des Données"],
    "RGPD": ["GDPR", "General Data Protection Regulation"],

    # AI / IA
    "AI": ["IA", "Intelligence Artificielle"],
    "Artificial Intelligence": ["IA", "Intelligence Artificielle"],
    "IA": ["AI", "Artificial Intelligence"],

    # DPO / DPD
    "DPO": ["DPD", "Délégué à la Protection des Données"],
    "Data Protection Officer": ["DPD", "Délégué à la Protection des Données"],
    "DPD": ["DPO", "Data Protection Officer"],

    # NIS2
    "NIS2": ["Directive NIS2", "NIS 2"],
    "NIS2 Directive": ["Directive NIS2", "NIS 2"],

    # AI Act
    "AI Act": ["Règlement IA", "Règlement sur l'IA", "Loi sur l'IA"],
    "EU AI Act": ["Règlement IA européen", "AI Act"],
    "Artificial Intelligence Act": ["Règlement IA", "AI Act", "Loi sur l'IA"],

    # Cybersecurity
    "Cybersecurity": ["Cybersécurité", "Cyber-sécurité", "Sécurité informatique"],
    "Cybersécurité": ["Cybersecurity", "Cyber Security"],

    # Risk
    "High-Risk AI System": ["Système IA à haut risque", "Système d'IA à haut risque"],
    "High-Risk": ["Haut risque", "Risque élevé"],

    # Privacy
    "Privacy": ["Vie privée", "Confidentialité"],
    "Data Privacy": ["Confidentialité des données", "Vie privée des données"],
    "Privacy by Design": ["Protection de la vie privée dès la conception"],

    # Compliance
    "Compliance": ["Conformité", "Mise en conformité"],
    "Regulatory Compliance": ["Conformité réglementaire"],

    # Incident
    "Incident Reporting": ["Signalement d'incident", "Déclaration d'incident"],
    "Data Breach": ["Violation de données", "Fuite de données"],
    "Data Breach Notification": ["Notification de violation de données"],

    # Other common terms
    "Ransomware": ["Rançongiciel"],
    "Malware": ["Logiciel malveillant", "Maliciel"],
    "Phishing": ["Hameçonnage"],
    "Encryption": ["Chiffrement", "Cryptage"],
    "Authentication": ["Authentification"],
    "Authorization": ["Autorisation"],
    "Pseudonymization": ["Pseudonymisation"],
    "Anonymization": ["Anonymisation"],
    "Controller": ["Responsable de traitement"],
    "Processor": ["Sous-traitant"],
    "Data Subject": ["Personne concernée"],
    "Consent": ["Consentement"],
    "Legitimate Interest": ["Intérêt légitime"],
    "Purpose Limitation": ["Limitation des finalités"],
    "Data Minimization": ["Minimisation des données"],
    "Storage Limitation": ["Limitation de la conservation"],
    "Accuracy": ["Exactitude"],
    "Integrity": ["Intégrité"],
    "Confidentiality": ["Confidentialité"],
    "Accountability": ["Responsabilité"],
    "Transparency": ["Transparence"],
}


def generate_typographic_variants(name: str) -> Set[str]:
    """
    Génère des variantes typographiques automatiques.

    Règles:
    - Casing (lowercase, uppercase, title case)
    - Tirets (avec/sans, underscore)
    - Pluriel simple (ajouter 's')
    - Espaces (normalisation)
    """
    variants = set()

    # Nettoyage initial
    name_clean = name.strip()
    if not name_clean:
        return variants

    # Casing variants
    variants.add(name_clean.lower())
    variants.add(name_clean.upper())
    variants.add(name_clean.title())

    # Tirets et underscores
    if "-" in name_clean:
        variants.add(name_clean.replace("-", " "))
        variants.add(name_clean.replace("-", "_"))
    if "_" in name_clean:
        variants.add(name_clean.replace("_", " "))
        variants.add(name_clean.replace("_", "-"))
    if " " in name_clean:
        variants.add(name_clean.replace(" ", "-"))
        variants.add(name_clean.replace(" ", "_"))

    # Pluriel simple (si pas déjà pluriel)
    if not name_clean.endswith("s") and not name_clean.endswith("x"):
        variants.add(name_clean + "s")
        variants.add(name_clean.lower() + "s")

    # Retirer le nom original
    variants.discard(name_clean)

    return variants


def get_translations(name: str) -> Set[str]:
    """Récupère les traductions depuis le dictionnaire."""
    translations = set()

    # Recherche exacte
    if name in TRANSLATIONS_FR_EN:
        translations.update(TRANSLATIONS_FR_EN[name])

    # Recherche case-insensitive
    name_lower = name.lower()
    for key, values in TRANSLATIONS_FR_EN.items():
        if key.lower() == name_lower:
            translations.update(values)

    # Recherche pour acronymes dans le nom (ex: "NIS2 Directive" contient "NIS2")
    # Seulement pour les clés courtes (acronymes)
    words = set(name.split())
    for key, values in TRANSLATIONS_FR_EN.items():
        # Seulement si la clé est un acronyme court (<=5 chars, uppercase)
        if len(key) <= 5 and key.isupper() and key in words:
            translations.update(values)

    return translations


def generate_surface_forms(
    canonical_name: str,
    concept_type: str = None,
    use_llm: bool = False
) -> List[str]:
    """
    Génère toutes les surface forms pour un concept.

    Args:
        canonical_name: Nom canonique du concept
        concept_type: Type de concept (pour contexte LLM)
        use_llm: Utiliser LLM pour variantes avancées

    Returns:
        Liste des surface forms générées
    """
    all_forms = set()

    # 1. Traductions du dictionnaire
    translations = get_translations(canonical_name)
    all_forms.update(translations)

    # 2. Variantes typographiques du nom original
    typo_variants = generate_typographic_variants(canonical_name)
    all_forms.update(typo_variants)

    # 3. Variantes typographiques des traductions
    for trans in translations:
        typo_variants = generate_typographic_variants(trans)
        all_forms.update(typo_variants)

    # 4. LLM pour variantes avancées (optionnel)
    if use_llm:
        llm_variants = generate_llm_variants(canonical_name, concept_type)
        all_forms.update(llm_variants)

    # Nettoyer et limiter
    all_forms.discard(canonical_name)  # Retirer le nom original
    all_forms = {f for f in all_forms if len(f) >= 2 and len(f) <= 200}

    return sorted(list(all_forms))[:20]  # Max 20 variantes


def generate_llm_variants(
    canonical_name: str,
    concept_type: str = None
) -> Set[str]:
    """
    Génère des variantes via LLM (coûteux, utilisé avec parcimonie).
    """
    # TODO: Implémenter si nécessaire
    # Pour l'instant, retourner ensemble vide
    logger.debug(f"LLM variants skipped for: {canonical_name}")
    return set()


def update_concepts_in_neo4j(
    concepts_updates: Dict[str, List[str]],
    tenant_id: str = "default",
    dry_run: bool = False
):
    """
    Met à jour les concepts dans Neo4j avec leurs surface forms.

    Args:
        concepts_updates: Dict[canonical_name -> list of surface forms]
        tenant_id: Tenant ID
        dry_run: Si True, ne pas modifier la base
    """
    from knowbase.neo4j_custom.client import get_neo4j_client

    neo4j = get_neo4j_client()

    if dry_run:
        logger.info(f"[DRY-RUN] Would update {len(concepts_updates)} concepts")
        return

    # Mise à jour par batch
    batch_size = 100
    items = list(concepts_updates.items())

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]

        # Préparer les paramètres (utiliser canonical_name comme clé)
        updates = [
            {"name": name, "surface_form": " | ".join(forms)}
            for name, forms in batch
        ]

        cypher = """
        UNWIND $updates AS u
        MATCH (c:CanonicalConcept {canonical_name: u.name, tenant_id: $tenant_id})
        SET c.surface_form = u.surface_form
        RETURN count(c) AS updated
        """

        result = neo4j.execute_query(cypher, {"updates": updates, "tenant_id": tenant_id})
        updated = result[0].get("updated", 0) if result else 0
        logger.info(f"[OSMOSE] Updated {i + len(batch)}/{len(items)} concepts ({updated} in batch)")


def main():
    parser = argparse.ArgumentParser(description="Generate surface forms for concepts")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for advanced variants")
    parser.add_argument("--dry-run", action="store_true", help="Don't modify database")
    parser.add_argument("--limit", type=int, default=0, help="Limit concepts to process (0=all)")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🌊 OSMOSE Phase 2.7 - Palier 3: Surface Forms Generator")
    logger.info("=" * 60)

    # 1. Récupérer les concepts
    from knowbase.neo4j_custom.client import get_neo4j_client

    neo4j = get_neo4j_client()

    limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""

    cypher = f"""
    MATCH (c:CanonicalConcept)
    WHERE c.tenant_id = $tenant_id
    RETURN c.concept_id AS id, c.canonical_name AS name, c.concept_type AS type
    {limit_clause}
    """

    results = neo4j.execute_query(cypher, {"tenant_id": args.tenant})
    logger.info(f"[OSMOSE] Found {len(results)} concepts to process")

    # 2. Générer les surface forms
    concepts_updates = {}
    concepts_with_forms = 0

    for record in results:
        name = record.get("name", "")
        ctype = record.get("type", "")

        if not name:
            continue

        forms = generate_surface_forms(name, ctype, use_llm=args.use_llm)

        if forms:
            concepts_updates[name] = forms  # Utiliser name comme clé
            concepts_with_forms += 1

            if concepts_with_forms <= 5:
                logger.info(f"  {name}: {forms[:3]}...")

    logger.info(f"[OSMOSE] Generated surface forms for {concepts_with_forms}/{len(results)} concepts")

    # 3. Mettre à jour Neo4j
    if concepts_updates:
        update_concepts_in_neo4j(concepts_updates, tenant_id=args.tenant, dry_run=args.dry_run)

    # 4. Afficher stats
    total_forms = sum(len(f) for f in concepts_updates.values())
    logger.info("=" * 60)
    logger.info(f"✅ COMPLETE: {concepts_with_forms} concepts enriched, {total_forms} surface forms")
    if args.dry_run:
        logger.info("   (DRY-RUN mode - no changes made)")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
