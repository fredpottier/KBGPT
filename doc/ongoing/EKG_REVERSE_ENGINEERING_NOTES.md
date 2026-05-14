# EKG (Enterprise Knowledge Graph SAP) — Notes de reverse engineering

> *Doc mémoire — 2026-05-14*
> *Contexte : reverse engineering d'EKX (chat IA SAP-interne basé sur EKG) lors de la session V5.1 OSMOSIS, en accès employé SAP.*
> *But : ne pas avoir à se reposer la question dans 3 mois.*

---

## 1. Qu'est-ce qu'EKG / EKX

- **EKG** = Enterprise Knowledge Graph (asset interne SAP, namespace `ekg.cloud.sap`)
- **EKX** = chat IA grand public SAP qui interroge EKG + sources documentaires
- Disponible aux employés SAP, accès non public au reste du monde
- Score mesuré sur notre panel SAP 50q gold_set_sap_v2 : **~0.86** (extrapolation depuis CH-51 30q hard)

## 2. Architecture observée (3 couches)

### Couche 1 — Knowledge Graph ontologique SAP

- **Standard W3C** : RDF/OWL, requêtes SPARQL (pas Neo4j Cypher)
- **URIs persistantes business** : chaque concept SAP a un URI stable
  - Ex transaction : `https://ekg.cloud.sap/AP/S4H/PCM/TRAN/CGCZ`
  - Ex offre commerciale : `https://ekg.cloud.sap/SAP/LX/TM/CPT/RISEWith...{GUID}`
  - GUID format ABAP/HANA (`42010AEF0E491EEC9081C639C5418B6F`)
- **Namespaces hiérarchiques** : `AP/S4H/PCM/TRAN/` (Application/S4HANA/.../Transaction/)
- **Labels multilingues** par concept (FR, EN, DE minimum)
- **Cross-references** : un concept lie ses implémentations techniques
  - Ex : transaction CGCZ → function module `C1SVC_RFC_EXP_CACHE_INIT`
- **Source des données** : modélisation manuelle SAP + extraction metadata ABAP internes (tables TADIR, TSTCT, TFDIR) + pas seulement les PDF publics

### Couche 2 — Documentation enrichie liée au KG

- **SAPedia** (encyclopédie interne SAP) : articles avec cross-refs vers concepts KG
- **Service & Support Catalogue** : catalogue formalisé des services SAP
- **Help Portal** : pages publiques officielles
- **Tous interconnectés** : un concept KG pointe vers ses articles SAPedia, et vice-versa

### Couche 3 — Agent runtime (LLM-based)

Pattern observé sur 2 questions testées :

```
1. Multi-formulation query (3-7 reformulations)
   - FR + EN
   - Variations sémantiques ("OS updates", "OS patching", "OS maintenance")
   - Variations contextuelles ("frequency", "windows", "per year")

2. Search Knowledge Graph (recherche sémantique sur labels)
   - Plusieurs calls parallèles avec variations
   - Identifie les candidat URIs probables

3. Execute SPARQL Query (lookup précis avec URI)
   - SELECT ?p ?o WHERE { <URI> ?p ?o }
   - Récupère toutes propriétés + relations du concept

4. Retrieving External URLs (enrichissement SAPedia/Help/Catalogue)
   - Pages publiques officielles
   - Cross-refs cliquables

5. Synthèse template-driven adaptée par type de question
   - Tableau RACI pour responsabilités
   - Réponse courte + contexte + astuce pour lookup transaction
   - Follow-up question suggérée
```

## 3. Patterns observés sur 2 questions testées

### Question 1 — RACI patching S/4HANA PCE (multi-source business)

- 3 reformulations sémantiques
- 2 Search Knowledge Graph
- 1 Retrieving External URLs (Help, SAPedia, Service Catalogue)
- **Réponse format** : tableau (Élément / Responsabilité SAP) + bullets points d'attention + références cliquables ⚛ + follow-up "voulez-vous vérifier la matrice exacte de votre contrat ?"

### Question 2 — Transaction initialisation cache Expert (lookup technique)

- 6 reformulations (FR + EN + avec/sans le code candidat CGCZ)
- 1 Retrieving External URLs (Help Portal)
- 1 SPARQL Query précise sur URI `ekg.cloud.sap/AP/S4H/PCM/TRAN/CGCZ`
- **Réponse format** : réponse directe (CGCZ) + contexte d'usage + technique sous-jacente (function module ABAP) + label allemand + astuce + références cliquables

### Patterns à retenir

1. **Multi-formulation systématique** avant retrieval
2. **Recherche large puis lookup précis** (Search → SPARQL)
3. **Format de réponse adapté au type de question** (tableau pour RACI, réponse courte pour lookup)
4. **Astuce/contexte d'usage** ajouté quand pertinent
5. **Références cliquables** liant à des concepts du KG (pas des sections PDF)
6. **Follow-up question** parfois suggérée

## 4. Origine de la performance EKX (0.85+ estimé)

EKX bénéficie d'**assets SAP propriétaires accumulés sur des décennies** :

