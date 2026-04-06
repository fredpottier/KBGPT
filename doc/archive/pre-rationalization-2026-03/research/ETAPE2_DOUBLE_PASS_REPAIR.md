# Amélioration Anchor Resolution - Plan Complet

**Date**: 2026-01-09
**Contexte**: Suite à l'Étape 1 (Classification anchor_status)
**Source**: Analyse ChatGPT + Claude du problème 43% FUZZY_FAILED

---

## Diagnostic du Problème

### Ampleur Réelle

Le taux de **~43% de FUZZY_FAILED était une MOYENNE**. En réalité:
- Certains documents avaient **jusqu'à 80%** de FUZZY_FAILED
- Le taux variait fortement selon le type/format de document

### Impact Cascade CRITIQUE

Le problème ne se limite pas aux concepts non ancrés. Il y a un **effet domino**:

```
80% FUZZY_FAILED (pas d'anchors)
    ↓
Concepts sans relation ANCHORED_IN vers chunks
    ↓
Extraction relations canoniques REQUIERT concepts ancrés sur chunks
    ↓
Perte massive de paires de concepts pour extraction relations
    ↓
Document entier potentiellement "MUET" dans le Knowledge Graph
    ↓
Perte d'information structurante même pour documents importants
```

**Exemple concret**:
- Document de 100 concepts, 80% FUZZY_FAILED = 80 concepts sans anchors
- Paires possibles avec anchors: 20 × 19 / 2 = **190 paires**
- Paires possibles si tous ancrés: 100 × 99 / 2 = **4,950 paires**
- **Perte: 96% des relations potentielles!**

### Causes Techniques

1. **Mismatch de texte**: Le LLM reçoit peut-être une version du texte différente de celle utilisée pour le fuzzy matching
2. **Prompt pas assez strict**: Le LLM paraphrase ou fusionne des phrases au lieu de citer verbatim

---

## Plan d'Action (Ordre de Priorité)

### Étape 1 - Classification (COMPLÉTÉE)

- [x] `anchor_status` enum: SPAN, FUZZY_FAILED, NO_MATCH, EMPTY_QUOTE
- [x] Propriétés diagnostic: `fuzzy_best_score`, `anchor_failure_reason`
- [x] Persistance de TOUS les ProtoConcepts dans Neo4j
- [x] Script d'analyse `scripts/analyze_anchor_status.py`
- [ ] **Test de validation à faire demain**

---

### Étape 1bis - Alignement Texte + Prompt Strict (PRIORITAIRE)

**Principe clé de ChatGPT**:
> "Donner au LLM le texte 'matchable' (exactement celui que tu utiliseras côté fuzzy).
> Sinon tu demandes au LLM d'être exact sur une version du texte qu'il ne voit pas."

#### A. Vérifier l'Alignement des Textes

**Fichiers à inspecter**:
- `src/knowbase/semantic/extraction/hybrid_anchor_extractor.py` - texte envoyé au LLM
- `src/knowbase/semantic/anchor_resolver.py` - texte utilisé pour fuzzy matching

**Questions à vérifier**:
1. Le `segment_text` passé au LLM est-il identique au `source_text` du fuzzy matching?
2. Y a-t-il des transformations (nettoyage, normalisation) appliquées à un seul des deux?
3. Les caractères spéciaux (tirets, apostrophes, guillemets) sont-ils identiques?

**Action**: Ajouter un log de debug qui compare les deux textes caractère par caractère.

#### B. Améliorer le Prompt d'Extraction

**Prompt actuel** (à vérifier dans `prompts.py`): Probablement pas assez strict.

**Nouveau prompt recommandé**:

```
INSTRUCTIONS CRITIQUES POUR LES QUOTES:

1. Chaque "quote" DOIT être une COPIE EXACTE d'une sous-chaîne du texte fourni.

2. La quote doit pouvoir être trouvée par une recherche Ctrl+F dans le texte.

3. NE PAS paraphraser. NE PAS fusionner des phrases. NE PAS corriger la grammaire.

4. Si vous ne trouvez pas de sous-chaîne exacte pour un concept,
   retournez "quote": "" (chaîne vide) plutôt qu'une approximation.

5. Inclure suffisamment de contexte (15-40 mots) pour être non-ambigu.

EXEMPLE CORRECT:
- Texte: "SAP S/4HANA Cloud supports real-time analytics and embedded AI."
- Quote: "SAP S/4HANA Cloud supports real-time analytics"

EXEMPLE INCORRECT:
- Quote: "S/4HANA Cloud has real-time analytics" (paraphrase - INTERDIT)
- Quote: "SAP S/4HANA Cloud supports analytics and AI" (fusion - INTERDIT)
```

#### C. Ajouter Option `no_quote`

Permettre au LLM de signaler quand il ne trouve pas de quote exacte:

