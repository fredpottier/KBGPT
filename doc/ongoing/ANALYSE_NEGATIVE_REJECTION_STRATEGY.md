# Analyse — Strategie de Negative Rejection pour OSMOSIS

**Date** : 1er avril 2026
**Statut** : Proposition a evaluer — demande d'analyse critique
**Contexte** : OSMOSIS obtient 10% sur les questions "unanswerable" (questions dont la reponse n'est pas dans le corpus). Le systeme hallucine au lieu de dire "je ne sais pas". Un premier fix par prompt tuning (regle d'honnetete) a monte le score a 40% mais a degrade les autres categories (-18pp sur false_premise, -13pp sur conditional). Le prompt tuning est fragile et LLM-dependant.

---

## 1. Le probleme

Quand un utilisateur pose une question dont la reponse n'existe pas dans le corpus documentaire, OSMOSIS doit idealement repondre : "Les documents disponibles ne contiennent pas d'information sur ce sujet." Au lieu de cela, il fabrique une reponse a partir de chunks vaguement lies au domaine.

**Exemple** :
- Question : "Quel est le cout de licence annuel de SAP S/4HANA ?"
- Le retriever trouve des chunks sur les fonctionnalites de S/4HANA (score embedding eleve car meme domaine)
- Le LLM recoit ces chunks et synthetise une reponse sur les fonctionnalites alors que la question portait sur les prix
- L'utilisateur recoit une reponse hors-sujet presentee comme factuelle

**Pourquoi le prompt tuning ne suffit pas** :
- Fragile : fonctionne avec Haiku mais pourrait echouer avec un autre LLM
- Trade-off destructeur : rendre le LLM plus prudent le rend aussi plus timide sur les questions ou il a l'information
- Non deterministe : la meme question peut obtenir des reponses differentes selon le run
- Non testable unitairement : impossible de valider le comportement sans lancer une requete complete

---

## 2. Proposition : Coverage Score pre-synthese (decision deterministe)

### Principe

Deplacer la decision "je sais / je ne sais pas" **avant** le LLM, dans le code, de maniere deterministe. Si le systeme determine que les chunks recuperes ne couvrent pas la question, il court-circuite le LLM et retourne directement un message d'ignorance honnete.

### Mecanisme propose

**Etape 1 — Extraction des concepts cles de la question**

A partir de la question utilisateur, extraire les termes specifiques qui definissent le "sujet reel" de la question. Pas les termes generiques (SAP, S/4HANA, systeme) mais les termes discriminants.

Exemple :
- "Quel est le cout de licence annuel ?" → concepts cles : ["cout", "licence", "prix", "tarif", "annual"]
- "Combien de clients utilisent S/4HANA ?" → concepts cles : ["combien", "clients", "nombre", "utilisateurs", "adoption"]
- "Comment configurer l'integration avec Salesforce ?" → concepts cles : ["Salesforce", "integration", "configurer"]

