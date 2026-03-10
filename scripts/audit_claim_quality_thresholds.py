"""
Audit empirique des seuils de qualité des claims.
Calcule les similarités embedding pour déterminer les seuils optimaux.

Tests:
1. Verif(c) = cos(φ(claim_text), φ(verbatim)) — détecte les fabrications
2. Trivial(c) = cos(φ(subject), φ(object)) — détecte les tautologies
3. Propositionality — détecte les fragments non-propositionnels
"""

import json
import sys
import logging
import numpy as np
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    from neo4j import GraphDatabase
    import os
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def load_claims(driver, limit=300):
    """Charge un échantillon aléatoire de claims avec toutes les données."""
    query = """
    MATCH (c:Claim)
    WHERE c.tenant_id = 'default'
    WITH c, rand() AS r
    ORDER BY r
    LIMIT $limit
    RETURN c.claim_id AS claim_id,
           c.text AS text,
           c.verbatim_quote AS verbatim,
           c.structured_form_json AS sf_json,
           c.claim_type AS claim_type,
           c.confidence AS confidence,
           c.doc_id AS doc_id
    """
    with driver.session() as session:
        result = session.run(query, limit=limit)
        claims = []
        for record in result:
            sf = None
            if record["sf_json"]:
                try:
                    sf = json.loads(record["sf_json"])
                except:
                    pass
            claims.append({
                "claim_id": record["claim_id"],
                "text": record["text"],
                "verbatim": record["verbatim"],
                "sf": sf,
                "claim_type": record["claim_type"],
                "confidence": record["confidence"],
                "doc_id": record["doc_id"],
            })
        return claims


def load_embedding_model():
    """Charge le modèle d'embedding multilingue."""
    from sentence_transformers import SentenceTransformer
    logger.info("Chargement du modèle d'embedding (CPU)...")
    model = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
    logger.info("Modèle chargé.")
    return model


