# Sprint 2 — Diagnostic IntentResolver : la classification par prototypes est cassee

**Date** : 25 mars 2026
**Contexte** : Sprint 1 termine (6/6 livrables), validation go/no-go OK, debut Sprint 2
**Objectif de ce document** : Presenter la situation, les decouvertes et les options pour obtenir un consensus multi-IA

---

## 1. Rappel de l'architecture mise en place (Sprint 1)

### Le probleme de depart (Sprint 0)
OSMOSIS combine un Knowledge Graph (Neo4j : 15861 claims, 7059 entites, 2620 clusters, 252 tensions cross-doc) avec un vector store (Qdrant : ~15000 chunks). Le Sprint 0 a revele que :
- Injecter le KG dans le prompt LLM **degrade** les reponses (-8pp factual)
- Le KG est un game-changer pour les contradictions (100% vs RAG 0%) et la completude (+19pp)
- Le KG **perturbe** les questions simples : +8pp irrelevant, +20pp partial hallucination
- Le taux de refus (false_idk 33%) est **100% un probleme de prompt** (pas de retrieval)

### La solution concue : IntentResolver 2-passes + KG2RAG

Architecture validee par consensus Claude Code + Claude Web (analyse latence et reclassification post-retrieval) :

**Passe 1 — Classification linguistique pre-retrieval (< 5ms)**
- 27 prototypes embeddes repartis en 4 types (A/B/C/D)
- Cosine similarity entre l'embedding de la question et les prototypes
- Domain-agnostic : les prototypes sont des structures linguistiques generiques
- Defaut = Type A si confiance < 0.35

**Retrieval Qdrant** : identique pour tous les types (top_k=10)

**Passe 2 — Reclassification post-retrieval par signal KG**
- Regles deterministes sur les chunks recuperes
- Tensions detectees (2+ docs) → upgrade Type B
- 4+ documents distincts → upgrade Type C
- QD match exact → upgrade Type D
- Multi-version → upgrade Type B
- KG vide → tout reste Type A (degradation gracieuse)

**Execution par type** :
- **Type A** (defaut, ~70%) : chunks RAG bruts, ZERO KG, hard constraint non-regression
- **Type B** (~5%) : chunks reorganises en adjacence contradictoire
- **Type C** (~20%) : diversification round-robin par document, top_k elargi a 20
- **Type D** (<5%) : QD-first (chunk QuestionDimension en tete)

### Les prototypes utilises

```python
PROTOTYPES = {
    "A": [  # 7 prototypes
        "What is X?",
        "How does X work?",
        "Explain X",
        "What are the prerequisites for X?",
        "Comment fonctionne X ?",
        "Qu'est-ce que X ?",
        "Quels sont les prerequis pour X ?",
    ],
    "B": [  # 7 prototypes
        "What is the difference between X and Y?",
        "Compare X and Y",
        "How has X changed between version 1 and version 2?",
        "Are there contradictions between X and Y?",
        "Quelle est la difference entre X et Y ?",
        "X versus Y",
        "Les documents se contredisent-ils sur X ?",
    ],
    "C": [  # 7 prototypes
        "Give me a complete summary of X across all documents",
        "What do all documents say about X?",
        "Audit X",
        "List everything about X",
        "Fais un resume complet de X",
        "Que disent tous les documents sur X ?",
        "Fais un audit de X",
    ],
    "D": [  # 6 prototypes
        "What is the exact value of X?",
        "What is the minimum threshold for X?",
        "What is the maximum limit of X?",
        "Quel est le seuil exact de X ?",
        "Quelle est la valeur de X ?",
        "Quel est le nombre maximum de X ?",
    ],
}
```

### Motivation de cette approche
- **Domain-agnostic** : les prototypes sont des structures linguistiques, pas du contenu domaine
- **Zero training** : pas besoin de donnees annotees, fonctionne avec un KG vide
- **< 5ms** : dot product sur 27 vecteurs pre-calcules
- **Degradation gracieuse** : KG vide → tout reste Type A → comportement RAG pur

---

## 2. Resultats du Sprint 1

### Benchmark validation go/no-go (100 questions T1 human + 25 T2 KG + 20 T4 KG)

