# Étude des listes de stopwords OSMOSIS — Rôle, usage, remédiations

*Document d'analyse pour review externe. Rédigé le 2026-04-09.*

---

## Contexte

OSMOSIS utilise actuellement **3 listes de mots figées** (588 items au total, FR+EN uniquement) à différents points critiques du pipeline. Ces listes fonctionnent sur le corpus SAP actuel (français + anglais), mais constituent un risque structurel si le système doit traiter un corpus dans une autre langue (italien, allemand, espagnol, néerlandais...).

**Le problème fondamental** : une liste figée sur un besoin sans délimitation franche finira toujours par tomber sur un cas non prévu. Avant d'externaliser ces listes dans des fichiers, il faut étudier si des mécanismes dynamiques ne rendraient pas ces listes partiellement ou totalement inutiles.

**Infrastructure existante dans OSMOSIS** :
- **Détection de langue** : `LanguageDetector` basé sur fasttext `lid.176.bin` (176 langues), singleton avec cache LRU, déjà utilisé dans 12+ modules
- **IDF du corpus** : `_get_corpus_idf()` dans `kg_signal_detector.py` — calcule l'IDF de chaque terme à partir d'un échantillon de 2000 chunks Qdrant, cache en mémoire
- **spaCy** : déjà dans les dépendances du projet (utilisé pour la segmentation et NER)

---

## Liste 1 : `ENTITY_STOPLIST`

### Localisation
- **Fichier** : `src/knowbase/claimfirst/models/entity.py`, lignes 241-326
- **Type** : `frozenset` de 308 items

### Rôle
Empêcher des mots trop génériques d'être promus en entités nommées (`Entity`) dans le Knowledge Graph. Le LLM d'extraction de claims peut proposer des candidats entités qui sont des mots courants ("system", "document", "version", "ce", "un"...). Cette liste sert de filtre post-extraction.

### Usage dans le code

**Point d'appel principal** — `entity.py:393` dans `is_valid_entity_name()` :
```python
normalized = Entity.normalize(name)
if normalized in ENTITY_STOPLIST:
    return False   # → entité rejetée
```
Cette fonction est le point de validation unique : tout candidat entité passe par ce test.

**Point d'appel secondaire** — `entity_extractor.py:111` :
```python
self.stoplist = ENTITY_STOPLIST.copy()
if custom_stoplist:
    self.stoplist = self.stoplist | {s.lower() for s in custom_stoplist}
```
L'extracteur copie la liste au démarrage et peut la fusionner avec une stoplist custom (ex: domain pack). Il l'utilise ensuite pour compter les entités filtrées dans ses stats.

### Composition de la liste (308 items)

| Catégorie | Exemples | Nb items approx. | % |
|---|---|---:|---:|
| Noms génériques EN | "system", "document", "service", "process", "feature" | ~70 | 23% |
| Noms génériques FR | "système", "document", "service", "processus", "fonctionnalité" | ~40 | 13% |
| Pluriels EN | "systems", "services", "documents", "applications" | ~30 | 10% |
| Articles, déterminants, pronoms EN | "the", "a", "this", "he", "which", "some" | ~40 | 13% |
| Articles, déterminants FR | "le", "la", "ce", "un", "quelque", "chaque" | ~25 | 8% |
| Prépositions, conjonctions, adverbes EN | "to", "of", "and", "but", "also", "very" | ~50 | 16% |
| Verbes génériques EN | "use", "set", "get", "make", "need" | ~20 | 6% |
| Faux acronymes (mots courts) | "as", "new", "up", "non", "map", "fix" | ~15 | 5% |
| Chiffres romains | "ii", "iii", "iv", "vi", "vii" | ~9 | 3% |
| Acronymes 2-chars ambigus | "nt", "fn", "cg", "bv", "ck" | ~9 | 3% |

### Listes compagnons dans le même fichier

Deux autres listes figées travaillent en tandem avec `ENTITY_STOPLIST` :

- **`PHRASE_FRAGMENT_INDICATORS`** (ligne 329, ~30 items) : verbes modaux et auxiliaires EN+FR ("will", "should", "is", "was", "doit", "sera"...). Si un mot de cette liste apparaît dans un candidat multi-mots, c'est un fragment de phrase, pas une entité.
- **`_FUNCTION_WORDS`** (ligne 343, ~50 items) : prépositions, conjonctions, pronoms EN. Un candidat multi-mots ne doit pas **commencer** par un de ces mots.