def cosine_similarity(a, b):
    """Cosine similarity entre deux vecteurs."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def compute_verifiability_scores(model, claims):
    """Test 1: cos(φ(claim_text), φ(verbatim)) — détecte les fabrications."""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 1: VÉRIFIABILITÉ — cos(claim_text, verbatim)")
    logger.info(f"{'='*60}")

    texts = [f"query: {c['text']}" for c in claims]
    verbatims = [f"query: {c['verbatim']}" for c in claims]

    logger.info(f"Encoding {len(texts)} claim_texts...")
    text_embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)
    logger.info(f"Encoding {len(verbatims)} verbatims...")
    verb_embeddings = model.encode(verbatims, batch_size=32, show_progress_bar=False)

    scores = []
    details = []
    for i, claim in enumerate(claims):
        sim = cosine_similarity(text_embeddings[i], verb_embeddings[i])
        scores.append(sim)
        details.append({
            "claim_id": claim["claim_id"],
            "text": claim["text"][:120],
            "verbatim": claim["verbatim"][:120],
            "sim": sim,
        })

    scores = np.array(scores)

    # Distribution
    logger.info(f"\nDistribution des scores de vérifiabilité (n={len(scores)}):")
    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]:
        below = np.sum(scores < threshold)
        pct = 100 * below / len(scores)
        logger.info(f"  < {threshold:.2f} : {below:4d} claims ({pct:.1f}%)")

    logger.info(f"\n  Moyenne: {np.mean(scores):.4f}")
    logger.info(f"  Médiane: {np.median(scores):.4f}")
    logger.info(f"  Écart-type: {np.std(scores):.4f}")
    logger.info(f"  Min: {np.min(scores):.4f}")
    logger.info(f"  Max: {np.max(scores):.4f}")
    logger.info(f"  P5:  {np.percentile(scores, 5):.4f}")
    logger.info(f"  P10: {np.percentile(scores, 10):.4f}")
    logger.info(f"  P25: {np.percentile(scores, 25):.4f}")

    # Bottom 20 — candidates pour rejet
    sorted_details = sorted(details, key=lambda x: x["sim"])
    logger.info(f"\n--- TOP 20 PIRES SCORES (candidats rejet) ---")
    for d in sorted_details[:20]:
        logger.info(f"  sim={d['sim']:.3f} | text: {d['text']}")
        logger.info(f"           | verb: {d['verbatim']}")
        logger.info("")

    # Top 10 — exemples conformes
    logger.info(f"\n--- TOP 10 MEILLEURS SCORES (conformes) ---")
    for d in sorted_details[-10:]:
        logger.info(f"  sim={d['sim']:.3f} | text: {d['text']}")
        logger.info(f"           | verb: {d['verbatim']}")
        logger.info("")

    return scores, details


def compute_triviality_scores(model, claims):
    """Test 2: cos(φ(subject), φ(object)) — détecte les tautologies."""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 2: TRIVIALITÉ — cos(subject, object)")
    logger.info(f"{'='*60}")

    sf_claims = [c for c in claims if c["sf"] and c["sf"].get("subject") and c["sf"].get("object")]
    logger.info(f"Claims avec structured_form complète: {len(sf_claims)}/{len(claims)}")

    if not sf_claims:
        logger.info("Aucune claim avec SF, skip.")
        return np.array([]), []

    subjects = [f"query: {c['sf']['subject']}" for c in sf_claims]
    objects = [f"query: {c['sf']['object']}" for c in sf_claims]

    logger.info(f"Encoding {len(subjects)} subjects...")
    subj_embeddings = model.encode(subjects, batch_size=32, show_progress_bar=False)
    logger.info(f"Encoding {len(objects)} objects...")
    obj_embeddings = model.encode(objects, batch_size=32, show_progress_bar=False)

    scores = []
    details = []
    for i, claim in enumerate(sf_claims):
        sim = cosine_similarity(subj_embeddings[i], obj_embeddings[i])
        scores.append(sim)
        details.append({
            "claim_id": claim["claim_id"],
            "text": claim["text"][:120],
            "subject": claim["sf"]["subject"],
            "predicate": claim["sf"]["predicate"],
            "object": claim["sf"]["object"],
            "sim": sim,
        })

    scores = np.array(scores)

    # Distribution
    logger.info(f"\nDistribution des scores de trivialité (n={len(scores)}):")
    for threshold in [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]:
        above = np.sum(scores > threshold)
        pct = 100 * above / len(scores)
        logger.info(f"  > {threshold:.2f} : {above:4d} claims ({pct:.1f}%) — candidats tautologie")

    logger.info(f"\n  Moyenne: {np.mean(scores):.4f}")
    logger.info(f"  Médiane: {np.median(scores):.4f}")
    logger.info(f"  Écart-type: {np.std(scores):.4f}")
    logger.info(f"  Min: {np.min(scores):.4f}")
    logger.info(f"  Max: {np.max(scores):.4f}")
    logger.info(f"  P90: {np.percentile(scores, 90):.4f}")
    logger.info(f"  P95: {np.percentile(scores, 95):.4f}")
    logger.info(f"  P99: {np.percentile(scores, 99):.4f}")

    # Top 20 plus hauts scores = plus tautologiques
    sorted_details = sorted(details, key=lambda x: x["sim"], reverse=True)
    logger.info(f"\n--- TOP 20 PLUS TAUTOLOGIQUES ---")
    for d in sorted_details[:20]:
        logger.info(f"  sim={d['sim']:.3f} | S={d['subject']} | P={d['predicate']} | O={d['object']}")
        logger.info(f"           | text: {d['text']}")
        logger.info("")

    # Bottom 10 — les plus informatifs (S et O très différents)
    logger.info(f"\n--- TOP 10 PLUS INFORMATIFS (S ≠ O) ---")
    for d in sorted_details[-10:]:
        logger.info(f"  sim={d['sim']:.3f} | S={d['subject']} | P={d['predicate']} | O={d['object']}")
        logger.info(f"           | text: {d['text']}")
        logger.info("")

    return scores, details


def compute_sf_alignment_scores(model, claims):
    """Test 3: cos(φ(SF sérialisé), φ(claim_text)) — détecte les SF hallucinations."""
    logger.info(f"\n{'='*60}")
    logger.info("TEST 3: ALIGNEMENT SF↔TEXT — cos(SF sérialisé, claim_text)")
    logger.info(f"{'='*60}")

    sf_claims = [c for c in claims if c["sf"] and c["sf"].get("subject") and c["sf"].get("object")]

    if not sf_claims:
        logger.info("Aucune claim avec SF, skip.")
        return np.array([]), []

    # Sérialiser le SF en texte naturel
    sf_texts = []
    for c in sf_claims:
        sf_str = f"{c['sf']['subject']} {c['sf']['predicate'].lower().replace('_', ' ')} {c['sf']['object']}"
        sf_texts.append(f"query: {sf_str}")

    claim_texts = [f"query: {c['text']}" for c in sf_claims]

    logger.info(f"Encoding {len(sf_texts)} SF sérialisés...")
    sf_embeddings = model.encode(sf_texts, batch_size=32, show_progress_bar=False)
    logger.info(f"Encoding {len(claim_texts)} claim_texts...")
    text_embeddings = model.encode(claim_texts, batch_size=32, show_progress_bar=False)

    scores = []
    details = []
    for i, claim in enumerate(sf_claims):
        sim = cosine_similarity(sf_embeddings[i], text_embeddings[i])
        scores.append(sim)
        details.append({
            "claim_id": claim["claim_id"],
            "text": claim["text"][:120],
            "sf_str": f"{claim['sf']['subject']} {claim['sf']['predicate']} {claim['sf']['object']}",
            "sim": sim,
        })

    scores = np.array(scores)

    logger.info(f"\nDistribution des scores SF↔text (n={len(scores)}):")
    for threshold in [0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]:
        below = np.sum(scores < threshold)
        pct = 100 * below / len(scores)
        logger.info(f"  < {threshold:.2f} : {below:4d} claims ({pct:.1f}%) — SF décorrélé du texte")

    logger.info(f"\n  Moyenne: {np.mean(scores):.4f}")
    logger.info(f"  Médiane: {np.median(scores):.4f}")
    logger.info(f"  Écart-type: {np.std(scores):.4f}")
    logger.info(f"  P5:  {np.percentile(scores, 5):.4f}")
    logger.info(f"  P10: {np.percentile(scores, 10):.4f}")

    # Bottom 20
    sorted_details = sorted(details, key=lambda x: x["sim"])
    logger.info(f"\n--- TOP 20 PIRES ALIGNEMENTS SF↔TEXT ---")
    for d in sorted_details[:20]:
        logger.info(f"  sim={d['sim']:.3f} | SF: {d['sf_str'][:80]}")
        logger.info(f"           | text: {d['text']}")
        logger.info("")

    return scores, details


def compute_propositionality(claims):
    """Test 4: Détection des fragments non-propositionnels (sans verbe)."""
    import re

    logger.info(f"\n{'='*60}")
    logger.info("TEST 4: PROPOSITIONNALITÉ — fragments sans verbe")
    logger.info(f"{'='*60}")

    # Patterns de verbes courants (langue-agnostique via patterns structurels)
    # On cherche des formes verbales anglaises communes dans le domaine SAP
    verb_patterns = [
        r'\b(is|are|was|were|has|have|had)\b',
        r'\b(uses?|requires?|supports?|enables?|provides?|extends?|replaces?)\b',
        r'\b(can|could|may|might|must|shall|should|will|would)\b',
        r'\b(allows?|includes?|contains?|defines?|configures?|integrates?)\b',
        r'\b(based|powered|designed|intended|compatible|available)\b',
        r'\b(runs?|sends?|creates?|processes?|manages?|handles?)\b',
        r'\b\w+(?:ed|ing|tion|sion)\b',  # Suffixes verbaux/nominaux
    ]

    no_verb_claims = []
    has_verb_claims = []

    for claim in claims:
        text = claim["text"]
        has_verb = False
        for pattern in verb_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                has_verb = True
                break

        if has_verb:
            has_verb_claims.append(claim)
        else:
            no_verb_claims.append(claim)

    logger.info(f"\nRésultats (n={len(claims)}):")
    logger.info(f"  Avec verbe détecté:  {len(has_verb_claims)} ({100*len(has_verb_claims)/len(claims):.1f}%)")
    logger.info(f"  Sans verbe détecté:  {len(no_verb_claims)} ({100*len(no_verb_claims)/len(claims):.1f}%)")

    if no_verb_claims:
        logger.info(f"\n--- CLAIMS SANS VERBE DÉTECTÉ ---")
        for c in no_verb_claims[:20]:
            logger.info(f"  [{c['claim_id'][:20]}] len={len(c['text']):3d} | {c['text'][:120]}")

    # Claims courtes sans verbe = fragments nominaux très suspects
    short_no_verb = [c for c in no_verb_claims if len(c["text"]) < 80]
    logger.info(f"\n  Fragments nominaux courts (<80 chars, sans verbe): {len(short_no_verb)}")
    for c in short_no_verb:
        logger.info(f"    [{c['claim_id'][:20]}] | {c['text']}")

    return no_verb_claims


def main():
    logger.info("=" * 60)
    logger.info("AUDIT QUALITÉ CLAIMS — Tests de seuils empiriques")
    logger.info("=" * 60)

    # 1. Charger les données
    driver = get_neo4j_driver()
    claims = load_claims(driver, limit=300)
    logger.info(f"\n{len(claims)} claims chargées depuis Neo4j")
    driver.close()

    # 2. Charger le modèle
    model = load_embedding_model()

    # 3. Test 1: Vérifiabilité
    verif_scores, verif_details = compute_verifiability_scores(model, claims)

    # 4. Test 2: Trivialité
    triv_scores, triv_details = compute_triviality_scores(model, claims)

    # 5. Test 3: Alignement SF↔text
    sf_scores, sf_details = compute_sf_alignment_scores(model, claims)

    # 6. Test 4: Propositionnalité
    no_verb = compute_propositionality(claims)

    # 7. Synthèse et recommandations
    logger.info(f"\n{'='*60}")
    logger.info("SYNTHÈSE ET SEUILS RECOMMANDÉS")
    logger.info(f"{'='*60}")

    if len(verif_scores) > 0:
        # Seuil vérifiabilité: on veut rejeter les fabrications pures
        # sans rejeter les reformulations légitimes
        p10_verif = np.percentile(verif_scores, 10)
        p5_verif = np.percentile(verif_scores, 5)
        logger.info(f"\n1. VÉRIFIABILITÉ cos(text, verbatim):")
        logger.info(f"   P5={p5_verif:.3f}, P10={p10_verif:.3f}")
        logger.info(f"   Seuil recommandé: {max(0.5, p5_verif):.2f}")
        logger.info(f"   Claims rejetées à ce seuil: {np.sum(verif_scores < max(0.5, p5_verif))}")

    if len(triv_scores) > 0:
        p95_triv = np.percentile(triv_scores, 95)
        p90_triv = np.percentile(triv_scores, 90)
        logger.info(f"\n2. TRIVIALITÉ cos(subject, object):")
        logger.info(f"   P90={p90_triv:.3f}, P95={p95_triv:.3f}")
        logger.info(f"   Seuil recommandé: {min(0.92, p95_triv):.2f}")
        logger.info(f"   Claims rejetées à ce seuil: {np.sum(triv_scores > min(0.92, p95_triv))}")

    if len(sf_scores) > 0:
        p5_sf = np.percentile(sf_scores, 5)
        p10_sf = np.percentile(sf_scores, 10)
        logger.info(f"\n3. ALIGNEMENT SF↔TEXT cos(SF, text):")
        logger.info(f"   P5={p5_sf:.3f}, P10={p10_sf:.3f}")
        logger.info(f"   Seuil recommandé: {max(0.55, p5_sf):.2f}")
        logger.info(f"   Claims rejetées à ce seuil: {np.sum(sf_scores < max(0.55, p5_sf))}")

    logger.info(f"\n4. PROPOSITIONNALITÉ:")
    logger.info(f"   Fragments sans verbe: {len(no_verb)}/{len(claims)}")
    short_frag = [c for c in no_verb if len(c["text"]) < 80]
    logger.info(f"   Fragments courts (<80 chars) sans verbe: {len(short_frag)}")

    logger.info(f"\n{'='*60}")
    logger.info("FIN DE L'AUDIT")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
