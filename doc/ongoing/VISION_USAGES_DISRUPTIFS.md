# Vision : Usages disruptifs OSMOSIS — Au-delà du RAG

*Date : 13 avril 2026*
*Contexte : le système fonctionne (benchmarks OK) mais la valeur perçue reste celle d'un "bon RAG". Il faut des usages que seul OSMOSIS peut offrir grâce à son KG.*

## Constat

OSMOSIS aujourd'hui = un RAG augmenté par un Knowledge Graph. Les benchmarks montrent que c'est meilleur qu'un RAG pur (+2-5 pts faithfulness, détection de tensions). Mais un client ne paie pas pour +5 pts de faithfulness. Il paie pour des **capacités impossibles autrement**.

## Les 5 usages disruptifs identifiés

### 1. Queryable Truth Layer — "Montre-moi TOUT"

**Le problème** : un RAG classique donne une réponse synthétisée à partir de 5-10 chunks. Mais un juriste, un auditeur, un compliance officer a besoin de **tout** ce que dit le corpus sur un sujet. Pas une synthèse, pas un top-5 — **l'exhaustivité**.

**Ce qu'OSMOSIS peut faire** : le KG contient TOUTES les claims sur un sujet, pas juste les plus proches en cosine similarity. Une couche "Natural Language → Cypher" permet de garantir l'exhaustivité :

```
"Tout ce que disent les documents sur les amendes de l'AI Act"
→ MATCH (c:Claim)-[:ABOUT]->(e:Entity {name: 'administrative fines'})
  WHERE c.doc_id CONTAINS 'AI_Act'
→ 47 claims exhaustives, pas 5 chunks
```

**Valeur client** : "Avec OSMOSIS, rien ne passe entre les mailles. Chaque affirmation du corpus est identifiée, tracée et vérifiable."

**Différenciateur vs RAG/Copilot** : un RAG ne peut pas garantir l'exhaustivité (le retrieval est top-k). OSMOSIS le peut car les claims sont structurées dans le KG.

**Implémentation** :
- Natural Language → Cypher via LLM (le LLM connaît le schéma du KG)
- Résultats affichés comme liste structurée (pas de synthèse LLM, les claims brutes)
- Mode "Evidence Pack" : export PDF/Excel des claims avec sources

---

### 2. Détection proactive — "Le système vous alerte"

**Le problème** : dans un RAG, le système attend qu'on lui pose une question. Si personne ne demande "Y a-t-il des contradictions entre notre politique interne et le nouveau règlement ?", la contradiction passe inaperçue.

**Ce qu'OSMOSIS peut faire** : le KG détecte les contradictions, les évolutions, les tensions **automatiquement** lors de l'import. Ces signaux peuvent déclencher des **alertes proactives** :

- "3 nouvelles contradictions détectées entre vos documents internes et l'AI Act"
- "Le document importé hier contredit 2 claims de votre politique de protection des données"
- "5 exigences de l'AI Act ne sont couvertes par aucun de vos documents internes"

**Valeur client** : "OSMOSIS ne répond pas seulement — il surveille votre corpus et vous prévient quand quelque chose ne colle pas."

**Différenciateur vs RAG/Copilot** : aucun RAG ne fait de détection proactive. C'est un paradigme fondamentalement différent — le système est un **observateur actif**, pas un répondeur passif.

**Implémentation** :
- Post-import : comparer les nouvelles claims avec les existantes → détecter les nouvelles contradictions/évolutions
- Dashboard d'alertes dans le cockpit (déjà partiellement implémenté via les tensions)
- Notifications par email/webhook quand un seuil est dépassé
- Les relations CONTRADICTS, REFINES, EVOLVES_TO sont la matière première

---

### 3. Comparaison structurée — "Tableau de bord comparatif"

**Le problème** : demander à un RAG "Compare le RGPD et la CCPA" donne un pavé de texte. Un décideur veut un **tableau** avec les dimensions clés (droits, sanctions, portée, consentement) et les différences par axe.

**Ce qu'OSMOSIS peut faire** : les Perspectives + les QS_COMPARED + les CONTRADICTS fournissent la matière structurée. Il suffit d'organiser la présentation :

| Dimension | RGPD | CCPA | Tension |
|-----------|------|------|---------|
| Consentement | Opt-in explicite | Opt-out | Philosophique |
| Amendes max | 20M€ / 4% CA | $7.5M / 1.5% CA | Échelle |
| Droits effacement | Oui (Art. 17) | Oui (§1798.105) | Alignement |
| Transferts internationaux | SCC/BCR requis | Pas de restriction | Divergence |

**Valeur client** : "En un coup d'œil, vous voyez les convergences et divergences entre deux réglementations."

**Différenciateur vs RAG/Copilot** : un RAG ne peut pas structurer une comparaison car il ne connaît pas les dimensions. Les QS (QuestionSignatures) d'OSMOSIS fournissent exactement ces dimensions.

**Implémentation** :
- Nouveau mode de réponse `COMPARISON` (en plus de DIRECT, TENSION, PERSPECTIVE)
- Extraction des dimensions depuis les QS partagées entre deux sujets
- Rendu tabulaire dans le frontend
- Les 50482 QS_COMPARED sont la source

---

### 4. Audit de complétude — "Qu'est-ce qui manque ?"

**Le problème** : un compliance officer doit s'assurer que sa documentation couvre TOUS les aspects d'un règlement. Mais comment savoir ce qui manque si on ne sait pas ce qu'on ne sait pas ?

**Ce qu'OSMOSIS peut faire** : en comparant la structure du KG (Perspectives, Facets, entités) avec un référentiel (les articles d'un règlement, les exigences d'un standard), identifier les **zones aveugles** :

