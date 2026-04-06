# ADR — FacetEngine V2 : Adressabilite Semantique Emergente

**Statut :** Draft
**Date :** 2026-03-28
**Auteurs :** Consensus ChatGPT + Claude Opus + Fred
**Contexte :** Diagnostic facettes — 326 liens vs 2659 dans le backup

---

## Contexte

Le FacetMatcher actuel fait du keyword substring match : chaque facette a une liste
de mots-cles, et chaque claim est matchee si elle contient un de ces mots.

Resultat : 2% de couverture (326/15566 claims). La facette "Security" n'a que 8
keywords alors que le Security Guide de 980 pages utilise des centaines de termes
techniques differents (authorization object, audit log, certificate, SSO, SAML...).

## Diagnostic racine (ChatGPT)

Le probleme n'est pas le matching. C'est le modele mental.

On essaie de faire du **tagging lexical** dans un systeme qui est fondamentalement
**information-first + addressability-first**. Cela viole :

1. Addressability-first : une facette basee sur des mots-cles n'est PAS un pivot structurant fiable
2. LLM = extracteur, pas classifieur : le matching substring est du bottom-up naif
3. Lecture stratifiee : on fait texte → mot → facette au lieu de information → sens → facette

## Decision

Remplacer le modele `Facet = {nom + keywords[]}` par
`Facet = pole de regroupement semantique` base sur des prototypes d'Information.

Les facettes ne sont plus definies par des mots-cles mais par des **prototypes
composites** (embeddings) calcules a partir des Informations representativas.

---

## Nouveau modele de donnees

### Noeud Facet

```
Facet:
  facet_id: str
  canonical_label: str
  description: str
  facet_family: str
  status: "candidate" | "validated" | "deprecated" | "split_candidate" | "merge_candidate"
  promotion_level: "STRONG" | "WEAK"
  embedding_model: str
  centroid_vector_ref: str
  prototype_count: int
  doc_count: int
  info_count: int
  claimkey_count: int
  created_at: timestamp
  updated_at: timestamp
  extraction_method: str
```

### Relations

```
(:Information)-[:BELONGS_TO_FACET {
  confidence: float,
  assignment_method: str,   # "embedding_centroid" | "theme_alignment" | "legacy_keyword"
  promotion_level: str,     # "STRONG" | "WEAK"
  score_semantic: float,
  score_theme: float,
  score_claimkey: float,
  assigned_at: timestamp,
  review_status: str        # "auto" | "reviewed" | "rejected"
}]->(:Facet)

(:ClaimKey)-[:BELONGS_TO_FACET]->(:Facet)
(:Theme)-[:ALIGNS_WITH_FACET]->(:Facet)
```

---

## Pipeline FacetEngine V2

### Pass F1 — Facet Bootstrap (LLM, 1 call/doc)

Input : document, themes, top informations
Output : FacetCandidate[] (label + description + exemples, SANS keywords)

### Pass F2 — Facet Normalization

Dedupliquer les facettes proches (embedding clustering + arbitrage LLM sur petits groupes).

### Pass F3 — Prototype Build

Pour chaque facette :
- Embedding du label + description (poids 0.25)
- Centroid des Informations prototypes (poids 0.50)
- Centroid des ClaimKeys associes (poids 0.15)
- Centroid des Themes alignes (poids 0.10)
→ Vecteur composite = le coeur semantique de la facette

### Pass F4 — Assignment multi-signal

Pour chaque Information :
```
global_score =
  0.55 * semantic_similarity(info_vector, facet_vector) +
  0.20 * theme_alignment_score +
  0.15 * claimkey_alignment_score +
  0.10 * structural_cohesion_score

if global_score >= 0.82 and semantic >= 0.75 → STRONG
elif global_score >= 0.68 → WEAK
else → pas de lien
```

### Pass F5 — Governance

Metriques de sante par facette :
- info_count, doc_count, weak_ratio, strong_ratio
- top_doc_concentration, cross_doc_stability
- merge_candidate_with, split_candidate, drift_alert

Regles :
- doc_count=1 + info_count<8 → reste candidate
- Forte dispersion → split possible
- Forte proximite vectorielle entre 2 facettes → merge candidate

---

## Invariants

1. Aucune facette ne depend d'une liste de termes metier
2. Pas de matching par taxonomie fermee
3. Le label n'est qu'une facade lisible — le coeur est le prototype composite
4. Les facettes sont des surfaces d'organisation, pas des verites
5. STRONG vs WEAK comme gouvernance, pas comme verite

---

## Structure modules

```
src/knowbase/facets/
  models.py              # Facet, FacetCandidate, FacetPrototype, FacetAssignment
  bootstrap.py           # Pass F1 : extraction LLM
  normalizer.py          # Pass F2 : fusion/split/canonicalisation
  prototype_builder.py   # Pass F3 : prototypes composites + embeddings
  scorer.py              # Pass F4 : score multi-signal
  assigner.py            # Pass F4 : creation relations
  governance.py          # Pass F5 : metriques sante + alertes
  orchestrator.py        # Pipeline complet
```

---

## Plan de migration

### Sprint 1 — Assignment par embeddings
Creer le modele Facet V2 et l'assignment Information → Facet via embeddings + seuils.

### Sprint 2 — Signaux enrichis
Ajouter Theme → Facet et ClaimKey → Facet pour enrichir les signaux.

### Sprint 3 — Gouvernance
Ajouter weak/strong, health metrics, merge/split candidates.

### Sprint 4 — Navigation
Brancher le runtime de navigation / UI sur cette couche.

### Mode shadow pendant la transition
- FacetEngineV2 en parallele de rebuild_facets.py
- Dual write : BELONGS_TO_FACET_LEGACY + BELONGS_TO_FACET
- Retrait progressif des keywords

---

## References

- Diagnostic facettes 2026-03-28 (326 liens vs 2659)
- ADR KG Quality Pipeline V3
- Consensus ChatGPT + Claude Opus (2026-03-28)
