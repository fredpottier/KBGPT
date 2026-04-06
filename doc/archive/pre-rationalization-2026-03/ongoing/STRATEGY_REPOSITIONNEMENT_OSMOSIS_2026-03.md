# OSMOSIS — Stratégie de Repositionnement & Feuille de Route Produit
**Date** : 2026-03-10
**Statut** : Document de cadrage stratégique — vivant, mis à jour au fil des décisions
**Auteurs** : Analyse croisée Claude + ChatGPT + décisions fondateur
**Référence technique** : `doc/ongoing/OSMOSE_TRAVAUX_RESTANTS_2026-03.md`
---
## 1. Constat de Départ — Pourquoi un Repositionnement
### 1.1 Le problème initial
OSMOSIS a été construit en utilisant des sources documentaires SAP (documentation technique, SAP Notes, guides produit). Ce choix était pragmatique — travaillant pour SAP, ces sources étaient immédiatement accessibles.
**Mais SAP dispose déjà d'un outil similaire** (KG + RAG) construit avec :
- Un cadre ontologique propre et borné
- Les sources officielles (help.sap.com, SAP Notes)
- Les ressources de maintenance
- La légitimité institutionnelle
**Conclusion : se battre sur le terrain SAP contre SAP est une bataille perdue d'avance.**
### 1.2 Ce qui est acquis
L'architecture technique d'OSMOSIS est **solide et domain-agnostic** :
- Pipeline d'ingestion multi-format (PDF, PPTX, DOCX, XLSX, MD, HTML)
- Knowledge Graph avec enrichissement sémantique (267 entités canoniques, 565 relations cross-doc)
- Détection de contradictions multi-couches (5 niveaux)
- Tracking d'évolution temporelle (MODIFIED / ADDED / REMOVED)
- Multi-tenant avec isolation complète
- Configuration domain-agnostic via Domain Context (INV-25 : zéro regex SAP)
- 81 modules Python dans `claimfirst` seul
- 3 944 tests
### 1.3 La vraie nature du projet
Ce projet a commencé comme un **projet personnel** pour progressivement migrer vers une **volonté de commercialisation**. L'objectif a toujours été de construire une plateforme **complètement agnostique du domaine fonctionnel**, pas un produit SAP.
---
## 2. Analyse de Positionnement — Synthèse des Réflexions
### 2.1 Options évaluées
| Option | Description | Verdict |
|--------|-------------|---------|
| **Plateforme doc généraliste** | "Chat with your docs" | ❌ Marché saturé (Glean, Guru, Notion AI, Copilot) |
| **Niche technique** | Réglementation, clinique, OSS | ⚠️ Viable mais limitant |
| **Veille / Intelligence** | Analyse d'évolution, narrative threads | ⚠️ Intéressant mais prématuré |
| **Documentation Verification** | Cohérence, contradictions, évolutions | ✅ **RETENU** — aligné avec l'existant |
### 2.2 Identification du vrai différenciateur
**Ce qu'OSMOSIS fait et qu'aucun RAG du marché ne fait :**
Un RAG classique fonctionne ainsi :
documents → chunks → embeddings → réponse

OSMOSIS fonctionne ainsi :
documents → extraction → claims → graph → reasoning

