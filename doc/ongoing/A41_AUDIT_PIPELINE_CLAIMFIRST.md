# A4.1 — Audit pipeline ClaimFirst : où le `subject_canonical` est perdu

> **Verdict** : ce n'est PAS un bug d'extraction. C'est une **décision design intentionnelle** du prompt `claim_extractor` qui réserve `structured_form` aux claims relationnels HIGH-VALUE. Le runtime_v6 vient piocher dans ce champ pour son indexation par sujet, ce qui est un mauvais alignement architectural.

## 1. Cartographie du flow

```
ClaimExtractor.extract()
    └── LLM prompt (claim_extractor.py:110-183)
            ├── HIGH VALUE  (relation X<-pred->Y, 2 entités nommées) → structured_form = {S, P, O}
            └── MEDIUM VALUE (assertion factuelle avec subject)       → structured_form = NULL ⚠️
                Ex: "X offers a capability", "X has a limitation"

SlotEnricher.enrich() (orchestrator.py:455)
    └── Cible UNIQUEMENT les claims with structured_form (filtre line 449)
        → laisse intactes les claims MEDIUM VALUE sans SF

ClaimPersister
    └── to_neo4j_properties() (models/claim.py:303-323)
            ├── if structured_form is None → ne peuple PAS subject_canonical
            └── if structured_form is set  → dénormalise SF.subject → subject_canonical
                                              SF.predicate → predicate
                                              SF.object → object_canonical

Backfill A3.8 (commit b9161db, 21/05/2026)
    └── Idem ClaimPersister : ne touche QUE les claims with structured_form
        → Ne crée pas de subject_canonical pour les claims sans SF
```

## 2. Code in-vivo

### Prompt extracteur (claim_extractor.py:110-168)

```
**HIGH VALUE** — Relational claims between two named entities:
- X uses / is based on / requires Y
- X replaces / succeeds Y
- X is integrated in / embedded in Y
- X is compatible with / supports Y
→ For these claims, fill the `structured_form` field.

**MEDIUM VALUE** — Specific factual claims with an identifiable subject:
- X offers a specific capability
- X has a specific limitation / constraint
→ `structured_form` = null    ← INTENTIONNEL

## STRICT CONSTRAINT — structured_form predicates
- NEVER invent a predicate outside this list. No synonyms, no inflections, no invented forms.
- If the relationship does not fit any predicate above, set "structured_form": null.
- Subject and object must be proper nouns or technical terms, NOT descriptions or clauses.
- If no clear relation between two named entities → "structured_form": null.
```

### Modèle Claim (models/claim.py:303-323)

```python
def to_neo4j_properties(self) -> Dict[str, Any]:
    ...
    if self.structured_form:
        props["structured_form_json"] = json.dumps(self.structured_form)
        sf_subject = self.structured_form.get("subject")
        sf_predicate = self.structured_form.get("predicate")
        sf_object = self.structured_form.get("object")
        if sf_subject:
            props["subject_canonical"] = sf_subject
        ...
    # ↑ Si structured_form is None → subject_canonical n'est PAS écrit
```

## 3. Pourquoi cette conception ?

`structured_form` a été conçu pour le module **verification V1.1** (`verification/comparison/`), dont le besoin est :

- Comparer 2 claims pour détecter contradiction (`SUPERSEDES`, `CONTRADICTS`, etc.)
- Demande un **prédicat fermé** d'une liste canonique (USES, REPLACES, IS_BASED_ON, ...)
- Demande un **sujet ET un objet** nommés (relation binaire)

Pour ce besoin, restreindre `structured_form` aux relations HIGH-VALUE est **correct**. Une comparaison déterministe ne peut pas se faire sur des claims descriptifs "X offers a capability" (pas de Y normalisé).

## 4. Mais le runtime_v6 utilise `subject_canonical` pour autre chose

ADR A3 §4.1 attend `MATCH (c:Claim {subject_canonical: X})` pour **indexer les claims par leur sujet**, peu importe qu'il y ait un object ou un prédicat canonique.

→ Le runtime_v6 a **réutilisé un champ existant** (`subject_canonical` dénormalisé du `structured_form.subject`) pour un **besoin différent** (indexation par sujet, pas comparaison de relations).

**Mismatch architectural** : `subject_canonical` joue deux rôles incompatibles :
1. Champ de relation (rempli si claim a une relation S-P-O canonique) — besoin verification V1.1
2. Champ d'indexation (devrait être rempli pour tout claim ayant un sujet identifiable) — besoin runtime_v6

