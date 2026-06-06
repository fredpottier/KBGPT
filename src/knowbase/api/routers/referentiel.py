"""
Referentiel API — Carte du Référentiel (#456).

Sert l'anatomie documentaire du KG pour la page de visualisation :
- GET /api/referentiel/map      → documents + lignées (avec preuves) + paires agrégées
- GET /api/referentiel/tensions → registre des tensions adjugées (audit trail)

Tout est calculé depuis le KG (aucune donnée applicative dénormalisée) :
- statut document : annulé s'il est la CIBLE d'une arête SUPERSEDES_DOC ;
- lignée : arêtes SUPERSEDES_DOC + claims-preuves DECLARES_SUPERSESSION (doc+page) ;
- paires : relations claim-à-claim agrégées par paire de documents ;
- tensions : arêtes CONTRADICTS avec leur verdict d'adjudication (#446) —
  `confirmed` = adjudication='CONFIRMED' uniquement.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/referentiel", tags=["referentiel"])

# Relations claim-à-claim SÉMANTIQUES agrégées par paire (les marqueurs
# techniques C4_SCANNED/C6_SCANNED du pipeline sont exclus).
_SEMANTIC_RELS = (
    "REFINES|COMPLEMENTS|SPECIALIZES|QUALIFIES|CHAINS_TO|EVOLVES_TO|EVOLUTION_OF"
)

_DOC_HASH_RE = re.compile(r"_[a-f0-9]{6,}$", re.IGNORECASE)


def _doc_title(doc_id: str, reg_key: Optional[str]) -> str:
    if reg_key:
        return reg_key
    return _DOC_HASH_RE.sub("", doc_id or "").replace("_", " ")


# ── Parsing des dates citées dans les déclarations de supersession ───────────
# Formats rencontrés dans les preuves : « 4/24/89 », « 6/3/97 », « July 15, 1991 »
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_RE_US_NUMERIC = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")
_RE_MONTH_NAME = re.compile(r"^\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\s*$")


def _parse_stated_date(raw: Optional[str]) -> Optional[str]:
    """Date citée → ISO (best-effort, None si non reconnue)."""
    if not raw:
        return None
    m = _RE_US_NUMERIC.match(raw)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:  # « 89 » → 1989 (les citations réglementaires sont passées)
            yr += 1900 if yr > 30 else 2000
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    m = _RE_MONTH_NAME.match(raw)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        da, yr = int(m.group(2)), int(m.group(3))
        if mo and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    return None


# ── Schemas ───────────────────────────────────────────────────────────────────

class RefDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str
    title: str
    authority: Optional[str] = None
    status: str  # in_force | superseded | external (référencé mais non ingéré)
    n_claims: int = 0
    n_withdrawn: int = 0
    doc_date: Optional[str] = None  # ISO — date documentaire (frise chronologique)
    date_source: Optional[str] = None  # claims (valid_from modal) | cited (citée par le remplaçant)


class RefLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    superseder: str  # doc_id du document remplaçant
    superseded: str  # doc_id du document remplacé
    scope: Optional[str] = None
    detection: Optional[str] = None  # explicit | version_convention…
    evidence: Optional[str] = None
    evidence_claim_id: Optional[str] = None
    evidence_doc_id: Optional[str] = None
    evidence_page: Optional[int] = None


class RefPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_a: str
    doc_b: str
    relations: Dict[str, int] = Field(default_factory=dict)
    n_relations: int = 0
    tensions_examined: int = 0
    tensions_confirmed: int = 0


class RefSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n_documents: int = 0
    n_lineages: int = 0
    n_claims: int = 0
    tensions_examined: int = 0
    tensions_confirmed: int = 0


class RefMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: RefSummary
    documents: List[RefDocument] = Field(default_factory=list)
    lineage: List[RefLineage] = Field(default_factory=list)
    pairs: List[RefPair] = Field(default_factory=list)


class RefTension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_a: str
    doc_b: str
    title_a: str
    title_b: str
    text_a: str
    text_b: str
    page_a: Optional[int] = None
    page_b: Optional[int] = None
    verdict: Optional[str] = None
    reason: Optional[str] = None
    method: Optional[str] = None


class RefTensions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int = 0
    by_verdict: Dict[str, int] = Field(default_factory=dict)
    items: List[RefTension] = Field(default_factory=list)


class RefPairExample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_a: str
    text_b: str
    doc_a: str
    doc_b: str
    page_a: Optional[int] = None
    page_b: Optional[int] = None


class RefPairExamples(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation: str
    total: int = 0
    items: List[RefPairExample] = Field(default_factory=list)


# ── Cyphers ───────────────────────────────────────────────────────────────────

_CY_DOCS = """
MATCH (c:Claim {tenant_id: $tenant_id})
WITH c.doc_id AS doc_id, count(c) AS n_claims,
     sum(CASE WHEN c.lifecycle_status_current = 'withdrawn' THEN 1 ELSE 0 END) AS n_withdrawn