Ce n'est **pas la même catégorie d'outil**. OSMOSIS possède une **représentation structurée de la connaissance** portée par les documents :
| Capacité | RAG classique | OSMOSIS |
|----------|:---:|:---:|
| "Quelle est notre politique X ?" | ✅ | ✅ |
| "Cette politique a-t-elle changé ?" | ❌ Aveugle | ✅ Timeline d'évolution |
| "Y a-t-il des contradictions ?" | ❌ Aveugle | ✅ 5 couches de détection |
| "Que manque-t-il dans notre doc ?" | ❌ Aveugle | ✅ Analyse de complétude |
| "Peut-on se fier à cette information ?" | ❌ Aveugle | ✅ 6 régimes de vérité |
### 2.3 Profondeur technique réelle (audit du code)
L'audit du codebase révèle que la différenciation est **beaucoup plus profonde** que "contradictions + évolutions" :
| Capacité | Détail technique | Impact |
|----------|-----------------|--------|
| **Contradiction Detection** | 5 couches : bucketing → exclusivité prédicat → ValueFrame → comparateur formel → arbitrage LLM | Aucun concurrent ne fait ça |
| **Truth Regimes** | 6 régimes : NORMATIVE_STRICT, NORMATIVE_BOUNDED, EMPIRICAL_STATISTICAL, DESCRIPTIVE_APPROX, CONDITIONAL_SCOPE, TEXTUAL_SEMANTIC | Raisonnement épistémologique codé |
| **Quality Gates** | 5 phases avec vérifiabilité, tautologie, atomicité, indépendance | Pipeline de vérification formelle |
| **Invariants** | Système formel INV-1 à INV-26 garantissant la traçabilité probatoire | Auditabilité de niveau enterprise |
| **Evidence-locking** | Pointer mode — chaque claim verrouillée à ses `unit_ids` source | Zéro connaissance inventée |
| **ClaimKey lifecycle** | EMERGENT → COMPARABLE → DEPRECATED | Gestion du cycle de vie des faits |
**Conclusion de l'audit** : OSMOSIS n'est pas "un RAG un peu plus intelligent". C'est un **moteur d'analyse de faits documentaires** avec des capacités de vérification formelle.
### 2.4 Le vrai problème résolu
Le problème n'est **pas** la recherche documentaire. Le problème est :
> **Les entreprises ne peuvent pas se fier à leur propre documentation.**
Exemples concrets :
- **Produit** : spec produit dit X, doc marketing dit Y, doc support dit Z — contradictions permanentes
- **Sécurité** : doc architecture vs doc runbook vs doc compliance — incohérences critiques
- **Réglementaire** : version 2022 vs version 2024 — impossible de savoir ce qui est valide
- **Post-acquisition** : documentation héritée de 3 entités fusionnées — chaos documentaire
---
## 3. Positionnement Retenu
### 3.1 Catégorie produit
> **Documentation Verification Platform**
Ni "Document Intelligence" (trop vague), ni "Truth Engine" (trop absolu, politiquement risqué en entreprise), ni "Enterprise RAG" (mort en arrivant).
### 3.2 Pitchs calibrés
**Version 30 secondes :**
> *"Aujourd'hui, quand vous cherchez une information dans vos documents, les outils vous donnent la meilleure réponse trouvée. Mais ils ne vous disent pas si cette information est contredite dans un autre document, si elle a été mise à jour depuis, ou si un pan entier de connaissance manque. Osmosis ne cherche pas dans vos documents — il les vérifie. Il construit une représentation structurée de votre connaissance et détecte automatiquement les contradictions, les évolutions et les angles morts."*
**Version 10 secondes :**
> *"Osmosis transforme vos documents en connaissance vivante : il détecte ce que la recherche ne voit pas — contradictions, évolutions, incohérences."*
**Tagline :**
> **"De la recherche documentaire à l'intelligence documentaire"**
### 3.3 Les 3 piliers de valeur (basés sur le code existant)
| Pilier | Feature réelle | Question client |
|--------|---------------|-----------------|
| **Cohérence** | Contradiction detection 5 couches + truth regimes | "Nos docs se contredisent-elles ?" |
| **Traçabilité** | Evolution tracking + applicability frames | "Qu'est-ce qui a changé entre v1 et v2 ?" |
| **Fiabilité** | Quality gates + evidence-locking + confidence scoring | "Peut-on se fier à cette information ?" |
### 3.4 Pourquoi PAS "Truth Engine" / "Truth Layer"
Le mot **"truth"** est dangereux commercialement :
1. Implique un jugement de valeur absolu — or le système est nuancé (6 régimes de vérité, tolérance, scopes conditionnels)
2. Politiquement explosif en entreprise — "qui a tort, le VP Produit ou le VP Marketing ?"
3. Le bon cadrage n'est pas "vérité" mais **"cohérence et traçabilité"** — moins sexy mais plus vendable
Le terme "truth layer" peut être utilisé dans un whitepaper technique, pas dans un pitch commercial.
---
## 4. Vision Long Terme — 3 Horizons
### Horizon 1 (maintenant → 6 mois) : Documentation Verification Platform
- **Wedge market** : Éditeurs logiciels mid-size (50-500 pers.), cabinets de conseil
- **Feature phare** : Détection de contradictions + évolution tracking
- **Objectif** : 5 clients pilotes, pas une vision grandiose
- **Positionnement** : "Osmosis détecte automatiquement les contradictions et les évolutions dans votre documentation"
### Horizon 2 (6 → 18 mois) : Knowledge Verification Platform
- **Élargissement** : Toute entreprise avec documentation complexe
- **Ajout** : Analyse de complétude, narrative threads matures
- **Objectif** : Product-market fit validé
- **Positionnement** : "Osmosis vérifie la cohérence et la fiabilité de la connaissance dans votre documentation"
### Horizon 3 (18+ mois) : AI Knowledge Governance Layer
- **Condition** : Le marché AI Governance mûrit (EU AI Act enforcement, NIST frameworks)
- **Pivot** : L'architecture est DÉJÀ prête — fact-centric, cross-doc, traceable, contextual
- **Positionnement** : "La couche de vérification entre la connaissance d'entreprise et les systèmes AI"
- **Mais** : On y arrive avec des clients, du revenu et de la crédibilité — pas avec un slide deck
### Décision : Produit d'abord, Infrastructure ensuite
| Produit (court terme) | Infrastructure (long terme) |
|---|---|
| UI dominante | API dominante |
| Vendu aux équipes | Intégré aux plateformes |
| SaaS | Moteur embarquable |
| Feature-driven | Ecosystem-driven |
L'architecture actuelle penche vers l'infrastructure (32+ endpoints API, multi-tenant, domain-agnostic), mais **le chemin commercial passe par le produit** :
- Un produit génère du revenu et des retours utilisateurs rapidement
- Une infrastructure nécessite un écosystème de développeurs, doc API parfaite, support technique
- Playbook classique : Stripe, Twilio ont commencé comme produit avant de devenir infrastructure
---
## 5. Premier Marché Cible
### 5.1 Cible principale : Éditeurs logiciels mid-size (50-500 personnes)
**Pourquoi :**
- Documentation massive qui évolue à chaque release
- Contradictions fréquentes entre doc produit, support, marketing
- Pas les moyens de SAP/Microsoft pour construire leur propre outil
- Comprennent immédiatement "vos docs se contredisent sur ces 3 points"
- Ticket d'entrée accessible
### 5.2 Cible secondaire : Cabinets de conseil / audit
- Analysent des masses documentaires pour leurs clients
- La détection de contradictions dans la documentation client est une prestation à forte valeur
- Crédibilité institutionnelle qui peut accélérer l'adoption
### 5.3 Cible horizon 2 : Compliance / Réglementaire
- Contradictions entre versions réglementaires = risque légal
- Corpus RGPD/ENISA/NIST déjà prêt à ingérer (76 documents)
- Marché plus niche mais ticket plus élevé
---
## 6. Chantiers P0 — Bloquants Avant Toute Commercialisation
### 6.1 État de maturité commerciale (audit mars 2026)
| Dimension | Score | Détail |
|-----------|-------|--------|
| Architecture technique | **9/10** ✅ | Pipeline complet, multi-tenant, domain-agnostic |
| Documentation produit | **3/10** 🔴 | Zéro doc en anglais, zéro guide utilisateur |
| Données de démo | **2/10** 🔴 | Aucune donnée non-SAP dans le KG. Impossible de montrer à un prospect |
| Sécurité enterprise | **5/10** 🟡 | Pas de SSO/SAML, pas de secrets management |
| Frontend Intelligence Report | **6/10** 🟡 | Pas de visualisation KG, pas de dashboard contradictions |
| CI/CD | **0/10** 🔴 | 3 944 tests mais aucun pipeline automatisé |
| Scalabilité | **5/10** 🟡 | Docker-compose only, single-node |
| **Score commercial global** | **5.5/10** | **R&D avancée, pas encore un produit vendable** |
### 6.2 Chantier P0-A : Corpus de démo non-SAP
**Décision** : Utiliser le corpus réglementaire **déjà présent** dans `data/burst/waiting_rgpd_1/` (76 documents PDF).
| Source | Nombre | Type |
|--------|--------|------|
| EDPB (European Data Protection Board) | 29 docs | Guidelines, opinions RGPD |
| ENISA (EU Agency for Cybersecurity) | 32 docs | Threat landscapes, risk management |
| NIST | 3 docs | AI Risk Management Framework |
| WEF | 3 docs | AI governance |
| CNIL, AEPD, FRA, EDPS | 9 docs | Régulateurs nationaux |
**Pourquoi ce corpus :**
- Zéro fichier à télécharger — déjà présent
- Format PDF natif — pipeline validé
- Domain context RGPD créé et mis à jour (3 piliers : Data Protection + Cybersecurity + AI Governance)
- Contradictions naturelles entre régulateurs (CNIL vs EDPB, NIST vs ENISA)
- Storytelling puissant : *"Osmosis a ingéré 76 documents de 8 régulateurs et détecté 14 contradictions..."*
**Fichier domain context** : `config/domain_context_rgpd.json` — mis à jour le 2026-03-10 pour couvrir les 3 piliers du corpus.
**Prochaine étape** : En parallèle, préparer un corpus OSS (Docker ou PostgreSQL) pour démontrer le caractère domain-agnostic. Le support MD/HTML a été ajouté au pipeline (2026-03-10).
### 6.3 Chantier P0-B : Intelligence Report UI
L'écran "Intelligence Report" est **LA** traduction visible de la valeur d'OSMOSIS. Sans lui, 81 modules Python restent invisibles.
**Contenu minimum :**
- Nombre de contradictions détectées (avec drill-down vers les claims source)
- Évolutions entre versions (MODIFIED / ADDED / REMOVED)
- Score de cohérence global du corpus
- Timeline des changements
- Export PDF (pour les cabinets de conseil)
**Scénario de démo cible :**
ÉTAPE 1 : Ingestion d'un corpus (ex: 76 docs réglementaires) → "Osmosis a ingéré 76 documents, identifié 800 claims, 200 entités" ÉTAPE 2 : Question classique (RAG standard) → "Quel est le délai de notification de breach RGPD ?" → "72 heures" → "Jusque-là, n'importe quel RAG fait pareil." ÉTAPE 3 : LE MOMENT DIFFÉRENCIANT → "Osmosis a détecté 5 contradictions entre les guidelines EDPB et ENISA" → "3 recommandations NIST divergent des obligations NIS2" → "4 claims ont évolué entre les guidelines EDPB v1.0 et v2.0" → "Aucun RAG ne vous montre ça."