```json
{
  "concepts": [
    {
      "label": "Real-time Analytics",
      "definition": "...",
      "quote": "SAP S/4HANA Cloud supports real-time analytics",
      "no_quote": false
    },
    {
      "label": "Some Inferred Concept",
      "definition": "...",
      "quote": "",
      "no_quote": true,
      "no_quote_reason": "Concept inferred from context, no verbatim mention"
    }
  ]
}
```

**Fichiers à modifier**:
- `src/knowbase/semantic/extraction/prompts.py` - nouveau prompt
- `src/knowbase/semantic/extraction/hybrid_anchor_extractor.py` - parser `no_quote`

---

### Étape 2 - Double Pass Repair (FILET DE SÉCURITÉ)

**À implémenter APRÈS l'Étape 1bis**, pour les cas résiduels.

Si le fuzzy matching échoue malgré le prompt amélioré:

1. Extraire un contexte réduit (~500-1000 chars) autour de la position approximative
2. Appeler LLM avec prompt de réparation spécialisé
3. Re-tenter le fuzzy matching sur la nouvelle quote

#### Prompt de Réparation

```
SYSTEM:
You are a precise text locator. Your ONLY task is to find an EXACT substring.

USER:
Find the EXACT substring in this text that mentions "{concept_label}".

Concept context:
- Definition: {concept_definition}
- Original quote attempt: {original_llm_quote}

TEXT (search in this EXACT text):
---
{reduced_context_text}
---

RULES:
- Return ONLY text that appears EXACTLY in the text above
- The result must be findable via Ctrl+F
- Include 15-30 words of context
- If no exact match exists, return empty string

RESPONSE (JSON):
{
  "exact_quote": "...",
  "found": true/false
}
```

#### Algorithme

```python
async def repair_failed_anchors(proto_concepts, segment_text):
    for pc in proto_concepts:
        if pc.anchor_status != "FUZZY_FAILED":
            continue

        # Extraire contexte réduit
        reduced_context = extract_reduced_context(
            segment_text,
            pc.fuzzy_best_match_position,  # si disponible
            window_size=800
        )

        # Appel LLM réparation
        repair_result = await call_repair_llm(
            concept_label=pc.label,
            concept_definition=pc.definition,
            original_quote=pc.original_llm_quote,
            reduced_context=reduced_context
        )

        if repair_result.found:
            # Re-tenter fuzzy matching
            new_resolution = resolve_anchor_with_diagnostics(
                llm_quote=repair_result.exact_quote,
                source_text=segment_text,
                ...
            )

            if new_resolution.anchor_status == AnchorStatus.SPAN:
                # Succès! Mettre à jour le ProtoConcept
                pc.anchors = [new_resolution.anchor]
                pc.anchor_status = "SPAN"
                pc.fuzzy_best_score = new_resolution.fuzzy_best_score
                pc.repair_applied = True
```

#### Fichiers à Modifier

1. `src/knowbase/semantic/anchor_resolver.py` - `repair_failed_anchor()`
2. `src/knowbase/semantic/extraction/hybrid_anchor_extractor.py` - appel repair après extraction
3. `src/knowbase/semantic/extraction/prompts.py` - `get_anchor_repair_prompt()`
4. `src/knowbase/config/feature_flags.py` - `enable_double_pass_repair` flag

---

## Métriques Attendues

| Étape | SPAN | FUZZY_FAILED | Amélioration |
|-------|------|--------------|--------------|
| Avant (invisible) | ~57% | ~43% | - |
| Après Étape 1 | ~57% | ~43% | Visibilité |
| Après Étape 1bis | ~80-85% | ~15-20% | Prompt + alignement texte |
| Après Étape 2 | ~90-95% | ~5-10% | Double Pass récupère résiduels |

**Objectif final**: < 10% de FUZZY_FAILED en production

---

## Checklist Demain Matin

1. [ ] Lancer import documents `data/burst/pending/`
2. [ ] Exécuter `analyze_anchor_status.py` - valider Étape 1
3. [ ] Inspecter le code pour vérifier alignement texte LLM ↔ fuzzy
4. [ ] Comparer `segment_text` vs `source_text` avec logs debug
5. [ ] Améliorer prompt dans `prompts.py` si nécessaire
6. [ ] Re-tester et mesurer amélioration
7. [ ] Si encore >15% FUZZY_FAILED, implémenter Double Pass

---

## Références

- ADR Hybrid Anchor Model: `doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md`
- Analyse ChatGPT du 2026-01-09: Prompt strict + Double Pass
- Code extraction: `src/knowbase/semantic/extraction/hybrid_anchor_extractor.py`
- Code anchor: `src/knowbase/semantic/anchor_resolver.py`
- Prompts: `src/knowbase/semantic/extraction/prompts.py`