- "Votre corpus couvre 85% des exigences de l'AI Act. Les 15% manquants concernent : Art. 52 (transparence des systèmes interactifs), Art. 53 (obligations des providers de GPAI), ..."
- "Aucun de vos documents ne mentionne les obligations de certification (Art. 43)"

**Valeur client** : "OSMOSIS identifie non seulement ce que vous savez, mais surtout ce que vous ne savez pas."

**Différenciateur vs RAG/Copilot** : un RAG ne peut pas identifier un manque — il ne sait pas ce qu'il devrait savoir. OSMOSIS, via le KG structuré et les Facets, peut détecter les trous.

**Implémentation** :
- Référentiel structuré par domaine (articles de loi, exigences standard) — fourni par le Domain Pack
- Mapping claims existantes → exigences du référentiel
- Score de couverture par axe
- Dashboard "compliance gap analysis" dans l'Atlas

---

### 5. Timeline documentaire — "Comment ça a évolué ?"

**Le problème** : les réglementations évoluent (GDPR → amendments, AI Act proposal → final). Un juriste a besoin de voir l'**évolution** dans le temps : qu'est-ce qui a changé, ajouté, supprimé entre deux versions ?

**Ce qu'OSMOSIS peut faire** : les relations EVOLVES_TO, CHAINS_TO et les ApplicabilityAxis (version/date) permettent de reconstruire une timeline :

```
2016: GDPR adopté (Art. 17 - droit à l'effacement)
2021: AI Act proposé (pas de mention du droit à l'effacement pour l'IA)
2024: AI Act final (Art. 73 - interaction avec GDPR pour les données d'entraînement)
2025: EDPB guidelines (problème de mémorisation dans les LLMs → effacement impossible)
```

**Valeur client** : "OSMOSIS retrace l'histoire de chaque exigence à travers les versions et les documents."

**Différenciateur vs RAG/Copilot** : un RAG traite tous les documents comme un sac plat. OSMOSIS connaît les relations temporelles entre les claims.

**Implémentation** :
- Visualisation timeline dans l'Atlas (axe temps)
- Détection automatique des évolutions via EVOLVES_TO + REFINES
- Filtre "version/date" déjà partiellement implémenté (ApplicabilityAxis)

---

## Priorisation

| Usage | Valeur perçue | Effort | Données dispo | Priorité |
|-------|--------------|--------|---------------|----------|
| **Comparaison structurée** | Très haute | Moyen | QS_COMPARED (50K) | **P0** |
| **Détection proactive** | Très haute | Moyen | CONTRADICTS, REFINES | **P0** |
| **Audit de complétude** | Haute | Élevé | Facets + Domain Pack | **P1** |
| **Queryable Truth Layer** | Haute | Élevé | Cypher + KG | **P1** |
| **Timeline documentaire** | Moyenne | Moyen | EVOLVES_TO, CHAINS_TO | **P2** |

### 6. Raisonnement transparent — "Voici comment je cherche"

**Le problème** : un RAG classique (y compris OSMOSIS aujourd'hui) renvoie une réponse finale sans montrer le chemin. L'utilisateur ne sait pas si le système a cherché dans les bons documents, s'il a considéré toutes les versions, s'il a détecté des contradictions.

**Ce que fait un concurrent** : montrer les étapes de recherche en temps réel :
```
🔍 Recherche dans le KG : "S/4HANA security"
🔍 Recherche par version : "S/4HANA 2023 security guide"
🔍 Recherche par version : "S/4HANA 2022 security guide"
🔍 Recherche ciblée : "S/4HANA Identity Authentication IAS"
💡 Clarification : "Vous parlez de On-Premise, Cloud public, ou PCE ?"
📊 Réponse structurée par dimension (IAM, Audit, Réseau, Fiori)
```

**Ce qu'OSMOSIS peut faire** : le Query Decomposer V2 fait DÉJÀ de la décomposition multi-requêtes, des scope_filters par version, et du check_plan_integrity. Mais tout est invisible. Il suffit de :
- Streamer les sous-requêtes et leurs résultats en temps réel (WebSocket)
- Afficher les Perspectives activées comme "axes de recherche"
- Montrer les tensions détectées AVANT la synthèse
- Poser des questions de clarification quand l'ambiguïté est forte

**Valeur client** : "Je vois exactement comment OSMOSIS raisonne. Je peux vérifier qu'il n'a rien oublié."

**Différenciateur vs concurrent** : le concurrent montre des recherches. OSMOSIS peut montrer des **preuves** — chaque claim avec sa source, chaque contradiction avec ses deux côtés. C'est le "Queryable Truth Layer" appliqué au raisonnement.

**Implémentation** :
- WebSocket pour le streaming des étapes de recherche (partiellement implémenté)
- Frontend : composant "reasoning trace" avec les sous-requêtes, les résultats intermédiaires, les tensions détectées
- API : exposer le `reasoning_trace` déjà présent dans la réponse search (mais actuellement vide ou minimal)
- Le Query Decomposer V2 fournit déjà les sub-queries — il suffit de les rendre visibles

---

## Note stratégique

Ces usages ne sont pas des "features" — ce sont des **paradigmes**. Un RAG répond. OSMOSIS observe, alerte, compare, audite. C'est ce qui justifie un KG vs un simple index vectoriel.

Le KG n'est pas un luxe technique — c'est le socle qui rend ces usages possibles. Sans les CONTRADICTS, pas de détection proactive. Sans les QS_COMPARED, pas de comparaison structurée. Sans les Facets, pas d'audit de complétude.

C'est ça la proposition de valeur : **le KG transforme un corpus passif en un système de connaissance actif.**