| Critere | Baseline (Sprint 0) | Sprint 1 | Delta | Verdict |
|---------|---------------------|----------|-------|---------|
| T1 factual | 0.360 | **0.348** | -1.2pp | GO (< 5pp) |
| T1 false_answer | 22.0% | **18.0%** | -4pp | Amelioration |
| T1 false_idk | 37.5% | **38.3%** | +0.8pp | Stable |
| T1 irrelevant | 22.0% | **25.0%** | +3pp | Stable |
| T2 both_sides | 100% | **100%** | 0 | GO |
| T2 tension_mentioned | 100% | **100%** | 0 | GO |
| T4 completeness | 67.8% | **62.5%** | -5.3pp | Limite |
| T1 zero regression | — | **0 regressions** | — | GO |

**Verdict** : GO CONDITIONNEL — zero regression significative, false_answer en baisse.

### Note importante sur le benchmark
Le benchmark runner (`run_osmosis.py`) utilise son propre prompt de synthese via vLLM direct. Il NE passe PAS par l'API OSMOSIS et donc NE declenche PAS l'IntentResolver ni le chunk_organizer. Les resultats du benchmark mesurent le retrieval + synthese standardisee, pas le pipeline complet avec routing.

---

## 3. Le diagnostic qui change tout (Livrable 2.0)

### Methode
Ventilation des 100 questions T1 human par type d'intent, en utilisant les memes prototypes que l'IntentResolver de production. Chaque question est embeddee via TEI (multilingual-e5-large) et classee par cosine similarity max avec les prototypes.

### Resultats

| Type | Questions | Correct | False IDK | False Answer | Irrelevant |
|------|-----------|---------|-----------|-------------|------------|
| **A** (factuel simple) | **25** (25%) | 20% | **44%** | 8% | 28% |
| **B** (comparatif) | **0** (0%) | — | — | — | — |
| **C** (audit/completude) | **75** (75%) | 21% | **33%** | 21% | 24% |
| **D** (comparable) | **0** (0%) | — | — | — | — |
| **Total** | 100 | 21% | 36% | 18% | 25% |

### Le probleme : 75% des questions sont mal classees

Les 100 questions T1 human sont des questions **factuelles simples** (Type A). Exemples :
- "Quel objet d'autorisation protege l'import de la Simplification Database ?" → classe **Type C**
- "Quelle SAP Note faut-il consulter pour telecharger la Simplification Database ?" → classe **Type C**
- "Quel role SAP est fourni pour le team lead dans le Payroll Control Center ?" → classe **Type C**
- "Quelle transaction est utilisee pour le monitoring MRP dans S/4HANA ?" → classe **Type C**

Ces questions **devraient toutes etre Type A** (factuel direct, reponse dans un seul chunk).

### Pourquoi ca arrive

Le modele d'embedding (multilingual-e5-large) capture la **semantique du sujet** plus que la **structure interrogative**. Quand une question mentionne un sujet specifique et technique ("objet d'autorisation", "SAP Note", "transaction"), l'embedding est plus proche de "What do all documents say about [sujet technique]" (prototype C) que de "What is X?" (prototype A) — parce que X dans le prototype A est trop generique.

Dit autrement : les prototypes A sont **trop vagues** ("What is X?") et les prototypes C sont **trop attracteurs** ("What do all documents say about X?"). L'embedding model ne distingue pas la structure syntaxique ("quel est" = question simple) du contenu semantique ("objet d'autorisation SAP" = sujet complexe).

---

## 4. Implications en cascade

### 4.1 Le hard constraint Type A est contourne

Le chunk_organizer est cense ne RIEN modifier pour Type A (hard constraint invariant RAG). Mais si 75% des questions sont mal classees en Type C, le chunk_organizer applique la strategie `cluster_coverage` (round-robin par document) au lieu de `raw`. Cela signifie :
- Les chunks sont **reorganises** alors qu'ils ne devraient pas l'etre
- L'invariant "Type A = memes chunks que RAG" est **casse en pratique** pour 75% des questions
- Une partie de l'irrelevant +8pp vs RAG pourrait venir de cette reorganisation inappropriee

