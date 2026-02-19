# src/knowbase/claimfirst/models/subject_anchor.py
"""
Modèle SubjectAnchor - Sujet canonique avec résolution conservative.

INV-9: Conservative Subject Resolution (Anti-Hallucination Alias)

Principe: La résolution de sujets ne doit JAMAIS auto-fusionner sur
simple embedding ou inférence LLM.

Règles:
1. SubjectAnchor = entité canonique avec aliases typés
   - aliases_explicit: trouvés textuellement dans le corpus (FORT)
   - aliases_inferred: suggérés par LLM (FAIBLE, à confirmer)
   - aliases_learned: appris par cooccurrence stable + validation (MOYEN)

2. Ordre de résolution STRICT:
   - Exact match → OK
   - Normalisation lexicale → re-test exact
   - aliases_learned → OK (confiance 0.95)
   - Soft match embedding → CANDIDAT UNIQUEMENT (jamais décision finale)
   - Rien → création nouveau SubjectAnchor (AVEC FILTRE)

3. Règle d'abstention: Si doute sur équivalence → PAS de merge
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AliasSource(str, Enum):
    """Source d'un alias - détermine sa fiabilité."""

    EXPLICIT = "explicit"
    """Trouvé textuellement dans le corpus (FORT)."""

    INFERRED = "inferred"
    """Suggéré par LLM (FAIBLE, à confirmer)."""

    LEARNED = "learned"
    """Appris par cooccurrence stable + validation (MOYEN)."""


