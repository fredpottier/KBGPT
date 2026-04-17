# ADR : Extraction d'entités domain-agnostic

*Date : 12 avril 2026*
*Statut : Recherche terminée — décision à valider*
*Contexte : test du pipeline sur corpus réglementaire (GDPR, AI Act, CCPA)*

## Constat

L'EntityExtractor actuel repose sur des **heuristiques de casse** (termes capitalisés, acronymes, patterns syntaxiques). Cette approche fonctionne bien sur les corpus techniques (SAP, biomédical) où les entités sont des noms propres ("SAP S/4HANA", "BRCA1", "scispaCy") mais échoue sur les corpus non-techniques.

Sur le corpus réglementaire :
- 55% des claims ont une relation ABOUT vers une entité (après tous les correctifs)
- 45% des claims restent orphelines — non pas par bug technique mais parce que les entités du domaine sont des **concepts en minuscules** que le regex ne peut pas capter
- Parmi ces 45%, **94% n'ont aucun concept juridique identifiable** même avec une liste large — ce sont des propositions prescriptives vagues

### Le problème n'est pas le réglementaire

Le réglementaire est représentatif de **tout corpus non-technique** :

| Domaine | Exemples d'entités structurantes | Captées par regex ? |
|---------|----------------------------------|-------------------|
| Technique/SAP | SAP S/4HANA, BTP, Fiori, ABAP | Oui (noms propres capitalisés) |
| Biomédical | BRCA1, Metformin, Preeclampsia | Oui (termes techniques capitalisés) |
| Réglementaire | data controller, conformity assessment, legitimate interest | Non (minuscules) |
| Finance | risque de contrepartie, ratio de solvabilité | Non |
| RH | entretien professionnel, obligation de reclassement | Non |
| Assurance | franchise contractuelle, subrogation | Non |
| Industrie | non-conformité produit, plan de maintenance préventive | Non |

Si OSMOSIS ne gère que les deux premiers cas, il est limité aux corpus tech/science et perd sa proposition de valeur ("Cortex Documentaire des Organisations").

---

## État de l'art (recherche 12/04/2026)

### Consensus 2025 : le LLM est l'extracteur d'entités

Tous les systèmes de référence pour la construction de KG utilisent le LLM comme extracteur principal :