### 4.2 Le prompt-per-type prevu en Sprint 2 aggraverait le probleme

Si on implemente des prompts differencies (plan Sprint 2 livrable 2.2) :
- Type A recevrait : "Synthesize, cite, answer partially if needed"
- Type C recevrait : "Couvre TOUS les documents. Structure par theme. Signale les trous."

Envoyer le prompt Type C a une question factuelle simple ("Quel objet d'autorisation...?") encouragerait le LLM a broder, augmenter le false_answer, et donner des reponses inutilement longues. Le false_answer de 21% deja observe sur les questions classees Type C pourrait etre un symptome de ce phenomene.

### 4.3 Le benchmark ne capture pas le probleme

Le benchmark runner court-circuite l'IntentResolver (il passe directement par vLLM). Les scores du benchmark sont donc **optimistes** pour la production : en production, 75% des questions sont mal routees, ce qui degrade la qualite de maniere invisible dans les metriques.

### 4.4 Le diagnostic par type est biaise

Les chiffres "false_idk Type A = 44%, false_idk Type C = 33%" ne sont pas des mesures de performance par type — ce sont des mesures sur des questions **mal classees**. Les 25 questions classees Type A sont probablement les plus generiques (d'ou le match avec "What is X"), et les 75 classees Type C sont plus specifiques. Le vrai false_idk sur les questions simples est probablement entre 33-44%, pas strictement 44%.

---

## 5. Options envisagees

### Option A : Corriger les prototypes

Ajouter des prototypes Type A plus specifiques et techniques :
- "Quel est le nom de X ?", "Quelle SAP Note pour X ?", "Quel objet d'autorisation pour X ?"
- "Quelle transaction pour X ?", "Quel role pour X ?", "Quel parametre pour X ?"

Et rendre les prototypes C plus restrictifs (exiger "tous", "complet", "resume", "audit").

**Avantage** : Correction rapide (~0.5j), preserve l'architecture existante.
**Probleme** : On retombe dans du **regex deguise** — les prototypes deviennent des patterns lexicaux embeddes, pas des structures linguistiques generiques. Et c'est specifique au domaine SAP (on ajouterait "SAP Note" dans les prototypes = violation de l'agnosticite domaine).

### Option B : Abandonner la Passe 1, tout defaut Type A, Passe 2 seulement

- Supprimer la classification linguistique pre-retrieval
- Toutes les questions sont Type A par defaut
- La Passe 2 (post-retrieval, signal KG) upgrade si le KG revele de la complexite

**Avantage** : Garantit le hard constraint Type A a 100%. Simple. Pas de risque de mal-classification.
**Probleme** : On perd la detection des vrais Type C ("Fais un audit complet de la securite") qui n'ont pas necessairement de signal KG (pas de tensions, juste une demande d'exhaustivite). La Passe 2 n'a aucun moyen de detecter "l'utilisateur veut un audit" sans signal linguistique.

### Option C : Classificateur LLM leger (~100ms)

Un appel rapide a Qwen 14B via vLLM :
```
"Classifie cette question en une lettre :
A = question factuelle simple (reponse dans un seul passage)
B = comparaison ou difference entre documents/versions
C = demande d'audit, resume complet, ou analyse exhaustive
D = valeur exacte, seuil, chiffre precis

Question : {question}
Type :"
```
~50 tokens in, ~5 tokens out, ~100ms sur vLLM.

**Avantage** : Robuste, domain-agnostic (le LLM comprend l'intention, pas juste la proximite d'embedding). Pas de prototypes a maintenir.
**Probleme** : Ajoute 100ms + un appel LLM dans le chemin critique. Dependance au vLLM pour le routing (si vLLM est down, pas de classification). Et c'est une solution transitoire qui utilise un LLM pour une tache de classification — l'inverse du "pas de MVP transitoire".

### Option D : Hybride — Passe 1 simplifiee + Passe 2 renforcee

La Passe 1 devient un **detecteur de marqueurs explicites** (pas des prototypes embeddes) :
- Si la question contient "compare", "difference", "versus", "contradictions" → Type B
- Si la question contient "tous les documents", "resume complet", "audit", "exhaustif" → Type C
- Si la question contient "valeur exacte", "seuil", "combien exactement" → Type D
- **Sinon** → Type A (defaut)

