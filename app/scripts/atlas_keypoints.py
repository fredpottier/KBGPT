"""Atlas « intelligent » bâti sur les KeyPoints (et non les Perspectives HDBSCAN).

Problème de l'Atlas actuel : il s'appuie sur les Perspectives, qui groupent par
SIMILARITÉ DE SURFACE (HDBSCAN d'embeddings) → mêmes faiblesses que la détection
(claims contradictoires dispersés, thèmes mal rapprochés).

Ici chaque NarrativeTopic = un KeyPoint (une QUESTION normalisée) → groupement par
le bon axe (« de quoi ça parle »), et les TENSIONS (réponses opposées sous la même
question) sont surfacées explicitement dans la description → l'Atlas devient
débat-aware. Roots = thèmes cliniques (cardiovasculaire, cancer, mortalité…).

Réutilise 100% de la rédaction LLM + roots + persistance d'AtlasGenerator via une
sous-classe qui surcharge `_load_perspectives`.

Usage : docker compose exec app python scripts/atlas_keypoints.py --tenant alcohol_health
"""
from __future__ import annotations

import argparse
import os
from collections import Counter

from neo4j import GraphDatabase

from knowbase.atlas.generator import AtlasGenerator

# Thèmes cliniques (root) par mots-clés dans la question
_THEMES = [
    ("Cardiovascular", ["cardiovascular", "heart", "coronary", "stroke", "atrial", "blood pressure", "hypertension"]),
    ("Cancer", ["cancer", "carcino", "tumor", "tumour", "breast", "oesophag", "esophag", "colorect", "pancrea"]),
    ("Mortality", ["mortality", "death", "all-cause", "life expectancy", "years of life"]),
    ("Brain & Cognition", ["brain", "cognition", "cognitive", "dementia", "grey matter", "white matter", "iron"]),
    ("Metabolic", ["diabetes", "metabolic", "gallstone", "liver", "hepat", "pancreatitis"]),
    ("Minimum-risk level & guidelines", ["minimi", "safe level", "tmrel", "guideline", "recommend", "standard drink", "low-risk"]),
    ("Methodology & bias", ["mendelian", "randomi", "confound", "bias", "abstainer", "study design", "reverse caus", "selection"]),
]


def theme_for(question: str) -> str:
    q = (question or "").lower()
    for name, kws in _THEMES:
        if any(k in q for k in kws):
            return name
    return "General"