OPTIONAL MATCH (d:Document {tenant_id: $tenant_id, doc_id: doc_id})
RETURN doc_id, d.reg_key AS reg_key, n_claims, n_withdrawn
ORDER BY n_claims DESC
"""

# Documents externes : cibles de lignée jamais ingérées (créées par le détecteur
# #443 avec ingested=false) — affichées en fantôme sur la carte.
_CY_EXTERNAL_DOCS = """
MATCH (d:Document {tenant_id: $tenant_id})
WHERE coalesce(d.ingested, true) = false
RETURN d.doc_id AS doc_id, d.reg_key AS reg_key
"""

_CY_LINEAGE = """
MATCH (a:Document {tenant_id: $tenant_id})-[r:SUPERSEDES_DOC]->(b:Document {tenant_id: $tenant_id})
OPTIONAL MATCH (cl:Claim {tenant_id: $tenant_id, claim_id: r.source_claim_id})
RETURN a.doc_id AS superseder, b.doc_id AS superseded,
       r.scope AS scope, r.detection_source AS detection,
       coalesce(r.evidence, cl.text) AS evidence,
       r.source_claim_id AS evidence_claim_id,
       cl.doc_id AS evidence_doc_id, cl.page_no AS evidence_page,
       r.stated_date AS stated_date