Puis la Passe 2 KG upgrade comme aujourd'hui.

**Avantage** : Pas de faux positifs (seuls les marqueurs explicites declenchent un type non-A). Simple. Deterministe.
**Probleme** : Ca ressemble a du regex. Mais contrairement aux prototypes embeddes, les marqueurs sont **linguistiques et domain-agnostic** ("compare", "tous les documents" fonctionnent en francais, anglais, biomedical ou SAP).

### Option E : Pas de Passe 1 du tout, Passe 2 enrichie avec signal linguistique

Toutes les questions sont Type A par defaut. La Passe 2 est enrichie pour capter aussi les signaux linguistiques :
- Apres le retrieval, analyser la question + les chunks pour detecter :
  - La question demande une comparaison ? (NLI sur paire question/chunks)
  - Les chunks proviennent de 4+ documents ? → Type C
  - Les chunks contiennent des tensions KG ? → Type B
  - Un QD match exact ? → Type D

**Avantage** : Un seul point de decision (post-retrieval), pas de pre-classification fragile.
**Probleme** : Le signal linguistique ("Fais un audit complet") n'est pas disponible dans les chunks — il est dans la question. Et le NLI ajouterait de la latence.

---

## 6. Donnees supplementaires pour l'analyse

### Test de classification sur 6 questions representatives (fait en Sprint 1)

| Question | Passe 1 | Correct ? |
|----------|---------|-----------|
| "What is SAP Fiori?" | A (0.755) | Oui |
| "Compare S/4HANA 2022 and 2023" | B (0.813) | Oui |
| "Give me a complete summary of security" | C (0.893) | Oui |
| "What is the exact threshold for X?" | D (0.960) | Oui |
| "comment on fait pour upgrader ?" | A (0.839) | Oui |
| "Quelles sont les nouvelles fonctionnalites de la version 2023 ?" | C (0.817) | Discutable (A ou C) |

Les prototypes fonctionnent bien sur des questions **generiques**. Ils echouent sur des questions **techniques specifiques** qui n'ont pas de marqueur syntaxique explicite.

### Distribution attendue vs observee

| Type | Attendu (questions T1 human) | Observe | Ecart |
|------|------------------------------|---------|-------|
| A | ~85-90% | **25%** | -60pp |
| B | ~5% | **0%** | -5pp |
| C | ~5-10% | **75%** | +65pp |
| D | ~0-2% | **0%** | 0 |

### Contraintes a respecter

1. **Agnosticite domaine** — zero code specifique a un domaine (SAP, biomedical)
2. **Pas de solution transitoire/MVP** — implementer la cible directement
3. **< 100ms de latence pour la classification** — ne pas degrader l'experience utilisateur
4. **Degradation gracieuse** — KG vide = tout Type A = RAG pur
5. **Hard constraint Type A** — les questions simples ne doivent JAMAIS etre modifiees par le KG

---

## 7. Questions pour l'analyse externe

1. **L'approche par prototypes embeddes est-elle fondamentalement viable** ou est-ce que la semantique de l'embedding model rend cette approche structurellement inadaptee pour la classification d'intent ?

2. **L'Option B (tout defaut Type A, Passe 2 seulement) est-elle suffisante ?** La perte de detection des vrais Type C linguistiques est-elle acceptable si la Passe 2 compense via les signaux KG ?

3. **L'Option C (LLM classifier) viole-t-elle le principe "pas de MVP transitoire" ?** Ou est-ce la cible definitive d'un classificateur domain-agnostic robuste ?

4. **L'Option D (marqueurs explicites) est-elle du regex deguise** ou est-ce une approche valide et maintenable pour les marqueurs linguistiques universels ?

5. **Quel est le vrai impact de la mauvaise classification en production ?** Si le benchmark ne passe pas par l'IntentResolver, est-ce que le probleme est visible pour les utilisateurs du chat ?

6. **Faut-il revoir l'architecture 2-passes** ou seulement corriger la Passe 1 ?