Ces deux listes ont les mêmes problèmes de couverture linguistique limitée.

### Risque sur corpus non-FR/EN

Sur un corpus italien, les mots "che", "questo", "uno", "delle", "sistema", "documento" passeraient le filtre et seraient promus en entités. Le graphe serait pollué de centaines d'entités-bruit, dégradant la qualité du KG et des Perspectives qui en dépendent. **Dégradation silencieuse** : pas d'erreur visible, juste des résultats de moins en moins pertinents.

### Remédiation proposée — approche hybride à 3 niveaux

#### Niveau 1 : POS tagging via spaCy (élimine ~60% de la liste)

**Principe** : les articles, pronoms, prépositions, conjonctions, adverbes et verbes auxiliaires sont des **catégories grammaticales** (Part-of-Speech). Un POS tagger les identifie dans n'importe quelle langue supportée par son modèle.

**Implémentation** :
```python
import spacy

# spaCy supporte 25+ langues avec POS tagging
# Modèles légers (~15MB) : en_core_web_sm, fr_core_web_sm, de_core_web_sm,
#                           it_core_web_sm, es_core_web_sm, nl_core_web_sm...
# Modèle multilingue (pas de détection de langue nécessaire) : xx_sent_ud_sm

EXCLUDED_POS = {"DET", "PRON", "ADP", "CCONJ", "SCONJ", "AUX", "PART", "INTJ"}

def is_function_word(word: str, nlp) -> bool:
    """True si le mot est un mot-outil grammatical (toute langue)."""
    doc = nlp(word)
    return doc[0].pos_ in EXCLUDED_POS
```

**Ce que ça remplace** : toute la section articles/déterminants/pronoms/prépositions/conjonctions/adverbes EN+FR (~170 items), PLUS `PHRASE_FRAGMENT_INDICATORS` (~30 items) et `_FUNCTION_WORDS` (~50 items). Soit **~250 items sur 388 (total des 3 listes) supprimés, et fonctionnel en 25+ langues**.

**Limites** : le POS tagger seul ne reconnaît pas qu'un nom commun comme "system" est trop générique pour être une entité. Il classerait "system" comme NOUN — ce qui est grammaticalement correct mais insuffisant pour notre besoin.

#### Niveau 2 : Seuil IDF / Document Frequency (élimine les noms génériques)

**Principe** : un mot qui apparaît dans une large proportion des documents du corpus est, par définition, générique **dans ce corpus**. "system" dans un corpus IT a un DF très élevé → c'est du bruit. "system" dans un corpus médical a un DF bas → c'est potentiellement pertinent.

**Implémentation** :
```python
def is_too_generic(word: str, corpus_df: dict, total_docs: int, 
                   threshold: float = 0.30) -> bool:
    """True si le mot apparaît dans >30% des documents du corpus."""
    df = corpus_df.get(word.lower(), 0)
    return (df / total_docs) > threshold if total_docs > 0 else False
```

**Ce que ça remplace** : les noms génériques EN+FR ("system", "document", "service", "système", "document"...) qui constituent ~110 items de la liste. Et ce de façon **auto-adaptative** : le seuil s'ajuste au corpus. Si un nouveau corpus ne contient pas souvent le mot "system", celui-ci ne sera plus filtré — et c'est correct.

**Prérequis** : calculer la Document Frequency sur le corpus. OSMOSIS calcule déjà l'IDF dans `kg_signal_detector.py` — il faudrait soit réutiliser ce cache, soit construire un cache DF dédié partagé entre les modules (à discuter).

**Limites** : sur un corpus très petit (< 10 documents), le DF peut être instable. Fallback nécessaire pour les très petits corpus.

#### Niveau 3 : Liste résiduelle minimale (~30-50 items)

**Ce qui reste** après niveaux 1 et 2 :