| Asset | Origine | Reproductible universel ? |
|---|---|---|
| **KG ontologique business** | Modélisation manuelle SAP (équipes Architecture) | ❌ Non — années-personnes d'effort métier |
| **Metadata techniques** (function modules, transactions) | Extraction tables ABAP internes (TADIR, TFDIR, TSTCT) | ❌ Non — accès aux systèmes SAP requis |
| **SAPedia** | Wiki interne rédigé par experts SAP | ❌ Non — contenu éditorial humain |
| **Service & Support Catalogue** | Catalogue services formalisé | ❌ Non — propriétaire SAP |
| **Labels multilingues** | Tables traduction SAP | ❌ Non — propriétaire SAP |
| **Templates de réponse** | Patterns business SAP curated | ✅ Patterns réutilisables (RACI, lookup, comparison) |
| **Multi-formulation query** | Comportement agent LLM | ✅ Réutilisable |
| **Pipeline Search → SPARQL → URL** | Architecture agent | ✅ Réutilisable |

## 5. Implications pour OSMOSIS / V6

### Inatteignable strictement universellement

EKX ≈ 0.85 sur SAP est **structurellement difficile à reproduire** sans :
- Modélisation business manuelle par tenant
- Accès aux metadata internes propriétaires du domaine
- Wiki éditorial humain

### Atteignable et compatible charte OSMOSIS

OSMOSIS V6 peut emprunter à EKX, en restant domain-agnostic :

1. **Indexation fine par identifiant** : chaque entité (transaction, code, article, médicament) = node KG avec URI persistante
2. **Multi-formulation query** au runtime
3. **Templates de réponse par answer_shape**
4. **Concept cards auto-générées par LLM** (équivalent SAPedia automatique — voir doc V6)
5. **Cross-references actives** entre entités
6. **Follow-up question** intelligente

### Cible réaliste OSMOSIS V6 universel

- **0.70-0.78** sur panel SAP (vs V5.1 actuel 0.62, vs EKX ~0.86)
- Gap résiduel ~0.08-0.15pp accepté comme prix de l'universalité
- **Argument commercial** : "EKX est SAP-locked ; OSMOSIS marche sur médical, légal, aerospace avec le même produit"

## 6. Pourquoi OSMOSIS ressemble à EKX (similarité observée par le user)

L'utilisateur (employé SAP) a noté énormément de similitudes entre EKX et OSMOSIS. **C'est cohérent** :

| Concept | OSMOSIS | EKX |
|---|---|---|
| KG-driven reasoning | V2 ClaimFirst, V5.1 DSG Neo4j | EKG ontologique |
| Multi-formulation query | V2 query_decomposer (CH-31.B) | Search Knowledge Graph multi-calls |
| Lecture multi-source synthesis | V5.1 reading_agent (10 tools) | SPARQL + Retrieving URLs + synthèse |
| Verifier post-synth | V5.1 GroundingVerifier HHEM-2.1 | Implicite via grounding KG |
| Templates de réponse | V3 Response Modes (CH-04) | RACI / lookup templates |
| Cross-references | V2 LOGICAL_RELATION + LIFECYCLE_RELATION | Concepts liés via URIs |
| Atlas narratif | OSMOSIS Atlas (V1.1+) | Probable équivalent SAPedia |
| Contradiction handling | V2 contradiction T2 bench + premise validator | Probable côté KG curated |

**Convergence architecturale** : les deux systèmes ont indépendamment convergé vers une **architecture KG + RAG + LLM + multi-formulation**.

**Différence principale** : EKX = **content curated humain** (KG + SAPedia), OSMOSIS = **content auto-extrait LLM**. Sur SAP, EKX gagne car le contenu curated existe ; sur d'autres domaines, OSMOSIS peut être plus rapide à déployer.

## 7. Question stratégique implicite

**OSMOSIS doit-il faciliter la "curation humaine" comme EKX ?**

Options possibles à long terme :
- **A** : Rester strictement automatique (universel pur, cible 0.70-0.78)
- **B** : Ajouter concept cards auto-générées LLM (équivalent SAPedia automatique, cible 0.75-0.82)
- **C** : Permettre aux tenants d'ajouter manuellement des "knowledge cards" curated (équivalent SAPedia humain, cible 0.78-0.85)

Sans réponse à cette question, le positionnement commercial reste flou.

## 8. Captures d'écran de référence

(Stockées dans `.claude/image-cache/` durant la session, à archiver dans `doc/archive/` si besoin)

- Process raisonnement EKX question 1 (RACI patching) : multi-Search Knowledge Graph + Retrieving External URLs
- Réponse EKX question 1 : tableau RACI structuré + bullets + références ⚛ + follow-up
- Process raisonnement EKX question 2 (cache Expert) : multi-Search + SPARQL Query explicite avec URI `AP/S4H/PCM/TRAN/CGCZ`
- Réponse EKX question 2 : réponse directe CGCZ + function module C1SVC_RFC_EXP_CACHE_INIT + astuce + référence

## 9. À retenir si on relit ce doc dans 3 mois

> EKX ≈ 0.86 sur SAP grâce à :
> 1. KG SAP ontologique curated manuellement (décennies)
> 2. Multi-source : KG + SAPedia + Service Catalogue + Help
> 3. Multi-formulation query + Search → SPARQL → URL pattern
> 4. Templates de réponse par type de question
> 5. Metadata SAP internes (function modules, labels multilingues)
>
> OSMOSIS peut emprunter 3+4 (charte universelle respectée).
> OSMOSIS ne peut pas emprunter 1+2+5 (asset propriétaire SAP).
> Cible réaliste OSMOSIS V6 universel : 0.70-0.78 sur SAP.
> Pour aller plus haut : permettre curation humaine optionnelle par tenant (Option C).