Methodes possibles (sans LLM) :
- Extraction de mots specifiques : mots non-stopwords absents du vocabulaire technique general du corpus
- TF-IDF inverse : mots rares par rapport au corpus (un mot present dans 1% des chunks est plus discriminant qu'un mot present dans 80%)
- Pattern matching : detecter les noms propres de produits externes, les termes financiers, les demandes de metriques

**Etape 2 — Verification de la couverture dans les chunks**

Pour chaque concept cle extrait, verifier sa presence lexicale dans les chunks recuperes. Pas juste la similarite embedding (qui capture le domaine global) mais la presence reelle du terme ou d'un synonyme proche.

Score de couverture = proportion des concepts cles trouves dans au moins un chunk.

**Etape 3 — Decision**

- Si coverage >= 0.5 (au moins la moitie des concepts cles trouves) → passer au LLM normalement
- Si coverage < 0.5 et score embedding max > seuil → passer au LLM avec un flag "partial_coverage" (le LLM est informe que la couverture est partielle)
- Si coverage < 0.3 ET score embedding max < seuil → court-circuiter le LLM, retourner un message d'ignorance

Le message d'ignorance est construit de maniere deterministe :
"Les documents disponibles ne contiennent pas d'information sur [concepts non trouves]. Le corpus couvre principalement [themes des chunks les plus proches]."

### Avantages

1. **Deterministe** : meme question = meme decision, testable unitairement
2. **LLM-agnostique** : ne depend d'aucun prompt, fonctionne avec n'importe quel LLM
3. **Pas de trade-off** : le LLM n'est pas surcharge de regles de prudence, il repond normalement quand on lui donne les chunks. La decision est prise avant lui.
4. **Explicable** : on peut montrer a l'utilisateur pourquoi le systeme a refuse (concepts non trouves)
5. **Pas de regression** : les questions ou les chunks sont pertinents passent au LLM sans modification

---

## 3. Risques et limites de cette approche

### Risque 1 — Faux negatifs (le systeme refuse a tort)

**Scenario** : La question utilise un terme que le corpus ne mentionne pas explicitement mais dont la reponse est presente sous un autre terme.

Exemple : L'utilisateur demande "Qu'est-ce que le MFA dans SAP ?" mais le corpus parle de "multi-factor authentication" sans jamais utiliser l'acronyme "MFA". Les concepts cles extraits ("MFA") ne matchent aucun chunk → le systeme refuse alors que la reponse existe.

**Gravite** : Elevee. Un faux refus est frustrant pour l'utilisateur et mine la confiance dans le systeme.

**Attenuation** :
- Utiliser une expansion de synonymes/acronymes (mais cela devient vite domain-specific, ce qui viole INV-6)
- Combiner la verification lexicale avec un seuil de similarite embedding : si l'embedding est tres eleve (> 0.85) meme sans match lexical, laisser passer
- Garder le seuil de refus assez bas (coverage < 0.3 ET embedding < seuil) pour minimiser les faux negatifs

### Risque 2 — Faux positifs (le systeme laisse passer a tort)

**Scenario** : La question contient des termes presents dans le corpus mais dans un contexte different.

Exemple : "Quel est le prix de SAP HANA ?" — le terme "SAP HANA" est partout dans le corpus (coverage elevee) mais aucun chunk ne parle de prix. Le systeme laisse passer, et le LLM hallucine un prix.

**Gravite** : Moyenne. C'est le meme probleme qu'aujourd'hui — le coverage score ne l'aggrave pas mais ne le resout pas non plus pour ce cas.

**Attenuation** :
- L'extraction de concepts cles doit isoler le "sujet reel" ("prix") des termes contextuels ("SAP HANA")
- Un bon extracteur distinguerait que "prix de SAP HANA" a comme concept cle "prix", pas "SAP HANA"
- Mais cette extraction est elle-meme un probleme non trivial

### Risque 3 — Deporter la responsabilite au KG/retriever

**Scenario** : Le KG ou le retriever a un bug, un index manquant, ou des entites mal canonicalisees. Les concepts cles ne sont pas trouves non pas parce que l'information n'est pas dans le corpus, mais parce que le systeme n'arrive pas a la retrouver.

Exemple : L'utilisateur demande "Quel objet d'autorisation controle SAP Credit Management ?" — l'information existe (F_UKM_SGMT) mais le chunk pertinent n'a pas ete recupere a cause d'un probleme de retrieval. Le coverage score est bas → le systeme refuse a tort.

**Gravite** : Elevee. Le systeme masque ses propres defaillances de retrieval derriere un "je ne sais pas" poli.

**Attenuation** :
- Ne jamais utiliser le coverage score comme seul critere. Toujours combiner avec le score embedding
- Si l'embedding est eleve (le retriever a trouve des chunks proches) mais le coverage lexical est bas, c'est un signal ambigu → dans le doute, laisser passer au LLM
- Logger les cas de refus pour audit (permet de detecter les problemes de retrieval)

### Risque 4 — Extraction de concepts cles est elle-meme un probleme difficile

**Scenario** : Comment extraire les "concepts cles discriminants" sans LLM et de maniere domain-agnostic ?

Exemples problematiques :
- "Comment SAP gere-t-il les tests de penetration ?" → concept cle = "tests de penetration" (compose, pas un seul mot)
- "Quelle est la solution analytics qui combine BI et Planning ?" → concepts cles = "analytics", "BI", "Planning" (termes generiques qui matchent beaucoup de chunks)
- "Quels sont les salaires des consultants ?" → concept cle = "salaires" (facile)

L'extraction de concepts cles sans LLM et domain-agnostic est faisable pour les cas simples (noms propres, termes financiers, metriques) mais difficile pour les cas subtils.

**Attenuation** :
- Approche hybride : extraction de base par regles (TF-IDF, patterns) + LLM leger en fallback pour les cas ambigus
- Commencer avec une approche simple (extraction lexicale) et mesurer les faux negatifs
- Accepter que cette couche ne soit pas parfaite mais meilleure que le prompt tuning

### Risque 5 — Complexite architecturale

Le coverage score ajoute une couche de decision entre le retriever et le LLM. Cela signifie :
- Un nouveau composant a maintenir et tester
- Des seuils a calibrer (0.3, 0.5, etc.) qui dependent potentiellement du corpus
- Une interaction complexe avec les autres mecanismes (signal detector, contradiction envelope, KG findings)

---

## 4. Alternatives au coverage score

### Alternative A — Post-validation (au lieu de pre-filtrage)

Au lieu de decider avant le LLM, on laisse le LLM repondre puis on verifie apres :
- Extraire les affirmations cles de la reponse
- Verifier que chaque affirmation est tracable dans les chunks
- Si trop d'affirmations ne sont pas tracables → remplacer la reponse par un message d'ignorance

**Avantage** : Le LLM n'est pas contraint, pas de faux refus
**Inconvenient** : Double cout LLM (synthese + validation), plus lent, la validation est elle-meme un probleme LLM-dependant

### Alternative B — Confidence score du LLM

Demander au LLM d'auto-evaluer sa confiance dans sa reponse (0-100%). Si < seuil → message d'ignorance.

**Avantage** : Simple a implementer
**Inconvenient** : Les LLM sont notoirement mauvais pour estimer leur propre confiance (overconfidence systematique). Non fiable.

### Alternative C — Dual-check (retriever + KG)

Verifier la couverture a la fois dans les chunks Qdrant ET dans le KG Neo4j. Si la question porte sur un sujet qui n'a aucune entite dans le KG et aucun chunk pertinent → refus.

**Avantage** : Deux sources independantes reduisent les faux negatifs
**Inconvenient** : Le KG ne couvre pas forcement tous les sujets du corpus (entites manquantes, claims non extraites)

### Alternative D — Approche hybride (recommandee)

Combiner le coverage score pre-synthese avec un prompt LLM allege :
1. Coverage score deterministe pour les cas clairs (hors-sujet evident : prix, salaires, stats...)
2. Prompt LLM standard (sans regle 12 agressive) pour les cas ambigus
3. Le LLM garde sa capacite naturelle a dire "je ne sais pas" sans etre force/empeche

Le coverage score ne gere que les 20% de cas evidents. Les 80% restants sont laisses au LLM avec un prompt equilibre.

---

## 5. Etat actuel et mesures

| Version | Prompt | unanswerable | false_premise | conditional | global |
|---|---|---|---|---|---|
| V2 (baseline) | Regle 7 "never refuse" | **10%** | 61% | 40% | 55.5% |
| V3 (honesty) | Regle 7+12 "honesty + out-of-scope" | **40.5%** | 43% | 27% | 53.9% |
| Cible | Coverage score + prompt equilibre | **60%+** | 60%+ | 40%+ | 60%+ |

Le V3 montre que le prompt peut pousser unanswerable a 40% mais au prix d'une degradation severe des autres categories. Une approche structurelle (coverage score) devrait permettre d'atteindre 60%+ sans degrader les autres.

---

## 6. Questions ouvertes pour analyse

1. Le coverage score pre-synthese est-il la bonne approche ou faut-il privilegier la post-validation ?
2. Comment extraire les concepts cles discriminants de maniere domain-agnostic et sans LLM ?
3. Le risque de masquer les defaillances de retrieval (risque 3) est-il acceptable ?
4. Existe-t-il des papiers academiques sur ce sujet specifique (pre-filtrage des questions hors-scope dans les systemes RAG) ?
5. L'approche hybride (D) est-elle la plus equilibree ou cree-t-elle trop de complexite ?

---

---

## 7. Resultats d'implementation — Question-Context Gap Signal

### Ce qui a ete implemente (1er avril 2026)

Un signal `question_context_gap` a ete ajoute dans l'architecture signal-driven :
- **IDF corpus-aware** : index de frequence calcule sur 2000 chunks Qdrant (14091 termes)
- **Extraction de termes specifiques** : les termes dont l'IDF > 2.0 sont consideres "specifiques" a la question
- **Gap score** : proportion des termes specifiques absents des chunks + claims KG
- **Decision** : gap=1.0 + pas d'exactness → UNANSWERABLE (hard reject, court-circuit LLM)
- **Soft signal** : gap >= 0.6 → note pour le LLM ("certains aspects ne sont peut-etre pas couverts")

### Resultats du benchmark V4

| Categorie | V2 (baseline) | V4 (gap signal) | Delta |
|---|---|---|---|
| **unanswerable** | 10% | **63.8%** | **+53.8pp** |
| negation | 82.6% | 53.2% | **-29.4pp** |
| multi_hop | 76.7% | 10.0% | **-66.7pp** |
| false_premise | 60.6% | 21.6% | **-39pp** |
| synthesis_large | 67.7% | 33.0% | **-34.7pp** |
| GLOBAL | 55.5% | 42.0% | **-13.5pp** |

### Diagnostic : le cross-lingue tue le signal

**Cause racine** : Le gap lexical ne traverse pas la barriere de langue. Avec un corpus en anglais et des questions en francais :
- "processus" (FR) ne matche pas "processes" (EN) → considere comme absent → gap artificiel
- "supportes" (FR) ne matche pas "supported" (EN) → idem
- "bloquer" (FR) ne matche pas "blocked" (EN) → idem

Resultat : le hard reject se declenche sur des questions legitimement answerable, detruisant les scores des autres categories.

### Decision : hard reject DESACTIVE, soft signal conserve

Le hard reject est desactive dans `signal_policy.py` (commente avec TODO). Le soft signal (gap >= 0.6 → note au LLM) est conserve car il n'a pas d'impact negatif.

Le code complet (IDF index, extraction termes, gap score, court-circuit search.py) est en place et pret a etre reactive quand le cross-lingue sera resolu.

### Piste pour resoudre le cross-lingue

Le probleme est que l'IDF est calcule sur les tokens bruts. Pour supporter le multilingue, il faudrait l'une de ces approches :

1. **Embeddings de termes** au lieu de matching lexical : comparer l'embedding du terme de la question avec les embeddings des termes des chunks. "cout" serait proche de "cost" en espace embedding. Mais cela ajoute un cout de calcul significatif.

2. **Dictionnaire de lemmes multilingue** : utiliser un mapping FR→EN, DE→EN, etc. Mais c'est du maintien de dictionnaire et potentiellement domain-specific.

3. **IDF sur embeddings de chunks** : au lieu de calculer l'IDF sur les tokens, le calculer sur les embeddings. Si l'embedding de la question est loin de tous les chunks (faible similarite dense max), c'est un signal d'absence. Mais c'est essentiellement ce que le retriever fait deja.

4. **Cross-lingual NER** : utiliser un modele NER multilingue (ex: xlm-roberta) pour extraire les entites dans la question ET les chunks, puis comparer les entites. Plus robuste que le lexical mais necessite un modele supplementaire.

5. **Approche la plus simple** : ne pas utiliser le gap lexical du tout. Plutot, utiliser le **score dense max du retriever** comme proxy de repondabilite. Si le meilleur chunk a un score dense < 0.3, c'est un signal fort d'absence. Mais les scores RRF actuels (~0.028) ne sont pas exploitables — il faudrait acceder au score dense brut avant fusion RRF.

**Recommandation** : L'option 5 (score dense) a ete testee et s'avere insuffisante (voir section 8).

---

## 8. Resultats V5 — Signal dense pre-RRF

Le score dense brut a ete expose dans le retriever et teste. Resultat :
- "cout de licence" (UNANSWERABLE) → dense max = 0.786
- "autorisation Credit Management" (ANSWERABLE) → dense max = 0.826

**Ecart = 0.04 points → indiscernable.** Le bi-encoder (e5-large) capture la proximite thematique ("SAP"), pas la repondabilite. Toute question mentionnant SAP a un score dense > 0.75 dans un corpus SAP.

### Conclusion des 4 approches testees

| Approche | unanswerable | Faux positifs | Viable ? |
|---|---|---|---|
| V2 baseline (prompt "never refuse") | 10% | 0 | ❌ hallucine |
| V3 prompt "honesty rule + rule 12" | 40.5% | Massifs (-18pp) | ❌ trade-off |
| V4 gap lexical IDF | 63.8% | Massifs (-67pp) | ❌ cross-lingue |
| V5 dense score pre-RRF | ~10% | 0 | ❌ ne discrimine pas |

**Toutes les approximations (lexicales, embedding, prompt) echouent.**

---

## 9. Direction finale — QA-Class (Question-Answerability Classifier)

### Diagnostic (consensus Claude + ChatGPT)

Le probleme n'est pas le retrieval (les chunks sont trouves) ni la synthese (le LLM est capable).
Le probleme est **la decision : "ce chunk permet-il de repondre a cette question ?"**

Aucun proxy (mots, embeddings, scores) ne capture cette decision.
Il faut l'evaluer **directement**.

### Architecture cible

```
retrieve → rerank → top_k_chunks
                        ↓
              QA-Class (Qwen/vLLM)    ← NOUVEAU
                        ↓
            signal: answerability_score
                        ↓
              signal_policy
                        ↓
              LLM synthese (ou refus)
```

### Principe

Pour les top-3 chunks, poser a un LLM leger la question :
"Ce chunk contient-il assez d'information pour repondre a la question ? YES / PARTIAL / NO"

Si 3/3 = NO → UNANSWERABLE (hard reject deterministe)
Si au moins 1 YES → ANSWERABLE (pipeline normal)
Si PARTIAL seulement → UNCERTAIN (soft signal)

### Pourquoi Qwen/vLLM (pas Haiku)

- **Gratuit** : vLLM tourne sur l'EC2 burst deja provisionnee
- **Rapide** : ~100ms par appel, 3 appels = 300ms
- **Pas de dependance API externe** pour une decision critique
- **Qwen 14B** est largement capable de classification YES/NO avec contexte
- Compatible avec la philosophie "pas de cout LLM pour la decision, LLM seulement pour la synthese"

### Prerequis

- EC2 burst avec vLLM doit etre accessible
- Fallback si vLLM non disponible : passer au LLM sans QA-Class (comportement actuel)
- A integrer comme signal dans `detect_signals()` / `signal_policy()`

### Impact attendu

- unanswerable : 10% → 60-80%
- Sans degradation des autres categories (le QA-Class est semantique, pas lexical)
- Multilingue natif (Qwen comprend FR, EN, DE, etc.)
- Domain-agnostic (la question "ce chunk repond-il ?" ne depend d'aucun domaine)

### Statut

Decision validee, implementation reportee a la prochaine session avec EC2 burst disponible.

---

*Document mis a jour le 1er avril 2026. Historique complet : V2 → V3 → V4 → V5 → decision QA-Class.*
