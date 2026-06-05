"""
ExplicitLineageDetector — récolte la lignée de DOCUMENT énoncée explicitement
dans les claims (« This AC cancels AC 21-25A », « Advisory Circular 25.562-1 is
cancelled »…) et la matérialise au niveau document.

Motivation
----------
La supersession bitemporelle existante (`SupersessionApplier`) n'infère `:SUPERSEDES`
que depuis une CONTRADICTION sémantique + un ordre temporel — ce qui échoue dès que
`valid_from` est absent. Résultat sur le corpus aéro : 1 seule relation SUPERSEDES
pour ~42 claims qui annoncent pourtant noir sur blanc leur lignée.

Ce détecteur exploite le signal le plus fort et le plus défendable d'un corpus
réglementaire : la phrase de supersession elle-même. 100 % déterministe (regex +
résolution d'identifiants), zéro appel LLM, domain-agnostic (familles de documents
réglementaires génériques : AC / Advisory Circular, ETSO/TSO, CFR, NPA).

Schéma produit (granularité « document + claim »)
-------------------------------------------------
- `(:Document {doc_id})-[:SUPERSEDES_DOC {explicit:true, …}]->(:Document {doc_id})`
  La chaîne de lignée au niveau document (vision conformité « quelle version en vigueur »).
  Le prédécesseur non ingéré est créé en `:Document {ingested:false, reg_key}`.
- `(:Claim)-[:DECLARES_SUPERSESSION]->(:Document)`
  Le claim porteur de la preuve (verbatim) relié au document superséd é.

Idempotent (MERGE). Domain-agnostic : aucun vocabulaire corpus-spécifique.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Normalisation des identifiants de documents réglementaires
# ============================================================================

# Suffixe de hash ajouté aux doc_id à l'ingestion (ex. "_515205d7")
_HASH_SUFFIX = re.compile(r"_[0-9a-f]{6,}$", re.IGNORECASE)

# Familles reconnues comme DOCUMENTS réglementaires (cibles de lignée valides).
# Volontairement restreint : on EXCLUT les normes (AS/ARP/SAE…) car dans les
# corpus elles apparaissent en « references to 'X' must be replaced by » (interne
# à une exigence), pas en supersession de document.
_RE_ETSO = re.compile(r"\b(E?TSO)[- ]?C?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)
_RE_AC = re.compile(
    r"\b(?:AC|ADVISORY\s+CIRCULAR)\s+([0-9]{1,3}(?:[.\-][0-9]{1,4}){1,2}[A-Za-z]?)",
    re.IGNORECASE,
)
_RE_CFR = re.compile(r"\b(?:14\s*)?CFR\s*(?:PART\s*)?([0-9]{1,3}(?:\.[0-9]+)?)", re.IGNORECASE)
_RE_NPA = re.compile(r"\bNPA[- ]?([0-9]{2,4}[-/][0-9]{1,4})", re.IGNORECASE)


def normalize_reg_key(raw: Optional[str]) -> Optional[str]:
    """Extrait une clé canonique de document réglementaire depuis un doc_id ou
    une mention en texte libre. Retourne None si rien de reconnaissable.

    Exemples :
        "AC_21-25A_515205d7"            -> "AC 21-25A"
        "AC_25.562-1B_e14eda4f"         -> "AC 25.562-1B"
        "AC_20-146_cancelled_5fb3ed5e"  -> "AC 20-146"
        "ETSO-C127c_amd17_d2c85ef0"     -> "ETSO-C127C"
        "Advisory Circular 25.562-1"    -> "AC 25.562-1"
        "ADVISORY CIRCULAR 25-17"       -> "AC 25-17"
        "the 1998 policy"               -> None
        "patent_US9399518_…"            -> None
    """
    if not raw:
        return None
    s = _HASH_SUFFIX.sub("", raw.strip())
    s = s.replace("_", " ")

    m = _RE_ETSO.search(s)
    if m:
        return f"{m.group(1).upper()}-C{m.group(2).upper()}"
    m = _RE_AC.search(s)
    if m:
        return f"AC {m.group(1).upper()}"
    m = _RE_CFR.search(s)
    if m:
        return f"CFR {m.group(1).upper()}"
    m = _RE_NPA.search(s)
    if m:
        return f"NPA {m.group(1).upper()}"
    return None


def regulatory_authority(doc_id_or_key: Optional[str]) -> Optional[str]:
    """Autorité émettrice d'un document réglementaire — heuristique best-effort.

    Domain-extensible : retourne None hors familles connues (le runtime reste alors
    attribué au niveau document, sans étiquette d'autorité). Couverture actuelle
    (aérospatial) : FAA (AC / 14 CFR / TSO) vs EASA (ETSO / CS / NPA). Ajouter
    d'autres juridictions ici au besoin (médical : FDA/EMA ; etc.).
    """
    if not doc_id_or_key:
        return None
    d = doc_id_or_key.upper()
    if d.startswith("ETSO") or "CS-" in d or d.startswith("NPA") or "EASA" in d:
        return "EASA"
    if d.startswith("AC_") or d.startswith("AC ") or "CFR" in d or d.startswith("TSO"):
        return "FAA"
    return None


def find_reg_ids(text: str) -> list[tuple[str, int]]:
    """Retourne la liste (clé normalisée, position de début) de tous les
    identifiants de documents réglementaires trouvés dans `text`, dans l'ordre.
    """
    found: list[tuple[str, int]] = []
    for rx in (_RE_ETSO, _RE_AC, _RE_CFR, _RE_NPA):
        for m in rx.finditer(text):
            key = normalize_reg_key(m.group(0))
            if key:
                found.append((key, m.start()))
    found.sort(key=lambda t: t[1])
    return found


# ============================================================================
# Parsing de la phrase de supersession
# ============================================================================

# Verbes de supersession de DOCUMENT (on EXCLUT « replace » : trop générique —
# « references to X must be replaced by », « may be replaced by ballast »…).
_VERB = re.compile(
    r"\b(cancel(?:s|led|ed)?|supersed(?:es|ed|e)|rescind(?:s|ed)?|withdraw(?:n|s)?)\b",
    re.IGNORECASE,
)

# Marqueurs de mention INCIDENTE (le claim parle d'une supersession sans en être
# l'acteur) → à rejeter.
_INCIDENTAL = re.compile(
    r"(reference to|no longer relevant|deleted a reference|typographical|redesignated|"
    r"paragraph|table\s|appendix)",
    re.IGNORECASE,
)

# « … canceled by <AGENT> » : l'agent (pas le doc source) est le superséd eur.
_BY_AGENT = re.compile(
    r"(?:cancel\w*|supersed\w*|rescind\w*|withdraw\w*)\s+by\s+(.{0,40})",
    re.IGNORECASE,
)

# Date énoncée (« dated 6/3/97 », « dated May 19, 2003 »)
_DATED = re.compile(r"dated\s+([A-Za-z0-9,/ .-]{6,30})", re.IGNORECASE)


def is_doc_supersession_statement(text: str) -> bool:
    """Vrai si `text` ressemble à une déclaration de supersession DE DOCUMENT
    (verbe non nié + au moins un identifiant de document réglementaire).

    Utilisé par la selection gate du pipeline staged : ces phrases sont une
    classe LIFECYCLE-CRITIQUE qui ne doit JAMAIS être jetée comme « doc_meta »
    (cf ADR_RESOLUTION_CONTRADICTIONS §7.I — bug du 04/06 : « This AC cancels
    AC 21-25A » était droppée → lignée perdue).
    """
    if not text:
        return False
    verb_matches = list(_VERB.finditer(text))
    if not verb_matches:
        return False
    def _neg(m: re.Match) -> bool:
        window = text[max(0, m.start() - 24):m.start()]
        return bool(re.search(r"\b(not|never|no longer|nor)\s+(?:\w+\s+){0,2}$", window, re.IGNORECASE))
    if all(_neg(m) for m in verb_matches):
        return False
    return bool(find_reg_ids(text))


# ============================================================================
# Déclarations LIFECYCLE réglementaires (audit #450 du 05/06/2026)
# ============================================================================

# Verbes de CHANGEMENT STRUCTUREL d'un texte réglementaire. Ces phrases
# (« Deletes paragraph 5e(5)(d)… », « Redesignates paragraph 5e(5)(e)… »,
# « This amendment moved the test criteria to a new Appendix J »,
# « Section 25.791 did not exist prior to Amendment 25-32 ») sont la matière
# première des questions lifecycle/évolution — le juge de la selection gate
# les classe typiquement en doc_meta → DROP, ce qui a détruit ~10 ancres du
# gold-set lors de la ré-ingestion staged (cf GOLD_SET_AERO_README révision
# 2026-06-05 bis).
_LIFECYCLE_VERB = re.compile(
    r"\b(delet(?:es|ed|e)|redesignat(?:es|ed|e)|add(?:s|ed)?|revis(?:es|ed|e)|"
    r"amend(?:s|ed)?|mov(?:es|ed|e)|remov(?:es|ed|e)|introduc(?:es|ed|e)|"
    r"renumber(?:s|ed)?|relocat(?:es|ed|e)|did not exist|no longer (?:exists?|appears?))\b",
    re.IGNORECASE,
)

# Cible structurelle du changement (sans elle, « adds »/« moved » sont trop génériques).
_STRUCTURAL_TARGET = re.compile(
    r"(\bparagraph\b|\bsubparagraph\b|\bsection\b|\bsubsection\b|\bappendix\b|"
    r"\bamendment\b|§|\bchapter\b|\btable\s+[0-9A-Z]|\bfigure\s+[0-9A-Z])",
    re.IGNORECASE,
)

# Provenance documentaire : « <authority> has published/issued <guidance/memo/policy>
# <identifiant> » (ex : le memo PSAIR100-9/8/2003 perdu par le gate).
_PROVENANCE = re.compile(
    r"\b(publish(?:es|ed)?|issu(?:es|ed|e))\b.{0,80}?"
    r"\b(guidance|memorandum|memo|policy|circular|bulletin|directive|notice)\b",
    re.IGNORECASE | re.DOTALL,
)


def is_regulatory_lifecycle_statement(text: str) -> bool:
    """Vrai si `text` décrit un CHANGEMENT STRUCTUREL d'un texte réglementaire
    (suppression/redésignation/ajout/déplacement de paragraphe, section,
    appendix…) ou une PROVENANCE documentaire datée/identifiée.

    Même contrat que `is_doc_supersession_statement` : utilisé par la selection
    gate comme classe LIFECYCLE-CRITIQUE qui override le DROP du juge, y compris
    en catégorie « déchet franc » (doc_meta). Garde volontairement étroite :
    verbe structurel + cible structurelle (ou provenance + identifiant précis).
    """
    if not text:
        return False
    if _LIFECYCLE_VERB.search(text) and _STRUCTURAL_TARGET.search(text):
        return True
    if _PROVENANCE.search(text):
        # provenance : exiger un identifiant précis (n° de memo, date, code)
        from knowbase.claimfirst.quality.identifier_guard import has_specific_identifier
        return has_specific_identifier(text)
    return False


@dataclass
class LineageParse:
    """Résultat du parsing d'un claim de supersession de document."""

    superseder_key: str
    superseded_key: str
    superseder_is_source: bool
    stated_date: Optional[str]
    confidence: float
    pattern: str  # "active" | "passive" | "by_agent"


@dataclass
class LineageReject:
    """Claim écarté, avec la raison (pour audit du dry-run)."""

    reason: str


def parse_lineage(text: str, source_key: Optional[str]) -> LineageParse | LineageReject:
    """Décide si `text` (verbatim d'un claim issu du document `source_key`)
    énonce une supersession de DOCUMENT, et de qui vers qui.

    Retourne un LineageParse (accepté) ou un LineageReject (raison du rejet).
    """
    if not text:
        return LineageReject("texte vide")

    verb_matches = list(_VERB.finditer(text))
    if not verb_matches:
        return LineageReject("aucun verbe de supersession")

    # Garde de NÉGATION (ADR §7.I.2) : « does not supersede », « shall not cancel »…
    # Si TOUTES les occurrences du verbe sont niées dans leur fenêtre gauche → rejet.
    def _negated(m: re.Match) -> bool:
        window = text[max(0, m.start() - 24):m.start()]
        return bool(re.search(r"\b(not|never|no longer|nor)\s+(?:\w+\s+){0,2}$", window, re.IGNORECASE))

    if all(_negated(m) for m in verb_matches):
        return LineageReject("verbe de supersession nié (does not supersede…)")

    if _INCIDENTAL.search(text):
        return LineageReject("mention incidente (reference/paragraph/table…)")

    reg_ids = find_reg_ids(text)
    if not reg_ids:
        return LineageReject("aucun identifiant de document cible")

    # Cibles candidates = identifiants ≠ document source
    others = [k for (k, _) in reg_ids if k != source_key]
    if not others:
        return LineageReject("seul le document source est cité (auto-référence)")

    superseded_key = others[0]
    stated_date = None
    md = _DATED.search(text)
    if md:
        # Coupe une éventuelle queue « , is canceled » que la regex aurait happée
        # (« dated 4/24/89, is canceled » -> « 4/24/89 » ; « May 19, 2003 » conservé).
        raw_date = re.split(r",?\s+(?:is|are|was|were)\s+", md.group(1), maxsplit=1)[0]
        stated_date = raw_date.strip().rstrip(".,")

    # Cas « <subject> … canceled by <AGENT> » : l'agent est le superséd eur, et le
    # superséd é est le SUJET (qui doit être un document reconnu, PAS l'agent).
    by = _BY_AGENT.search(text)
    if by:
        agent_key = normalize_reg_key(by.group(1))
        if agent_key:
            # Le document superséd é est un identifiant cité QUI N'EST PAS l'agent.
            cand = [k for k in others if k != agent_key]
            if not cand:
                # Seul l'agent est un document reconnu → le sujet superséd é n'en est
                # pas un (ex. « The FSSR was canceled by AC 00-20 ») → on écarte.
                return LineageReject("supersession par agent sans document superséd é reconnu")
            superseded_key = cand[0]
            if agent_key == source_key:
                return LineageParse(source_key, superseded_key, True, stated_date, 0.9, "passive")
            return LineageParse(agent_key, superseded_key, False, stated_date, 0.85, "by_agent")

    # Cas actif/passif standard : le document source est le superséd eur.
    if not source_key:
        return LineageReject("document source non résolu en clé réglementaire")
    if source_key == superseded_key:
        return LineageReject("supersession de soi-même")

    # Actif (« This AC cancels … », « we have cancelled … ») vs passif (« X is canceled »).
    active = re.search(r"\b(this\s+(?:ac|advisory\s+circular|document)|we\s)\b", text, re.IGNORECASE)
    pattern = "active" if active else "passive"
    confidence = 0.95 if active else 0.9
    return LineageParse(source_key, superseded_key, True, stated_date, confidence, pattern)


# ============================================================================
# Détecteur (lecture KG + matérialisation)
# ============================================================================

# Pré-filtre KG : ne charger que les claims susceptibles de porter une supersession.
_CANDIDATE_CYPHER = """
MATCH (c:Claim {tenant_id: $tid})
WHERE toLower(coalesce(c.text, "")) =~ '.*(cancel|supersed|rescind|withdrawn).*'
RETURN c.claim_id AS claim_id, c.doc_id AS doc_id,
       coalesce(c.text, "") AS text, toString(c.valid_from) AS valid_from
"""


@dataclass
class LineageEdge:
    """Une relation de lignée proposée/écrite."""

    superseder_doc_id: str  # doc_id ingéré, ou clé réglementaire si externe
    superseded_doc_id: str
    superseder_key: str
    superseded_key: str
    superseder_ingested: bool
    superseded_ingested: bool
    source_claim_id: str
    evidence: str
    stated_date: Optional[str]
    confidence: float
    pattern: str


class ExplicitLineageDetector:
    """Récolte la lignée explicite de document et la matérialise (idempotent).

    Usage :
        det = ExplicitLineageDetector(driver, tenant_id="default")
        edges, rejects = det.scan()         # dry-run : ne fait que proposer
        det.apply(edges)                    # écrit dans Neo4j
    """

    def __init__(self, driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ scan
    def _doc_key_map(self) -> dict[str, str]:
        """Map {clé réglementaire normalisée -> doc_id ingéré} pour le tenant."""
        out: dict[str, str] = {}
        with self.driver.session() as s:
            for r in s.run(
                "MATCH (c:Claim {tenant_id: $tid}) WHERE c.doc_id IS NOT NULL "
                "RETURN DISTINCT c.doc_id AS d",
                tid=self.tenant_id,
            ):
                key = normalize_reg_key(r["d"])
                if key and key not in out:
                    out[key] = r["d"]
        return out

    def scan(self) -> tuple[list[LineageEdge], list[tuple[str, str]]]:
        """Parcourt les claims candidats et retourne (edges proposées, rejets).

        Rejets = liste (claim_id, raison) — pour audit du dry-run.
        Aucune écriture.
        """
        key2doc = self._doc_key_map()
        edges: list[LineageEdge] = []
        rejects: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        with self.driver.session() as s:
            rows = list(s.run(_CANDIDATE_CYPHER, tid=self.tenant_id))

        for row in rows:
            doc_id = row["doc_id"]
            source_key = normalize_reg_key(doc_id)
            res = parse_lineage(row["text"], source_key)
            if isinstance(res, LineageReject):
                rejects.append((row["claim_id"], res.reason))
                continue

            # Résolution superséd eur / superséd é vers des doc_id
            superseder_doc = key2doc.get(res.superseder_key)
            superseder_ingested = superseder_doc is not None
            if superseder_doc is None:
                # Le superséd eur (agent externe) n'est pas ingéré : on le matérialise
                # quand même comme Document externe, keyé par sa clé réglementaire.
                superseder_doc = res.superseder_key

            superseded_doc = key2doc.get(res.superseded_key)
            superseded_ingested = superseded_doc is not None
            if superseded_doc is None:
                superseded_doc = res.superseded_key  # Document externe (non ingéré)

            dedup = (superseder_doc, superseded_doc)
            if dedup in seen:
                continue
            seen.add(dedup)

            edges.append(
                LineageEdge(
                    superseder_doc_id=superseder_doc,
                    superseded_doc_id=superseded_doc,
                    superseder_key=res.superseder_key,
                    superseded_key=res.superseded_key,
                    superseder_ingested=superseder_ingested,
                    superseded_ingested=superseded_ingested,
                    source_claim_id=row["claim_id"],
                    evidence=row["text"][:400],
                    stated_date=res.stated_date,
                    confidence=res.confidence,
                    pattern=res.pattern,
                )
            )

        return edges, rejects

    # ----------------------------------------------------------------- apply
    _WRITE_CYPHER = """
    // Document superséd eur (ingéré ou externe)
    MERGE (sup:Document {doc_id: $superseder_doc, tenant_id: $tid})
      ON CREATE SET sup.created_at = datetime()
    SET sup.ingested = coalesce(sup.ingested, $superseder_ingested),
        sup.reg_key  = coalesce(sup.reg_key, $superseder_key)
    // Document superséd é (ingéré ou externe)
    MERGE (old:Document {doc_id: $superseded_doc, tenant_id: $tid})
      ON CREATE SET old.created_at = datetime(),
                    old.ingested = $superseded_ingested,
                    old.reg_key = $superseded_key
    SET old.ingested = coalesce(old.ingested, $superseded_ingested),
        old.reg_key  = coalesce(old.reg_key, $superseded_key)
    // Lignée niveau document (idempotent)
    MERGE (sup)-[r:SUPERSEDES_DOC]->(old)
      ON CREATE SET r.explicit = true,
                    r.detected_at = datetime(),
                    r.scope = 'full',
                    r.detection_source = 'explicit_lineage_detector',
                    r.confidence = $confidence,
                    r.pattern = $pattern,
                    r.stated_date = $stated_date,
                    r.evidence = $evidence,
                    r.source_claim_id = $claim_id
    // Claim porteur de preuve relié au document superséd é (le « double »)
    WITH old
    MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tid})
    MERGE (c)-[d:DECLARES_SUPERSESSION]->(old)
      ON CREATE SET d.detected_at = datetime()
    RETURN 1 AS ok
    """

    def apply(self, edges: list[LineageEdge]) -> dict[str, int]:
        """Écrit les edges proposées dans Neo4j (idempotent)."""
        written = 0
        with self.driver.session() as s:
            for e in edges:
                s.run(
                    self._WRITE_CYPHER,
                    tid=self.tenant_id,
                    superseder_doc=e.superseder_doc_id,
                    superseded_doc=e.superseded_doc_id,
                    superseder_key=e.superseder_key,
                    superseded_key=e.superseded_key,
                    superseder_ingested=e.superseder_ingested,
                    superseded_ingested=e.superseded_ingested,
                    confidence=e.confidence,
                    pattern=e.pattern,
                    stated_date=e.stated_date,
                    evidence=e.evidence,
                    claim_id=e.source_claim_id,
                )
                written += 1
        return {"edges_written": written}
