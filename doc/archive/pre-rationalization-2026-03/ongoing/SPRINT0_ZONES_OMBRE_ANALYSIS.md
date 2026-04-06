# Sprint 0 — Zones d'ombre identifiees par Codex (Octopus deep)

**Date** : 24 mars 2026
**Source** : Analyse multi-provider Claude + Codex via Octopus
**Statut** : En cours de validation — Test 1 v2 termine

---

## Zones d'ombre CRITIQUES

### Zone 1 : Le LLM ignore-t-il le bloc KG ?

C'est le point le plus fondamental et personne ne l'avait teste. Toute l'architecture Phase B reposait sur l'hypothese qu'un bloc de 50-100 tokens structure (entites, tensions) injecte dans le prompt va changer la qualite des reponses. Si le LLM l'ignore, tout le plan est de la decoration.

**Action Sprint 0** : Tester score(OSMOSIS avec bloc KG) vs score(OSMOSIS sans bloc KG) sur 50 questions. Si delta < 5%, revoir fondamentalement la strategie. Cout : 1 jour.

**RESULTAT TEST v1** (bloc KG = noms d'entites, 10 tokens moy) : delta < 1%. Le bloc KG n'avait aucun impact car il ne contenait que des noms d'entites deja presents dans les chunks.

**RESULTAT TEST v2** (bloc KG enrichi = SPO + tensions + QS, 144 tokens moy) : **Le bloc KG DEGRADE les resultats** — factual_correctness -8pp, false_idk +6.9pp, answer_relevant -5pp. Le seul gain est correct_source +4.9pp. Le bloc KG detourne le LLM des chunks pertinents.

### Zone 2 : Couplage search.py

2100 lignes, une seule fonction, variables d'etat accumulees. Ajouter un IntentResolver + 4 branches dedans sans refactoring prealable, c'est la garantie de regressions. Le plan mentionne le refactoring mais ne le chiffre pas comme prerequis bloquant.

**Action Sprint 0** : Cartographier le flux de search.py (variables, mutations, sorties) AVANT de toucher au code. Cout : 2 jours.

### Zone 3 : Scaling du bloc KG a 200+ documents

A 22 documents, un bloc de 50-100 tokens peut resumer le contexte KG pertinent. A 200 documents, c'est impossible sans selection — et cette selection EST du retrieval KG, ce qui contredit "le KG n'intervient pas dans le retrieval". C'est une dette architecturale qui bloquera la croissance.

**Decision utilisateur** : a prendre en compte des maintenant. Si on le trace dans un document, l'experience montre que le risque de l'oublier est fort. Si on l'implemente, meme si on n'a que 22 docs et que cela n'aura aucun impact, le jour ou l'on aura 200+ documents, cela sera deja en place. Design for scale, pas dette future.

---

## Zones d'ombre HAUTES

### Zone 4 : Le baseline RAG est lui-meme mediocre (41%)

On optimise contre un baseline faible. La question non posee : quel score un humain expert atteindrait-il sur ces questions ? Si un humain fait 45%, le benchmark est trop difficile. Si un humain fait 85%, le probleme est fondamental (embeddings, chunking, top_k). Codex suggere aussi de tester RAG avec top-10 et top-20 chunks — peut-etre que plus de contexte bat les deux systemes.

**Action Sprint 0** : Tester RAG avec top-3, top-5, top-10, top-20. Si top-20 RAG bat OSMOSIS, le probleme n'est pas le KG mais le contexte insuffisant. Cout : 0.5 jour.

### Zone 5 : Biais benchmark — questions IA vs questions reelles

Les questions humaines ont ete redigees par Claude et les questions KG generees depuis le KG. Les vrais utilisateurs posent des questions vagues, imprecises, avec du code-switching FR/EN. Le benchmark ne capture pas ca.

**Decision utilisateur** : plutot que de chercher de vrais utilisateurs, Claude est capable de simuler un utilisateur expert. Actions :
1. Ajouter des questions "vagues/imprecises" simulant un utilisateur non-expert ("comment on fait pour upgrader ?", "c'est quoi le truc Fiori la ?")
2. Ajouter des questions avec code-switching FR/EN ("Quels sont les prerequis pour le system conversion ?")
3. Ajouter 10-15 questions dont la reponse N'EXISTE PAS dans le corpus — le systeme DOIT dire qu'il ne sait pas. C'est le test d'hallucination.

### Zone 6 : CRAG (Corrective RAG) directement applicable au probleme des 35% de refus

CRAG (Yan et al., ICLR 2024) ajoute un evaluateur de confiance entre retrieval et generation. Si la confiance est basse, il declenche un fallback. Chez eux c'est le web — chez nous ce serait Neo4j. C'est exactement notre arbre de decision "scores Qdrant eleves -> prompt / scores bas -> retrieval", mais formalise et automatique.

**Impact sur le plan** : le Sprint 0 devrait integrer le test de confiance CRAG-like (calibrer le score Qdrant comme predicteur de qualite de reponse) au lieu de juste "analyser les scores". C'est la meme donnee mais avec un framework theorique solide.

**Decision utilisateur** : totalement en phase.

### Zone 7 : Adaptive-RAG = notre IntentResolver mais mieux fonde

Adaptive-RAG (Jeong et al., NAACL 2024 — https://github.com/starsuzi/Adaptive-RAG) fait exactement ce que notre IntentResolver fait — mais avec un petit classificateur ML entraine sur des labels auto-generes, pas du regex. L'etat de l'art utilise un classificateur, pas du pattern matching.

**Decision utilisateur** : l'usage de regex est generalement mauvais. Il faut penser cible et non etape transitoire de faible valeur. Si on implemente un resolver, autant le faire correctement des le depart avec un classificateur ML leger. Cout d'entrainement faible (500 exemples annotes automatiquement selon le paper).

---

## Zones d'ombre MOYENNES

### Zone 8 : KG2RAG chunk organization

KG2RAG (NAACL 2025 — https://github.com/nju-websoft/KG2RAG) propose de reorganiser les chunks avant de les envoyer au LLM selon la structure du KG (pas par score Qdrant). C'est compatible avec notre architecture et potentiellement plus impactant que le bloc KG separe. Au lieu d'un en-tete court, les chunks eux-memes sont ordonnes pour raconter une histoire coherente.

**A la lumiere du Test 1 v2** : cette approche devient potentiellement plus pertinente que le bloc KG separe, puisque le bloc separe degrade les resultats. Reorganiser les chunks (sans ajouter de contenu) pourrait etre la bonne approche.

### Zone 9 : ReDeEP insight pour le prompting

Les LLMs ignorent le contexte externe quand leur memoire parametrique a une "forte prior". Les claims OSMOSIS doivent etre presentees avec des marqueurs d'autorite : "Selon le document X, section Y : [claim]" pour forcer l'attention. Cout zero — modifier les templates.

### Zone 10 : Couverture ClaimClusters

49% des claims ne sont dans aucun cluster (apres reclustering avec embeddings corriges : 8543 orphelines sur 15861). Le clustering utilise un seuil cosine de 0.85 tres conservateur.

**Analyse realisee** : les orphelines sont des claims factuellement uniques dans leur document (pas de claim similaire). Le plan Type C (audit) doit combiner Entity->ABOUT (71% couverture) + ClaimClusters (46% couverture) pour la completude.

---

## Sprint 0 revise — 10 livrables

1. **Test contribution bloc KG** (1 jour) : FAIT — v1 delta < 1%, v2 degrade -8pp factual
2. **Audit search.py** (2 jours) : a faire
3. **Stratification des 35% de refus** (1 jour) : scores Qdrant + contenu chunks — a faire
4. **Test top_k RAG** (0.5 jour) : top-3/5/10/20 pour calibrer le baseline — a faire
5. **Ajouter false_answer_rate** (0.5 jour) : dans le juge + re-run — a faire
6. **Relancer clustering** (0.5 jour) : FAIT — 239 nouveaux clusters, 46.1% couverture
7. **Test IntentResolver** (0.5 jour) : sur 275 questions + taux ambiguite — a faire
8. **Verifier canonical_labels** (0.5 jour) : a faire
9. **Ajouter questions negatives** : 10-15 questions sans reponse dans le corpus — a faire
10. **Ajouter questions vagues** : 10-15 questions imprecises FR/EN — a faire

**Total : 6-7 jours. Livrables 1 et 6 FAITS.**

---

## Etat de l'art identifie (recherche Codex deep)

| Approche | Probleme A (35% IDK) | Probleme B (KG degrade simple) | Applicabilite OSMOSIS |
|----------|---------------------|-------------------------------|----------------------|
| CRAG | **Haute** — detection + fallback | Neutre | **Directe** : fallback Neo4j au lieu du web |
| Adaptive-RAG | Neutre | **Haute** — skip retrieval si inutile | **Directe** : pre-filtre upstream |
| KG2RAG | Moderee | Neutre | **Tres directe** : reorganiser chunks par structure KG |
| RAPTOR | Neutre | Partielle | Complementaire (resumes hierarchiques) |
| Self-RAG | Moderee | **Haute** | Necessite fine-tuning du LLM |
| HippoRAG 2 | Moderee | Neutre | PPR sur claims Neo4j |
| FVA-RAG | Indirecte (validation) | Neutre | Utile pour contradiction checking |
| ReDeEP | Insight prompting | Neutre | Cout zero — modifier templates |