**Statut** : À CONCEVOIR — nécessite un design frontend + les endpoints API correspondants.
### 6.4 Chantiers P1 (après les P0)
| Priorité | Chantier | Raison |
|----------|----------|--------|
| P1 | Documentation en anglais (API + Getting Started) | 80% du marché est anglophone |
| P1 | CI/CD pipeline | Tests automatisés = crédibilité technique |
| P1 | Jeu de données OSS (Docker/PostgreSQL) | Démontrer le domain-agnostic |
| P2 | Sécurité enterprise (SSO/SAML) | Exigence des prospects enterprise |
| P2 | Scalabilité (Kubernetes, multi-node) | Production-readiness |
---
## 7. Validation Marché — Actions Parallèles
### 7.1 Conversations exploratoires (pas des démos)
**Objectif** : Valider le problème, pas vendre le produit.
**Question de qualification** :
> "Comment gérez-vous les contradictions dans votre documentation interne ?"
Si la réponse est "oui, c'est un cauchemar" → le problème est validé.
**Cibles pour les 5 premières conversations :**
1. Knowledge manager d'un éditeur SaaS mid-size
2. Consultant en management / cabinet de conseil
3. Responsable compliance / DPO
4. Product manager d'un éditeur logiciel
5. CTO / VP Engineering d'une startup 100+ personnes
### 7.2 Ce qu'on NE fait PAS encore
- Pas de site web marketing
- Pas de pricing
- Pas de mention "AI Governance" dans le messaging externe
- Pas de positionnement "Truth Engine" ou "AI Safety"
- Pas de recherche de financement
---
## 8. Modifications Techniques Réalisées (2026-03-10)
### 8.1 Support Markdown / HTML ajouté au pipeline
| Fichier | Modification |
|---------|-------------|
| `folder_watcher.py` | SUPPORTED_EXTENSIONS + routage md/html/docx |
| `ingestion.py` | Set validation document_kind + branche routage |
| `feature_flags.yaml` | supported_formats élargi |
| `burst.py` | Filtre documents + routage pipeline |
| `downloads.py` | Liste extensions + MIME types |
| `dispatcher.py` | Aucune modification — enqueue_document_v2() déjà générique |
**Docling supportait déjà ces formats** — les modifications ont simplement débloqué les points d'entrée qui filtraient les extensions.
### 8.2 Domain Context RGPD mis à jour
`config/domain_context_rgpd.json` — refonte complète pour couvrir les 3 piliers :
- **Data Protection** : GDPR, EDPB, CNIL, CJEU, EDPS
- **Cybersecurity** : ENISA, NIS2, EECC
- **AI Governance** : AI Act, NIST AI RMF, WEF
Changements majeurs : 14 → 20 sous-domaines, 20 → 43 acronymes, 5 → 10 target users, prompt d'injection revu pour 6 niveaux d'autorité, 3 → 5 règles de reclassification d'axes.
---
## 9. Risques Stratégiques
### 9.1 Risque #1 : Être perçu comme "un RAG un peu plus intelligent"
**Probabilité** : HAUTE si le messaging n'est pas maîtrisé
**Impact** : CRITIQUE — comparaison directe avec Glean, Copilot, etc. = défaite assurée
**Mitigation** : Ne jamais utiliser les termes "RAG", "chat with your docs", "AI search" dans le messaging. Toujours parler de **vérification**, **cohérence**, **contradictions**.
### 9.2 Risque #2 : Value invisibility
**Probabilité** : HAUTE tant que l'Intelligence Report UI n'existe pas
**Impact** : ÉLEVÉ — aucun prospect ne lira 81 modules Python
**Mitigation** : P0-B (Intelligence Report) est le chantier le plus urgent après le corpus de démo
### 9.3 Risque #3 : Vision grandiose déconnectée du produit
**Probabilité** : MOYENNE — tentant de se projeter sur "AI Governance Layer" sans client
**Impact** : ÉLEVÉ — paralysie par l'ambition
**Mitigation** : L'Horizon 3 (AI Governance) est une **vision**, pas un plan d'action. On y arrive avec des clients et du revenu, pas avec un slide deck.
### 9.4 Risque #4 : Biais SAP résiduel
**Probabilité** : MOYENNE — les données actuelles du KG sont 100% SAP
**Impact** : MOYEN — tout prospect non-SAP verra immédiatement que c'est un produit SAP rebrandé
**Mitigation** : Ingérer le corpus RGPD en priorité absolue. Avoir au minimum 2 corpus domain-agnostic avant toute démo.
---
## 10. Métriques de Succès — Horizon 1
| Métrique | Actuel | Objectif H1 (6 mois) | Mesure |
|----------|--------|----------------------|--------|
| Corpus non-SAP ingérés | 0 | ≥2 (RGPD + OSS) | Nombre de domain contexts actifs |
| Contradictions détectées (non-SAP) | 0 | ≥20 | Requête Neo4j CONTRADICTS |
| Intelligence Report UI | Inexistant | V1 fonctionnelle | Page frontend opérationnelle |
| Conversations prospects | 0 | ≥5 | Compte-rendus documentés |
| Documentation en anglais | 0 pages | ≥10 pages (API + Getting Started) | Pages publiées |
| CI/CD pipeline | Inexistant | Opérationnel | GitHub Actions ou équivalent |
---
## 11. Références
- Architecture cross-doc : `doc/ongoing/ARCH_CROSS_DOC_KNOWLEDGE_LAYERS.md`
- Travaux techniques restants : `doc/ongoing/OSMOSE_TRAVAUX_RESTANTS_2026-03.md`
- Chantiers pipeline : `doc/ongoing/OSMOSE_CHANTIERS_PROCHAINES_ETAPES.md`
- Quality gates baseline : `doc/ongoing/quality_gates_baseline_analysis.md`
- Audit qualité claims : `doc/ongoing/AUDIT_QUALITE_CLAIMS_V1.6.md`
- Comparaison RAG vs KG : `doc/ongoing/COMPARAISON_RAG_VS_KG_CROSS_DOC.md`
- Domain context RGPD : `config/domain_context_rgpd.json`
- Domain context SAP : `config/domain_context_sap_global.json`
- Corpus RGPD : `data/burst/waiting_rgpd_1/`