class SubjectAnchor(BaseModel):
    """
    Sujet canonique avec résolution d'alias conservative.

    INV-9: La résolution ne doit JAMAIS auto-fusionner sur
    simple embedding ou inférence LLM.

    Attributes:
        subject_id: Identifiant unique du sujet
        tenant_id: Tenant multi-locataire
        canonical_name: Nom de référence
        aliases_explicit: Alias trouvés dans le corpus (FORT)
        aliases_inferred: Alias suggérés par LLM (FAIBLE)
        aliases_learned: Alias validés par cooccurrence (MOYEN)
        domain: Domaine métier optionnel
        qualifiers_validated: Qualificateurs validés (≥20% docs)
        qualifiers_candidates: Qualificateurs candidats (en attente)
        embedding: Embedding pour soft matching (INV-9: candidat, pas décision)
        source_doc_ids: Documents d'où le sujet a été extrait
        possible_equivalents: IDs des sujets potentiellement équivalents
    """

    subject_id: str = Field(
        ...,
        description="Identifiant unique du sujet"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    canonical_name: str = Field(
        ...,
        min_length=3,
        description="Nom de référence du sujet"
    )

    # Aliases typés par source (INV-9)
    aliases_explicit: List[str] = Field(
        default_factory=list,
        description="Alias corpus-prouvés (FORT)"
    )

    aliases_inferred: List[str] = Field(
        default_factory=list,
        description="Alias LLM-suggérés (FAIBLE, à confirmer)"
    )

    aliases_learned: List[str] = Field(
        default_factory=list,
        description="Alias validés par cooccurrence (MOYEN)"
    )

    # Domaine métier optionnel
    domain: Optional[str] = Field(
        default=None,
        description="Domaine métier: 'SAP', 'Medical', 'Legal'..."
    )

    # PATCH F: Qualificateurs séparés validated vs candidates (INV-10)
    # Qualificateurs VALIDÉS (≥20% docs du même sujet + ≥2 valeurs)
    qualifiers_validated: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Qualificateurs validés: {version: ['2021', '2023'], region: ['EU', 'US']}"
    )

    # Qualificateurs CANDIDATS (découverts mais pas encore validés)
    qualifiers_candidates: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Qualificateurs candidats en attente de validation"
    )

    # Embedding pour soft matching (INV-9: candidat, pas décision)
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Embedding pour soft matching (candidat uniquement)"
    )

    # Provenance
    source_doc_ids: List[str] = Field(
        default_factory=list,
        description="Documents d'où le sujet a été extrait"
    )

    # Équivalences possibles (non confirmées)
    possible_equivalents: List[str] = Field(
        default_factory=list,
        description="subject_ids potentiellement équivalents (statut AMBIGUOUS)"
    )

    # Métadonnées
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de création"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date de dernière mise à jour"
    )

    def all_aliases(self) -> List[str]:
        """
        Tous les alias, toutes sources confondues.

        Returns:
            Liste de tous les alias (explicit + inferred + learned)
        """
        return self.aliases_explicit + self.aliases_inferred + self.aliases_learned

    def strong_aliases(self) -> List[str]:
        """
        Alias fiables uniquement (explicit + learned).

        CORRECTIF 5: aliases_inferred ne sont JAMAIS utilisés pour
        filtre dur à query-time.

        Returns:
            Liste des alias fiables
        """
        return self.aliases_explicit + self.aliases_learned

    def add_explicit_alias(self, alias: str) -> bool:
        """
        Ajoute un alias explicite (trouvé dans le corpus).

        Args:
            alias: Alias à ajouter

        Returns:
            True si l'alias a été ajouté
        """
        normalized = alias.strip()
        if normalized and normalized not in self.aliases_explicit:
            # Retirer des inferred si présent (promu vers explicit)
            if normalized in self.aliases_inferred:
                self.aliases_inferred.remove(normalized)
            self.aliases_explicit.append(normalized)
            return True
        return False

    def add_inferred_alias(self, alias: str) -> bool:
        """
        Ajoute un alias inféré (suggéré par LLM).

        INV-9: Ces alias ne sont JAMAIS utilisés pour filtre dur.

        Args:
            alias: Alias suggéré

        Returns:
            True si l'alias a été ajouté
        """
        normalized = alias.strip()
        if (normalized
            and normalized not in self.aliases_explicit
            and normalized not in self.aliases_inferred):
            self.aliases_inferred.append(normalized)
            return True
        return False

    def promote_to_learned(self, alias: str) -> bool:
        """
        Promeut un alias inféré vers learned après validation.

        Args:
            alias: Alias à promouvoir

        Returns:
            True si la promotion a réussi
        """
        normalized = alias.strip()
        if normalized in self.aliases_inferred:
            self.aliases_inferred.remove(normalized)
            if normalized not in self.aliases_learned:
                self.aliases_learned.append(normalized)
            return True
        return False

    def add_qualifier_candidate(self, key: str, value: str) -> None:
        """
        Ajoute un qualificateur candidat.

        INV-10: Les qualificateurs sont découverts du corpus, pas hardcodés.
        Un candidat doit être validé avant d'être utilisable.

        Args:
            key: Clé du qualificateur (ex: 'version')
            value: Valeur (ex: '2023')
        """
        if key not in self.qualifiers_candidates:
            self.qualifiers_candidates[key] = []
        if value not in self.qualifiers_candidates[key]:
            self.qualifiers_candidates[key].append(value)

    def promote_qualifier(self, key: str) -> bool:
        """
        Promeut un qualificateur candidat vers validé.

        Conditions (à vérifier avant appel):
        - ≥20% des docs du même sujet utilisent ce qualificateur
        - ≥2 valeurs distinctes

        Args:
            key: Clé du qualificateur à promouvoir

        Returns:
            True si la promotion a réussi
        """
        if key in self.qualifiers_candidates:
            values = self.qualifiers_candidates.pop(key)
            if key not in self.qualifiers_validated:
                self.qualifiers_validated[key] = []
            for v in values:
                if v not in self.qualifiers_validated[key]:
                    self.qualifiers_validated[key].append(v)
            return True
        return False

    def compute_subject_hash(self) -> str:
        """
        Calcule un hash stable pour le sujet.

        Utilisé pour la déduplication inter-sessions.

        Returns:
            Hash hexadécimal sur 16 caractères
        """
        normalized = self.canonical_name.lower().strip()
        content = f"{self.tenant_id}:{normalized}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "canonical_name": self.canonical_name,
            "aliases_explicit": self.aliases_explicit if self.aliases_explicit else None,
            "aliases_inferred": self.aliases_inferred if self.aliases_inferred else None,
            "aliases_learned": self.aliases_learned if self.aliases_learned else None,
            "domain": self.domain,
            "qualifiers_validated": self.qualifiers_validated if self.qualifiers_validated else None,
            "qualifiers_candidates": self.qualifiers_candidates if self.qualifiers_candidates else None,
            "source_doc_ids": self.source_doc_ids if self.source_doc_ids else None,
            "possible_equivalents": self.possible_equivalents if self.possible_equivalents else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "subject_hash": self.compute_subject_hash(),
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "SubjectAnchor":
        """Construit un SubjectAnchor depuis un record Neo4j."""
        return cls(
            subject_id=record["subject_id"],
            tenant_id=record["tenant_id"],
            canonical_name=record["canonical_name"],
            aliases_explicit=record.get("aliases_explicit") or [],
            aliases_inferred=record.get("aliases_inferred") or [],
            aliases_learned=record.get("aliases_learned") or [],
            domain=record.get("domain"),
            qualifiers_validated=record.get("qualifiers_validated") or {},
            qualifiers_candidates=record.get("qualifiers_candidates") or {},
            source_doc_ids=record.get("source_doc_ids") or [],
            possible_equivalents=record.get("possible_equivalents") or [],
            created_at=datetime.fromisoformat(record["created_at"])
            if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"])
            if record.get("updated_at") else datetime.utcnow(),
        )

    @classmethod
    def create_new(
        cls,
        tenant_id: str,
        canonical_name: str,
        doc_id: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> "SubjectAnchor":
        """
        Factory pour créer un nouveau SubjectAnchor.

        Le canonical_name est aussi ajouté comme alias_explicit.

        Args:
            tenant_id: Tenant ID
            canonical_name: Nom canonique
            doc_id: Document source (optionnel)
            domain: Domaine métier (optionnel)

        Returns:
            Nouveau SubjectAnchor
        """
        normalized = canonical_name.strip()
        subject_id = f"subject_{hashlib.md5(f'{tenant_id}:{normalized}'.encode()).hexdigest()[:12]}"

        return cls(
            subject_id=subject_id,
            tenant_id=tenant_id,
            canonical_name=normalized,
            aliases_explicit=[normalized],  # Le nom canonique est toujours explicit
            domain=domain,
            source_doc_ids=[doc_id] if doc_id else [],
        )


def is_valid_subject_name(name: str) -> bool:
    """
    Vérifie si un nom de sujet est valide pour création.

    Gates structurelles language-agnostic (coût zéro, pas de blacklist).
    Le filtrage sémantique est délégué à la validation LLM post-hoc.

    Args:
        name: Nom à vérifier

    Returns:
        True si le nom est valide pour créer un SubjectAnchor
    """
    normalized = name.lower().strip()
    words = normalized.split()

    # 1. Trop court : <2 mots ET <10 chars
    if len(words) < 2 and len(normalized) < 10:
        return False

    # 2. Pas assez de lettres
    alpha_chars = sum(1 for c in normalized if c.isalpha())
    if alpha_chars < 5:
        return False

    # 3. Trop long : >8 mots → probablement une phrase
    if len(words) > 8:
        return False

    # 4. Trop long en chars : >100 chars → description
    if len(normalized) > 100:
        return False

    # 5. Ponctuation de phrase : ; ! ? → pas un sujet
    if any(c in normalized for c in ";!?"):
        return False

    # 6. Marqueurs layout : | (pipes de tableaux/headers)
    if "|" in normalized:
        return False

    # 7. Commence par non-alphanum (bullet tronquée, symbole)
    if normalized and not normalized[0].isalnum():
        return False

    # 8. Ratio virgules élevé → phrase descriptive
    comma_count = normalized.count(",")
    if comma_count >= 3 and comma_count >= len(words) // 2:
        return False

    return True


__all__ = [
    "SubjectAnchor",
    "AliasSource",
    "is_valid_subject_name",
]