## 5. Confirmation empirique

L'audit 200 claims NULL (commit 22/05) confirme :
- **76.5% (cat a)** ont un subject extractible (mais pas de relation S-P-O canonique avec un object) → le pipeline les a délibérément laissés sans structured_form (et donc sans subject_canonical)
- **10% (cat b)** ont un subject pronominal (anaphorique) — résolution contextuelle requise
- **13% (cat d)** sont des phrases descriptives sans sujet d'assertion

→ 87% des NULL ont un subject identifiable, par construction le pipeline ne les capture pas.

## 6. Décision pour A4.2

### Option rejetée : élargir `structured_form` (Option 1)

Modifier le prompt extracteur pour produire `structured_form` même pour les claims MEDIUM VALUE (sans object).
- **Cassure sémantique** : verification V1.1, slot_enricher, deterministic_gates dépendent de "structured_form a un object canonique"
- **Effets de bord** : à auditer sur 20+ modules consommateurs
- **Coût migration KG** : élevé

### Option retenue : champ `subject_canonical` indépendant (Option 2)

**Principe** : extraire le `subject_canonical` **séparément** du `structured_form`, applicable à TOUS les claims (87% via LLM + 13% marginaux flagués).

**Architecture** :

```
ClaimExtractor.extract()  (inchangé pour le moment)
    └── structured_form = {subject, predicate, object} pour HIGH VALUE only

NEW: SubjectIndexer.index_claims(claims)   ← Nouveau composant A4.2
    │
    ├── Pour chaque claim sans structured_form :
    │   ├── Extraire le subject via LLM (Qwen2.5-14B léger, batch)
    │   ├── Si subject extrait avec confiance ≥ seuil → claim.subject_canonical = subject
    │   └── Si échec après 2 tentatives → claim.marginal = True
    │
    ├── Pour chaque claim avec structured_form :
    │   └── claim.subject_canonical = structured_form.subject (déjà fait par to_neo4j_properties)

ClaimPersister (modifié)
    └── to_neo4j_properties()
        ├── Si structured_form → dénormalise comme avant
        └── Sinon, si claim.subject_canonical rempli → écrit ce champ direct
                  + écrit claim.marginal si flag présent
```

### Avantages Option 2

- ✅ N'impacte aucun consommateur existant de `structured_form` (verification, comparison, slot_enricher, etc.)
- ✅ Sépare deux préoccupations légitimes (relation vs indexation)
- ✅ Permet à 87%+ des claims d'être indexables par sujet, sans contraindre le predicate
- ✅ Domain-agnostic : extraction LLM générique, pas de mapping métier
- ✅ Le flag `marginal=true` permet d'exclure les 13% cat d du retrieval principal

### Implication runtime_v6

Le runtime_v6 actuel match sur `subject_canonical` Cypher. Cela continue de fonctionner — il aura juste accès à 92%+ du KG au lieu de 38%, sans aucune modification du runtime.

## 7. Reste à valider en A4.2 (sortie audit)

1. **Choix du modèle LLM** pour l'extraction subject_canonical : Qwen2.5-14B-AWQ via vLLM burst (rapide + cost-effective)
2. **Format du prompt** : retourner JSON `{subject: "X" | null, confidence: 0.0-1.0, marginal: bool}`
3. **Seuil de confidence** pour accepter subject : à calibrer (probablement 0.7-0.8)
4. **Stratégie de tentative** : 2 tentatives max ; si échec → flag marginal
5. **Logging** : tracer la cause (NoSubjectFound, LowConfidence, LLMError) pour audit qualité
6. **Test garde-fou** : test automatique post-ingestion qui vérifie `count(subject_canonical IS NULL AND marginal IS NULL) < 5%`

## 8. Conclusion A4.1

| Question | Réponse |
|---|---|
| Pipeline a-t-il un bug ? | **Non.** Il fait ce pour quoi il a été conçu (verification V1.1) |
| Mais pourquoi 61% NULL alors ? | **Décision design** : structured_form réservé aux relations canoniques |
| Runtime_v6 a-t-il un bug ? | **Hypothèse cassée** : il présume subject_canonical partout |
| Que faire ? | **A4.2 = SubjectIndexer indépendant**, sans toucher structured_form |
| Coût A4.2 | Extraction LLM batch sur ~7134 claims + nouveau composant pipeline (2-3j) |
| Risque | Faible — n'impacte aucun consommateur existant de structured_form |

Mémoire mise à jour : `project_subject_canonical_must_be_quasi_mandatory.md`.