| Système | Organisation | Approche extraction | Ref |
|---------|-------------|-------------------|-----|
| **GraphRAG** | Microsoft | LLM extrait entités + relations + descriptions. Types auto-tunés par analyse d'échantillon corpus | [GitHub](https://github.com/microsoft/graphrag) |
| **KGGen** | Stanford STAIR Lab | LLM extrait des triples (S, P, O) sans contrainte de type. Clustering itératif pour normalisation | [NeurIPS 2025](https://arxiv.org/abs/2502.09956) |
| **LightRAG** | HKU | LLM extrait entités + relations, stocke dans graphe + index vectoriel. Supporte Qwen | [EMNLP 2025](https://github.com/HKUDS/LightRAG) |
| **Neo4j Graph Builder** | Neo4j | Mode "FREE" sans schéma — le LLM décide des types d'entités | [Doc](https://neo4j.com/developer/genai-ecosystem/importing-graph-from-unstructured-data/) |

**Aucun ne se limite aux noms propres. Aucun n'utilise le NER comme extracteur principal.**

Le NER (spaCy, GLiNER, Legal-BERT) est un **complément** pour les entités nommées du domaine (noms de réglementations, organisations), pas la solution au problème des concepts en minuscules.

### NER vs. Extraction de termes/concepts (ATE)

Ce sont **deux problèmes différents** :
- **NER** : identifie les noms propres (spans dans le texte). Ne fonctionne que si l'entité est textuellement présente
- **ATE** (Automatic Term Extraction) : identifie les termes spécialisés du domaine, qu'ils soient en majuscules ou non
- **Concept Extraction** : identifie le sujet/thème d'une proposition — le LLM doit **comprendre** le texte, pas juste trouver un span

Le problème OSMOSIS est du **concept extraction**, pas du NER.

### Modèles NER juridiques : quasi inexistants

Recherche exhaustive sur HuggingFace + spaCy Universe + GitHub :
- **Blackstone** (ICLR&D) : mort, spaCy 2.1, dernier commit 2021
- **PaDaS-Lab/gbert-legal-ner** : allemand uniquement (19 entity types dont LAW, REGULATION — schéma d'annotation réutilisable)
- **opennyaiorg/en_legal_ner_trf** : spaCy, anglais, entraîné sur jugements indiens (PROVISION, STATUTE, COURT)
- **Legal-BERT** (`nlpaueb/legal-bert-base-uncased`) : base model à fine-tuner, pas de NER pré-entraîné

**Il n'existe pas d'équivalent de scispaCy pour le juridique.** Pas de modèle `en_ner_legal_md` prêt à l'emploi.

### Outils d'extraction de termes (ATE)

| Outil | Approche | Multilingual | Zero-shot | CPU | Utile pour OSMOSIS ? |
|-------|----------|-------------|-----------|-----|---------------------|
| **YAKE** | Features statistiques (position, fréquence, co-occurrence) | 16 langues | Oui | Oui | Signal de termhood, pas suffisant seul |
| **KeyBERT** | Similarité cosinus document ↔ n-grams via sentence-transformers | Oui (via multilingual models) | Oui | Oui | Thèmes de document, pas sujets de claims individuelles |
| **spaCy noun chunks** | Extraction de noun phrases basée sur dependency parse | EN, FR, etc. | Oui | Oui | **Excellent comme source de candidats à filtrer** |
| **AutoPhrase** | Distant supervision Wikipedia + POS segmentation | Toute langue avec Wikipedia | Semi | Oui | Concept bon mais outil daté (2017, C++) |
| **TF-IDF corpus** | Termes distinctifs du corpus (déjà dans `corpus_stats.py`) | Oui | Oui | Oui | Filtrage des termes génériques, déjà implémenté |

---

## Risque critique identifié (review ChatGPT, 12/04/2026)

### L'invariant en danger

OSMOSIS repose sur un invariant fondamental :

> **"Pas d'assertion sans preuve localisable"**

Aujourd'hui, chaque entité est **text-anchored** — elle provient d'un span identifiable dans le texte source. La relation ABOUT est traçable : on peut montrer *où* dans le document l'entité apparaît.

Si on laisse le LLM générer `subject_entity: "data controller"` à partir de "The controller shall ensure...", on passe de l'**extraction** à l'**interprétation** :

- "the controller" → "data controller" ✔️ (normalisation raisonnable)
- "the organisation" → "data processor" ❌ (interprétation)
- "the system" → "security framework" ❌ (hallucination)

### Risques concrets

1. **Dérive sémantique** : le LLM sur-interprète et crée des liens factices
2. **Perte de traçabilité** : on ne peut plus prouver que l'entité est dans le texte
3. **Pollution du KG** : génération massive d'entités génériques ("system", "process", "requirement", "measure") — exactement ce qu'on essaie déjà de filtrer
4. **Mélange extraction/interprétation** : deux natures de données dans le même graphe sans distinction

---

## Décision : Architecture 3 couches + séparation Entity/Concept

### Règle d'or

> **Les outputs LLM ne doivent JAMAIS devenir des entités de vérité sans validation textuelle.**

### Deux niveaux d'entités dans le KG

#### Niveau 1 — Text-anchored Entities (SAFE)

Issues de :
- Regex (termes capitalisés, acronymes) — `EntityExtractor` actuel
- NER domain pack (GLiNER, scispaCy sidecar)
- spaCy noun chunks validés par IDF

**Garanties** : tracables, le span existe dans le texte source.

**Utilisables pour** : relations KG structurantes (ABOUT), navigation, Atlas, audit de provenance.

#### Niveau 2 — LLM-inferred Concepts (à manipuler avec précaution)

Issues de :
- `subject_entity` extrait par le LLM
- `topic_concepts` extraits par le LLM

**Pas de garantie** de correspondance textuelle. C'est une interprétation.

**Utilisables pour** : enrichir le retrieval (scoring Qdrant), clustering, matching sémantique Perspectives, améliorer le recall — mais **PAS** comme entités de première classe dans le KG.

### Modèle de données

```json
{
  "claim_text": "The controller shall ensure appropriate measures...",
  "claim_type": "PRESCRIPTIVE",
  "entities": ["controller"],                  // text-anchored (spans trouvés dans le texte)
  "inferred_subject": "data controller",       // LLM — interprétation, PAS une entité KG
  "topic_concepts": ["data protection"]         // LLM — enrichissement retrieval
}
```

### Comment ça se traduit dans le KG

```
(:Claim)-[:ABOUT]->(:Entity)                    // SEULEMENT text-anchored
(:Claim)-[:TOPIC]->(:Concept)                    // LLM-inferred, relation distincte
(:Concept)-[:SIMILAR_TO]->(:Entity)              // Lien de correspondance si validé
```

Le type de relation (ABOUT vs TOPIC) sépare strictement les deux natures de données. L'invariant "pas d'assertion sans preuve" est préservé sur ABOUT.

---

### Couche 1 — spaCy noun chunks + IDF (le vrai game changer)

**C'est la couche qui résout le plus de problèmes sans risque.**

Pour chaque claim, extraire les noun chunks via spaCy :
1. `nlp(text).noun_chunks` → "the controller", "appropriate technical measures", "a level of security"
2. Nettoyage déterministe : retirer déterminants ("the", "a", "an") → "controller", "appropriate technical measures", "level of security"
3. Filtre IDF (via `corpus_stats.py`) : garder les termes à IDF moyen (ni trop génériques ni trop rares)
4. Filtre longueur : 2-6 mots, 5-50 caractères
5. Validation : le noun chunk **existe dans le texte** → text-anchored → relation ABOUT

**Avantages** :
- Text-anchored : respecte l'invariant preuve
- Déterministe : reproductible, pas de risque d'hallucination
- Multilingue : spaCy supporte EN et FR
- CPU only, rapide
- Déjà dans les dépendances OSMOSIS

**Coverage attendue** : +15-25% (estimation basée sur le fait que les noun chunks captent les concepts en minuscules que le regex rate)

**Fichiers impactés** : nouveau `src/knowbase/claimfirst/extractors/concept_extractor_spacy.py`

### Couche 2 — NER domain pack (complément spécialisé)

Inchangé. Le sidecar domain pack (GLiNER, scispaCy) reste pertinent pour les **entités nommées** spécifiques au domaine. Text-anchored par construction.

### Couche 3 — LLM inline `inferred_subject` (enrichissement, PAS entity KG)

Ajouter `inferred_subject` et `topic_concepts` au prompt du ClaimExtractor. **MAIS** :
- Stockés comme **propriétés** sur le node Claim (pas comme nodes Entity)
- Utilisés pour le retrieval (boost sémantique dans Qdrant)
- Utilisés pour le clustering Perspectives
- **JAMAIS** utilisés pour créer des relations ABOUT

Si un `inferred_subject` matche un noun chunk text-anchored ou une entité existante → le lien ABOUT est créé vers l'entité validée, pas vers le concept LLM.

### Couche 4 — Quality gate spécificité (filtrage amont)

Si une claim n'a aucune entité après les 3 couches (ni noun chunk, ni NER, ni LLM match validé), elle est **trop vague** pour être structurante dans le KG. Options :
- Marquer `quality_status = "low_specificity"` (pas supprimer)
- Exclure du clustering et des Perspectives
- Conserver pour le retrieval vectoriel (Qdrant) mais pas pour la navigation KG

---

## Plan d'implémentation (révisé)

| Phase | Quoi | Effort | Risque | Coverage attendue |
|-------|------|--------|--------|------------------|
| **A** | Couche 1 — spaCy noun chunks + IDF | 3-4h | Faible (déterministe, text-anchored) | 70-80% |
| **B** | Couche 3 — `inferred_subject` dans le prompt (propriété Claim, pas Entity) | 2-3h | Moyen (contrôlé par la séparation ABOUT/TOPIC) | enrichissement retrieval |
| **C** | Couche 4 — quality gate spécificité | 1-2h | Faible | filtrage claims faibles |
| **D** | Mesure — re-import corpus réglementaire | 2-3h | — | validation cible >75% |
| **E** | Promotion Concept → Entity — si un `inferred_subject` est validé par N occurrences text-anchored cross-doc, il peut être promu en Entity | 2-3h | Faible (validation statistique) | +5-10% |

**Cible finale : >75% de claims avec ABOUT** (vs 55% actuellement), tout en préservant l'invariant preuve.

**Différence avec la V1 de l'ADR** : la Couche 1 n'est plus le LLM (risqué) mais spaCy noun chunks (safe). Le LLM passe en Couche 3 comme enrichissement, pas comme source de vérité.

## Références

- [GraphRAG Entity Extraction (GitHub)](https://github.com/microsoft/graphrag/blob/main/graphrag/prompts/index/entity_extraction.py)
- [GraphRAG Auto-Tuning (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/graphrag-auto-tuning-provides-rapid-adaptation-to-new-domains/)
- [KGGen: Extracting Knowledge Graphs from Plain Text (NeurIPS 2025)](https://arxiv.org/abs/2502.09956)
- [GLiNER: Generalist Model for NER (NAACL 2024)](https://aclanthology.org/2024.naacl-long.300/)
- [LightRAG (EMNLP 2025)](https://github.com/HKUDS/LightRAG)
- [Automatic Term Extraction Survey (ACM Computing Surveys 2025)](https://dl.acm.org/doi/10.1145/3787584)
- [LLMs4OL: LLMs for Ontology Learning (ISWC 2024/2025)](https://github.com/HamedBabaei/LLMs4OL)
- [End-to-End Structured Extraction with LLM (Databricks 2025)](https://community.databricks.com/t5/technical-blog/end-to-end-structured-extraction-with-llm-part-1-batch-entity/ba-p/98396)
- [Neo4j LLM Knowledge Graph Builder](https://neo4j.com/developer/genai-ecosystem/importing-graph-from-unstructured-data/)
- [YAKE (INESCTEC)](https://github.com/INESCTEC/yake)
- [KeyBERT Multilingual](https://link.springer.com/chapter/10.1007/978-3-030-79150-6_50)
- [AutoPhrase (Jingbo Shang)](https://github.com/shangjingbo1226/AutoPhrase)