class KeyPointAtlasGenerator(AtlasGenerator):
    """Atlas sourcé sur les KeyPoints, tension-aware."""

    def _load_perspectives(self, limit: int) -> list[dict]:
        cypher = """
        MATCH (k:KeyPoint {tenant_id:$tid})<-[:ANSWERS_KEYPOINT]-(c:Claim)
        WITH k, collect({doc: split(c.doc_id,'_')[0], stance: c.kp_stance,
                         answer: c.kp_answer, obj: c.object_canonical})[0..50] AS members
        WHERE k.claim_count >= 3
        RETURN k.kp_id AS kp_id, k.question AS question,
               k.claim_count AS claim_count, k.doc_count AS doc_count,
               coalesce(k.stances, []) AS stances, members
        ORDER BY k.claim_count * (CASE WHEN size(coalesce(k.stances,[]))>=3 THEN 2 ELSE 1 END) DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            rows = session.run(cypher, tid=self.tenant_id, limit=limit).data()

        out = []
        for r in rows:
            members = r["members"]
            objs = Counter(m["obj"] for m in members if m.get("obj"))
            subjects = [o for o, _ in objs.most_common(6)]
            stances = set(s for s in (r.get("stances") or []) if s and s != "none")
            # tension : directions opposées OU réponses divergentes sur ≥2 docs
            answers_by_doc = {}
            for m in members:
                if m.get("answer"):
                    answers_by_doc.setdefault(m["doc"], set()).add(m["answer"].strip().lower()[:40])
            divergent = len({a for s in answers_by_doc.values() for a in s}) >= 2 and len(answers_by_doc) >= 2
            tension = ({"increases", "decreases"} <= stances) or ({"affirms", "denies"} <= stances) or divergent

            # Description tension-aware (sert d'input au rédacteur LLM de topic)
            pos_lines = []
            seen = set()
            for m in members:
                key = (m["doc"], (m.get("answer") or "")[:50])
                if m.get("answer") and key not in seen:
                    seen.add(key)
                    pos_lines.append(f"{m['doc']} [{m.get('stance')}]: {m['answer'][:90]}")
                if len(pos_lines) >= 8:
                    break
            desc = f"Question: {r['question']}\nPositions across {r['doc_count']} sources:\n- " + "\n- ".join(pos_lines)
            if tension:
                desc = "⚠ CONFLICTING ANSWERS (debate) — present BOTH sides explicitly.\n" + desc

            out.append({
                "perspective_id": r["kp_id"],
                "label": r["question"],
                "description": desc,
                "subjects": subjects,
                "facets": [theme_for(r["question"])],
                "keywords": subjects[:5],
                "claim_count": r["claim_count"],
                "doc_count": r["doc_count"],
                "importance_score": float(r["claim_count"]) * (2.0 if tension else 1.0),
                "_tension": tension,
            })
        return out


def finalize_schema(drv, tenant):
    """Aligne le schéma sur ce qu'attend l'endpoint /atlas/homepage + crée les
    AtlasTheme (sinon : page vide / thèmes None). Le générateur de base écrit
    name/title ; l'endpoint lit canonical_name/narrative_label/claim_count + nœuds
    AtlasTheme."""
    with drv.session() as s:
        s.run("""
            MATCH (nt:NarrativeTopic {tenant_id:$t})
            OPTIONAL MATCH (k:KeyPoint {kp_id: nt.perspective_id})
            SET nt.narrative_label = coalesce(nt.narrative_label, nt.title),
                nt.claim_count = coalesce(nt.claim_count, k.claim_count, 0),
                nt.perspective_count = coalesce(nt.perspective_count, 1),
                nt.subject_names = coalesce(nt.subject_names, [])
        """, t=tenant)
        s.run("""
            MATCH (ar:AtlasRoot {tenant_id:$t}) SET ar.canonical_name = coalesce(ar.canonical_name, ar.name)
            WITH ar OPTIONAL MATCH (ar)-[hc:HAS_CHAPTER]->(nt:NarrativeTopic)
            SET hc.reading_order = coalesce(hc.reading_order, 0)
            WITH ar, sum(coalesce(nt.claim_count,0)) AS cc SET ar.claim_count = cc
        """, t=tenant)
        s.run("MATCH (th:AtlasTheme {tenant_id:$t}) DETACH DELETE th", t=tenant)
        s.run("""
            MATCH (r:AtlasRoot {tenant_id:$t})
            OPTIONAL MATCH (r)-[:HAS_CHAPTER]->(x:NarrativeTopic)
            WITH r, collect(x) AS topics
            CREATE (th:AtlasTheme {tenant_id:$t, theme_id:'theme_'+r.root_id, label:r.name,
                description:coalesce(r.description,''), claim_count:coalesce(r.claim_count,0),
                topic_coverage:size(topics), topic_ids:[x IN topics | x.topic_id],
                perspective_labels:[x IN topics | x.title][0..5]})
        """, t=tenant)
    print("[Atlas-KP] schéma finalisé (champs endpoint + AtlasTheme)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--max-topics", type=int, default=60)
    args = ap.parse_args()

    # vLLM url depuis l'état burst Redis
    from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
    st = get_burst_state_from_redis() or {}
    vllm_url = st.get("vllm_url") or "http://localhost:8000"

    drv = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")),
    )
    gen = KeyPointAtlasGenerator(driver=drv, vllm_url=vllm_url, tenant_id=args.tenant)
    stats = gen.generate_all(max_perspectives=args.max_topics)
    print(f"[Atlas-KP] topics={stats.n_perspectives_processed} erreurs={len(stats.errors)}", flush=True)
    finalize_schema(drv, args.tenant)
    drv.close()


if __name__ == "__main__":
    main()