- **Chiffres romains** ("ii", "iii", "iv"...) : ni mots-outils, ni fréquents dans le corpus. Regex `^[ivxlcdm]{2,5}$` sur le lowercase suffit. **0 item dans la liste.**
- **Faux acronymes courts** ("as", "up", "non", "fn"...) : 2-3 chars, all-alpha, mais pas des entités. Heuristique : `len <= 3 AND all_alpha AND not_in_domain_gazetteer`. **0 item dans la liste** si on a cette heuristique.
- **Acronymes 2-chars ambigus** ("nt", "cg", "bv"...) : couverts par la même heuristique.
- **Verbes génériques courts** ("use", "set", "get"...) : le POS tagger les classera comme VERB → filtrable. **0 item si on ajoute VERB aux POS exclus.** Mais attention : certains verbes nominalisés ("use" → "use case") doivent être gardés comme partie d'une entité multi-mots. Solution : ne filtrer les VERB que sur les candidats **mono-mot**.
- **Noms génériques résiduels** non couverts par le DF (cas du corpus trop petit ou mot absent du corpus mais quand même trop vague) : une petite liste de ~30 mots universellement trop vagues pour être des entités, toutes langues confondues. Ex: "thing", "item", "element", "stuff", "part", "area", "aspect"... Ces mots sont tellement basiques qu'ils sont rarement des entités dans aucun domaine.