"""

# Date documentaire = valid_from MODAL des claims du doc (héritage documentaire,
# même règle que lineage_resolution._doc_keys_and_dates).
_CY_DOC_DATES = """
MATCH (c:Claim {tenant_id: $tenant_id}) WHERE c.doc_id IS NOT NULL
WITH c.doc_id AS doc_id, toString(c.valid_from) AS vf, count(*) AS n
ORDER BY doc_id, (vf IS NULL), n DESC
WITH doc_id, collect(vf)[0] AS modal
RETURN doc_id, modal
"""

# NOTE : le MATCH non-orienté + filtre doc_a < doc_b donne UNE ligne par arête
# (l'orientation symétrique est éliminée par l'inégalité) — pas de /2.
_CY_PAIRS = f"""
MATCH (a:Claim {{tenant_id: $tenant_id}})-[r:{_SEMANTIC_RELS}]-(b:Claim {{tenant_id: $tenant_id}})
WHERE a.doc_id < b.doc_id
WITH a.doc_id AS doc_a, b.doc_id AS doc_b, type(r) AS rel, count(r) AS n
RETURN doc_a, doc_b, collect({{rel: rel, n: n}}) AS rels
"""

_CY_TENSION_COUNTS = """
MATCH (a:Claim {tenant_id: $tenant_id})-[r:CONTRADICTS]-(b:Claim {tenant_id: $tenant_id})
WHERE a.doc_id < b.doc_id
WITH a.doc_id AS doc_a, b.doc_id AS doc_b,
     count(r) AS examined,
     sum(CASE WHEN r.adjudication = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed
RETURN doc_a, doc_b, examined, confirmed
"""

_CY_TENSIONS = """
MATCH (a:Claim {tenant_id: $tenant_id})-[r:CONTRADICTS]->(b:Claim {tenant_id: $tenant_id})
WHERE ($verdict IS NULL OR r.adjudication = $verdict)
RETURN a.doc_id AS doc_a, b.doc_id AS doc_b,
       a.text AS text_a, b.text AS text_b,
       a.page_no AS page_a, b.page_no AS page_b,
       r.adjudication AS verdict, r.adjudication_reason AS reason,
       r.adjudication_model AS method
ORDER BY CASE r.adjudication WHEN 'CONFIRMED' THEN 0 ELSE 1 END, doc_a, doc_b
LIMIT $limit
"""

_CY_VERDICT_COUNTS = """
MATCH (:Claim {tenant_id: $tenant_id})-[r:CONTRADICTS]->(:Claim {tenant_id: $tenant_id})
RETURN coalesce(r.adjudication, 'NON_ADJUGÉ') AS verdict, count(r) AS n
"""

# Exemples verbatim d'une paire de documents pour UN type de relation —
# rend la décomposition « parlante » (on lit de vrais couples de phrases).
_CY_PAIR_EXAMPLES = f"""
MATCH (a:Claim {{tenant_id: $tenant_id, doc_id: $doc_a}})-[r]-(b:Claim {{tenant_id: $tenant_id, doc_id: $doc_b}})
WHERE type(r) = $rel
WITH a, b ORDER BY size(coalesce(a.text, '')) + size(coalesce(b.text, '')) ASC
RETURN a.text AS text_a, b.text AS text_b,
       a.doc_id AS doc_a, b.doc_id AS doc_b,
       a.page_no AS page_a, b.page_no AS page_b
LIMIT $limit
"""

_ALLOWED_REL_TYPES = set(_SEMANTIC_RELS.split("|")) | {"CONTRADICTS"}


def _get_driver():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client().driver


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/map", response_model=RefMap)
async def get_map(tenant_id: str = Query(default="default")) -> RefMap:
    """Anatomie complète : documents, lignées (avec preuves), paires agrégées."""
    from knowbase.relations.explicit_lineage_detector import regulatory_authority

    driver = _get_driver()
    with driver.session() as s:
        doc_rows = [dict(r) for r in s.run(_CY_DOCS, tenant_id=tenant_id)]
        ext_rows = [dict(r) for r in s.run(_CY_EXTERNAL_DOCS, tenant_id=tenant_id)]
        lin_rows = [dict(r) for r in s.run(_CY_LINEAGE, tenant_id=tenant_id)]
        pair_rows = [dict(r) for r in s.run(_CY_PAIRS, tenant_id=tenant_id)]
        tens_rows = [dict(r) for r in s.run(_CY_TENSION_COUNTS, tenant_id=tenant_id)]
        date_rows = {r["doc_id"]: r["modal"] for r in s.run(_CY_DOC_DATES, tenant_id=tenant_id)}

    superseded_ids = {l["superseded"] for l in lin_rows}
    # dates citées : « AC X, dated 6/3/97, is canceled » date le doc REMPLACÉ
    cited_dates = {}
    for l in lin_rows:
        iso = _parse_stated_date(l.get("stated_date"))
        if iso and l["superseded"]:
            cited_dates[l["superseded"]] = iso

    def _doc_date(doc_id: str):
        modal = date_rows.get(doc_id)
        if modal:
            return modal[:10], "claims"
        if doc_id in cited_dates:
            return cited_dates[doc_id], "cited"
        return None, None
    documents = []
    seen_ids = set()
    total_claims = 0
    for d in doc_rows:
        if not d["doc_id"]:
            continue
        seen_ids.add(d["doc_id"])
        total_claims += d["n_claims"] or 0
        dt, src = _doc_date(d["doc_id"])
        documents.append(RefDocument(
            doc_id=d["doc_id"],
            title=_doc_title(d["doc_id"], d.get("reg_key")),
            authority=regulatory_authority(d.get("reg_key") or d["doc_id"]),
            status="superseded" if d["doc_id"] in superseded_ids else "in_force",
            n_claims=d["n_claims"] or 0,
            n_withdrawn=d["n_withdrawn"] or 0,
            doc_date=dt, date_source=src,
        ))
    # Documents fantômes : référencés par la lignée mais jamais ingérés
    for d in ext_rows:
        if not d["doc_id"] or d["doc_id"] in seen_ids:
            continue
        seen_ids.add(d["doc_id"])
        dt, src = _doc_date(d["doc_id"])
        documents.append(RefDocument(
            doc_id=d["doc_id"],
            title=_doc_title(d["doc_id"], d.get("reg_key")),
            authority=regulatory_authority(d.get("reg_key") or d["doc_id"]),
            status="external" if d["doc_id"] not in superseded_ids else "superseded",
            n_claims=0, n_withdrawn=0,
            doc_date=dt, date_source=src,
        ))

    lineage = [RefLineage(
        superseder=l["superseder"], superseded=l["superseded"],
        scope=l.get("scope"), detection=l.get("detection"),
        evidence=l.get("evidence"), evidence_claim_id=l.get("evidence_claim_id"),
        evidence_doc_id=l.get("evidence_doc_id"),
        evidence_page=int(l["evidence_page"]) if l.get("evidence_page") is not None else None,
    ) for l in lin_rows]

    tens_by_pair = {(t["doc_a"], t["doc_b"]): t for t in tens_rows}
    pairs = []
    for p in pair_rows:
        rels = {x["rel"]: int(x["n"]) for x in (p.get("rels") or [])}
        t = tens_by_pair.pop((p["doc_a"], p["doc_b"]), {})
        pairs.append(RefPair(
            doc_a=p["doc_a"], doc_b=p["doc_b"],
            relations=rels, n_relations=sum(rels.values()),
            tensions_examined=int(t.get("examined") or 0),
            tensions_confirmed=int(t.get("confirmed") or 0),
        ))
    # paires qui n'ont QUE des tensions (pas d'autre relation)
    for (da, db), t in tens_by_pair.items():
        pairs.append(RefPair(
            doc_a=da, doc_b=db, relations={}, n_relations=0,
            tensions_examined=int(t.get("examined") or 0),
            tensions_confirmed=int(t.get("confirmed") or 0),
        ))

    summary = RefSummary(
        n_documents=len(documents),
        n_lineages=len(lineage),
        n_claims=total_claims,
        tensions_examined=sum(p.tensions_examined for p in pairs),
        tensions_confirmed=sum(p.tensions_confirmed for p in pairs),
    )
    return RefMap(summary=summary, documents=documents, lineage=lineage, pairs=pairs)


@router.get("/pair-examples", response_model=RefPairExamples)
async def get_pair_examples(
    doc_a: str = Query(...),
    doc_b: str = Query(...),
    relation: str = Query(..., description="Type de relation (REFINES, QUALIFIES…)"),
    tenant_id: str = Query(default="default"),
    limit: int = Query(default=3, le=10),
) -> RefPairExamples:
    """Exemples verbatim (couples de claims) d'une paire de docs pour un type donné."""
    rel = relation.upper().strip()
    if rel not in _ALLOWED_REL_TYPES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Type de relation inconnu : {relation}")
    driver = _get_driver()
    with driver.session() as s:
        rows = [dict(r) for r in s.run(
            _CY_PAIR_EXAMPLES, tenant_id=tenant_id, doc_a=doc_a, doc_b=doc_b,
            rel=rel, limit=limit,
        )]
    items = [RefPairExample(
        text_a=(r.get("text_a") or "")[:350], text_b=(r.get("text_b") or "")[:350],
        doc_a=r["doc_a"], doc_b=r["doc_b"],
        page_a=int(r["page_a"]) if r.get("page_a") is not None else None,
        page_b=int(r["page_b"]) if r.get("page_b") is not None else None,
    ) for r in rows]
    return RefPairExamples(relation=rel, total=len(items), items=items)


@router.get("/tensions", response_model=RefTensions)
async def get_tensions(
    tenant_id: str = Query(default="default"),
    verdict: Optional[str] = Query(default=None, description="Filtre verdict (CONFIRMED…)"),
    limit: int = Query(default=100, le=500),
) -> RefTensions:
    """Registre des tensions : paires CONTRADICTS avec verdicts d'adjudication."""
    driver = _get_driver()
    with driver.session() as s:
        counts = {r["verdict"]: r["n"] for r in s.run(_CY_VERDICT_COUNTS, tenant_id=tenant_id)}
        rows = [dict(r) for r in s.run(
            _CY_TENSIONS, tenant_id=tenant_id,
            verdict=verdict.upper() if verdict else None, limit=limit,
        )]
    items = [RefTension(
        doc_a=r["doc_a"], doc_b=r["doc_b"],
        title_a=_doc_title(r["doc_a"], None), title_b=_doc_title(r["doc_b"], None),
        text_a=(r.get("text_a") or "")[:400], text_b=(r.get("text_b") or "")[:400],
        page_a=int(r["page_a"]) if r.get("page_a") is not None else None,
        page_b=int(r["page_b"]) if r.get("page_b") is not None else None,
        verdict=r.get("verdict"), reason=r.get("reason"), method=r.get("method"),
    ) for r in rows]
    return RefTensions(total=sum(counts.values()), by_verdict=counts, items=items)