**Taille résiduelle estimée : ~30 items** (contre 308 aujourd'hui), la plupart étant des mots tellement basiques qu'ils ne posent pas de problème de couverture linguistique.

### Risques de la remédiation

| Risque | Probabilité | Mitigation |
|---|---|---|
| POS tagger se trompe sur un mot rare | Faible (>95% de précision sur les modèles spaCy) | Double filtre : POS + normalisation existante |
| DF instable sur très petit corpus (< 10 docs) | Moyenne | Fallback : si corpus < 20 docs, utiliser la liste résiduelle seule |
| Mot générique dans une langue non couverte par spaCy | Faible (spaCy couvre 25+ langues) | Le filtre DF rattrape : si le mot est fréquent, il est filtré quelle que soit la langue |
| Latence POS tagging à l'ingestion | Faible | ~0.1ms par mot avec spaCy, négligeable vs LLM call |
| spaCy non installé / modèle manquant | Moyenne | Fallback gracieux vers la liste résiduelle |

---

## Liste 2 : `_STOPWORDS`

### Localisation
- **Fichier** : `src/knowbase/api/services/kg_signal_detector.py`, lignes 248-268
- **Type** : `frozenset` de 149 items

### Rôle
Filtrer les mots-outils avant un calcul TF-IDF pour la **détection de gap question↔contexte** (Signal 5 du KG Signal Detector). L'objectif est d'identifier les termes **spécifiques** de la question utilisateur et de vérifier si le contexte récupéré (chunks Qdrant + claims KG) couvre ces termes. Si des termes spécifiques de la question sont absents du contexte → signal "gap" → le système sait que la réponse risque d'être incomplète.

### Usage dans le code

**Point d'appel unique** — `kg_signal_detector.py:278` dans `_tokenize_simple()` :
```python
def _tokenize_simple(text: str) -> list[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]
```

**Chaîne d'appel** :
1. `_tokenize_simple()` est appelée par `_extract_specific_terms()` (ligne 349) pour tokeniser la question
2. `_extract_specific_terms()` calcule l'IDF de chaque token et garde les `top_n` plus spécifiques (IDF élevé)
3. `_detect_question_context_gap()` (ligne 368) compare ces termes spécifiques au vocabulaire des chunks

### Observation critique

Le code calcule **déjà** l'IDF du corpus dans `_get_corpus_idf()` (ligne 281). La fonction `_extract_specific_terms()` filtre ensuite les termes avec `idf_score >= min_idf` (défaut 2.0).

**Le double filtrage est redondant** : `_STOPWORDS` filtre les mots-outils (fréquents par nature) → puis le seuil IDF filtre les mots fréquents dans le corpus. Les stopwords ont par définition un IDF très bas (proches de 0) car ils apparaissent dans presque tous les chunks. Le seuil `min_idf >= 2.0` les élimine automatiquement.

### Composition de la liste (149 items)

| Catégorie | Nb items approx. |
|---|---:|
| Déterminants, pronoms FR | ~30 |
| Prépositions, conjonctions FR | ~20 |
| Verbes auxiliaires FR | ~10 |
| Déterminants, pronoms EN | ~25 |
| Prépositions, conjonctions EN | ~30 |
| Verbes auxiliaires/modaux EN | ~20 |
| Adverbes communs EN | ~14 |

### Risque sur corpus non-FR/EN

Les stopwords italiens ("che", "questo", "nella", "sono", "hanno"...) ne sont pas filtrés. Ils seront tokenisés, et comme ils n'apparaissent pas dans le corpus (qui est FR/EN), leur IDF sera très élevé (terme "inconnu"). Ils seront donc considérés comme des **termes spécifiques** de la question, ce qui pollue la détection de gap : le système croit que "che" est un terme technique absent du contexte.

### Remédiation proposée — seuil IDF pur

**Principe** : supprimer la liste et s'appuyer uniquement sur l'IDF du corpus, qui est déjà calculé.

**Modification concrète** :
```python
# AVANT
def _tokenize_simple(text: str) -> list[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]

# APRÈS
def _tokenize_simple(text: str) -> list[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())
    return words   # Le filtrage se fait en aval par seuil IDF
```

Le filtrage par spécificité est déjà fait dans `_extract_specific_terms()` via le seuil `min_idf`. Les stopwords y sont naturellement éliminés car leur IDF est bas.

**Cas particulier — termes absents du corpus** : un stopword dans une langue non couverte par le corpus aurait un IDF très élevé (terme inconnu = `log(N+1)` dans le code actuel). Pour y remédier :
```python
# Ajouter un filtre : les termes qui n'apparaissent pas DU TOUT dans le corpus
# ne sont pas "spécifiques" — ils sont juste hors-domaine
idf_score = idf.get(token, None)
if idf_score is None:
    continue   # terme inconnu du corpus = pas pertinent pour la comparaison gap
```

Ce simple changement résout le problème multilingue : un stopword italien posé en question sur un corpus EN ne sera plus considéré comme "terme spécifique manquant" car il est tout simplement absent du vocabulaire du corpus.

**Taille de la liste résiduelle : 0 items.**

### Risques de la remédiation

| Risque | Probabilité | Mitigation |
|---|---|---|
| IDF non encore calculé au premier appel | Faible | Le fallback existe déjà (ligne 352) : garder tokens de 4+ chars |
| Corpus vide → pas d'IDF | Faible | Le code gère déjà ce cas (ligne 300-302) |
| Un vrai terme technique est aussi absent du corpus | Possible | C'est correct : si le terme n'est nulle part dans le corpus, le gap est **réel**, pas un artefact. Mais on ne peut pas le détecter par gap puisqu'on n'a pas de référence. Le système doit utiliser d'autres signaux. |

---

## Liste 3 : `_BM25_STOPWORDS`

### Localisation
- **Fichier** : `src/knowbase/api/services/retriever.py`, lignes 161-178
- **Type** : `frozenset` de 131 items

### Rôle
Filtrer les mots non-techniques dans l'extraction de keywords BM25 pour la recherche hybride (sémantique + BM25 full-text). Le retriever extrait les 4 termes les plus "techniques" de la question pour construire une requête BM25 `MatchText`. Les stopwords reçoivent un score de 0 dans la fonction `is_technical()`, ce qui les exclut de la sélection.

### Usage dans le code

**Point d'appel unique** — `retriever.py:197` dans `is_technical()` (nested dans `_extract_bm25_keywords()`) :
```python
def is_technical(w: str) -> int:
    if len(w) <= 2:
        return 0
    if w.lower() in _BM25_STOPWORDS:
        return 0               # ← stopword = score 0 = exclu
    score = 0
    if '/' in w or '_' in w:   # SAP S/4HANA, /SCWM/...
        score += 5
    if any(c.isdigit() for c in w):   # 2023, 2008727
        score += 4
    if w.isupper() and len(w) >= 2:   # SAP, MRP, EWM
        score += 3
    elif any(c.isupper() for c in w[1:]):  # camelCase
        score += 2
    elif w[0].isupper():              # Nom propre
        score += 1
    return score
```

**Chaîne d'appel** :
1. `_extract_bm25_keywords(question)` tokenise la question, score chaque mot, garde les top-4
2. `_hybrid_search()` injecte ces keywords dans une requête Qdrant MatchText

### Observation critique

La fonction `is_technical()` a déjà des **heuristiques positives fortes** : `/`, `_`, chiffres, majuscules, camelCase. Un mot purement lowercase sans caractère spécial obtient score=0 ou score=1 (s'il commence par une majuscule). La stoplist ne sert qu'à éliminer les mots FR/EN courants qui pourraient avoir score=1 (ex: "Comment", "Quel" commencent par majuscule).

### Composition de la liste (131 items)

| Catégorie | Nb items approx. |
|---|---:|
| Déterminants, pronoms FR | ~30 |
| Prépositions, conjonctions FR | ~25 |
| Verbes auxiliaires / modaux FR | ~15 |
| Déterminants, pronoms EN | ~20 |
| Prépositions, conjonctions EN | ~25 |
| Verbes auxiliaires/modaux EN | ~16 |

### Risque sur corpus non-FR/EN

Question en italien : *"Quali sono le differenze tra la versione 2022 e 2023?"* → "Quali" (score +1 car majuscule), "sono" (pas dans la liste → potentiellement sélectionné), "differenze" (pas dans la liste → sélectionné). La requête BM25 inclurait "sono" (verbe être italien) comme keyword technique → bruit dans le full-text search.

### Remédiation proposée — IDF/DF + renforcement heuristiques

**Option A — Seuil IDF (même cache que la liste 2)** :
```python
def is_technical(w: str, corpus_idf: dict) -> int:
    if len(w) <= 2:
        return 0
    # Mot très fréquent dans le corpus = pas technique
    idf_score = corpus_idf.get(w.lower())
    if idf_score is not None and idf_score < 1.5:  
        return 0   # Remplacement de la stoplist
    # Mot absent du corpus = pas utile pour BM25 
    # (le full-text search ne le trouvera pas de toute façon)
    if idf_score is None:
        return 0
    # ... heuristiques positives inchangées ...
```

**Logique** : si un mot est très fréquent dans le corpus (IDF bas), ce n'est pas un terme discriminant pour BM25. S'il est absent du corpus, le BM25 ne le trouvera pas non plus → inutile de l'inclure.

**Option B — POS tagging léger** : filtrer les DET/PRON/ADP/CONJ/AUX au moment du parsing de la question. Avantage : ne dépend pas du corpus. Inconvénient : ajoute une dépendance spaCy au retriever (qui ne l'utilise pas aujourd'hui).

**Recommandation** : Option A (IDF) car elle est cohérente avec la remédiation de la liste 2, n'ajoute pas de dépendance, et s'auto-adapte. Le cache IDF peut être mutualisé entre `kg_signal_detector.py` et `retriever.py`.

**Taille de la liste résiduelle : 0 items.**

### Risques de la remédiation

| Risque | Probabilité | Mitigation |
|---|---|---|
| Cache IDF pas encore disponible au démarrage du retriever | Moyenne | Lazy init au premier appel (pattern déjà en place dans kg_signal_detector) |
| Couplage retriever ↔ corpus IDF | Faible | Cache partagé en read-only, calcul fait une seule fois |
| Mot fréquent dans le corpus mais quand même "technique" | Très faible | Le seuil IDF < 1.5 correspond à un mot présent dans >22% des chunks. Aucun terme véritablement technique n'est si fréquent. Et les heuristiques positives (majuscules, chiffres, `/`) boostent le score indépendamment de l'IDF. |

---

## Synthèse comparative

| Critère | Aujourd'hui (listes figées) | Après remédiation |
|---|---|---|
| **Items à maintenir** | 588 (FR+EN seulement) | ~30 (universels, toute langue) |
| **Langues couvertes** | 2 (FR, EN) | Toutes (POS: 25+ via spaCy, IDF: auto-adaptatif) |
| **Adaptation au corpus** | Aucune (même liste SAP ou médical) | Automatique via IDF |
| **Maintenance** | Manuelle (ajouter des mots un par un) | Quasi-nulle (seule la petite liste résiduelle) |
| **Risque de faux positif** | Existant (ex: "DM" filtré alors que c'est un acronyme médical) | Réduit (IDF corpus-aware, POS grammar-aware) |
| **Risque de faux négatif** | Élevé sur langues non couvertes | Résiduel faible (POS + IDF couvrent 99% des cas) |
| **Dépendances ajoutées** | Aucune | spaCy (déjà présent) + mutualisation cache IDF |
| **Latence ajoutée** | 0 | Négligeable (~0.1ms POS, IDF déjà en cache) |

---

## Plan d'implémentation proposé

### Phase 1 : Mutualiser le cache IDF (pré-requis, ~2h)
- Extraire `_get_corpus_idf()` dans un module partagé (`src/knowbase/common/corpus_stats.py`)
- Le rendre accessible depuis `kg_signal_detector.py` ET `retriever.py`
- Ajouter un champ `document_frequency` (nombre brut de chunks contenant le terme) en plus de l'IDF

### Phase 2 : Remplacer `_STOPWORDS` par seuil IDF (~1h)
- Supprimer la constante `_STOPWORDS` dans `kg_signal_detector.py`
- Modifier `_tokenize_simple()` pour ne plus filtrer par liste
- Ajouter le filtre "terme absent du corpus = pas pertinent" dans `_extract_specific_terms()`
- **Tests** : vérifier que la détection de gap fonctionne toujours sur les questions FR/EN du benchmark

### Phase 3 : Remplacer `_BM25_STOPWORDS` par seuil IDF (~1h)
- Supprimer la constante `_BM25_STOPWORDS` dans `retriever.py`
- Modifier `is_technical()` pour utiliser le seuil IDF au lieu de la stoplist
- **Tests** : vérifier que les keywords BM25 extraits sont toujours pertinents sur les questions du benchmark

### Phase 4 : Remplacer `ENTITY_STOPLIST` par POS + IDF + liste minimale (~3h)
- Ajouter un wrapper POS tagging dans `src/knowbase/common/pos_filter.py` (chargement lazy du modèle spaCy, détection de langue automatique via `LanguageDetector` existant)
- Modifier `is_valid_entity_name()` : POS check → IDF check → liste résiduelle (~30 items)
- Traiter `PHRASE_FRAGMENT_INDICATORS` et `_FUNCTION_WORDS` via le même POS tagger
- **Tests** : vérifier sur le corpus SAP que les entités extraites sont identiques (ou meilleures) post-remédiation

### Phase 5 : Validation cross-langue (~2h)
- Ingérer 2-3 documents en italien ou allemand (PDF open-source)
- Vérifier qu'aucune pollution d'entités génériques n'apparaît dans le graphe
- Vérifier que le signal gap et le BM25 fonctionnent correctement
- Comparer avec le comportement actuel (qui serait dégradé sur ces mêmes documents)

**Effort total estimé : ~9h** (contre 4-8h pour une simple externalisation en fichiers, mais avec un résultat incomparablement plus robuste et pérenne).

---

## Questions ouvertes pour la review

1. **Seuil IDF optimal** : `min_idf >= 2.0` est le défaut actuel pour le signal gap. Faut-il un seuil différent pour le BM25 (`< 1.5` proposé) et pour les entités ? Faut-il rendre ces seuils configurables ?

2. **POS tagger — modèle multilingue vs per-language** : spaCy offre un modèle multilingue (`xx_sent_ud_sm`, 15MB) qui gère toutes les langues mais avec moins de précision, vs des modèles par langue (~15MB chacun, plus précis). Faut-il charger le modèle per-language en fonction de la détection fasttext ?

3. **Fallback sur corpus vide** : au tout premier import (corpus vide, pas d'IDF), la seule protection est le POS tagger + la petite liste résiduelle. Est-ce suffisant ?

4. **Entités multi-mots** : "use case", "data model", "access control" contiennent des mots qui seraient filtrés individuellement ("use", "data", "access"). Le filtre doit-il s'appliquer uniquement aux entités mono-mot ? Ou vérifier que **au moins un mot** du candidat multi-mots est "significatif" ?

5. **Coût spaCy en ingestion** : actuellement ~0.1ms/mot, mais sur une ingestion de 100 docs avec des milliers de candidats entités, le total peut monter à quelques secondes. Acceptable ?
