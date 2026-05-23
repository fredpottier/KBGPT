# ADR A4 — Choix 3 : Refonte runtime_v6 (DRAFT)

**Statut** : DRAFT — activation seulement si Choix 1 (Piste A Hybrid) ET Choix 2 (Vector-first) plafonnent tous les deux à C1 < 0.45 sur 20q.
**Date** : 2026-05-22
**Contexte** : post-A4.7 audit Oracle qui a verrouillé que **18/18 questions** où la preuve existe dans le KG sont en `lost_at_RETRIEVAL` avec recall=0%.

---

## Cadre domain-agnostic (rappel)

Cette refonte doit produire un runtime applicable à tout domaine (médical, réglementaire, juridique, aerospace...). Aucune dépendance corpus-spécifique.

---

## 1. Constat justifiant une refonte

Si Choix 1 (Hybrid BM25+Vector+RRF) ET Choix 2 (Vector-first direct) échouent tous les deux à dépasser C1 ~ 0.45, c'est que le pattern `Parse (sub_goals structurés) → Plan → Execute (tools KG/Qdrant) → Evaluate → Synthesize` n'est **pas le bon paradigme** pour les requêtes Q&A factuelles sur un KG bitemporal.

L'ADR_PARSE_EVALUATE_RUNTIME (A3.0) suppose que la question peut être **décomposée en sub_goals fact_lookup avec subject/predicate canoniques**, et que le retrieval peut être **précisément ciblé** une fois ces canoniques résolus. Si ce paradigme ne fonctionne pas, il faut le remplacer.

## 2. Décisions architecturales à trancher

### Option 3.A — Agentic RAG multi-agent (Mindful-RAG pattern)

**Source** : *Mindful-RAG: A Study of Points of Failure in RAG* (arxiv 2407.12216), arxiv 2411.13045 Agentic RAG patterns 2026.

Architecture :
- **Agent décomposeur** : split question en facets (entités, prédicats implicites, contraintes)
- **Agent retriever** : pour chaque facet, retrieval hybride (BM25 + vector) avec scoring de pertinence
- **Agent sufficiency-check** : *« avons-nous assez d'evidence pour répondre ? »*
- **Agent textual-recovery** (fallback) : si sufficiency=NO, lecture libre du texte source (à la V5.1 Reading Agent)
- **Agent synthesizer** : compose la réponse à partir des evidence collectés

Avantages :
- Pattern à l'état de l'art 2026 (publications majeures convergent vers ce paradigme)
- Sufficiency-check évite hallucinations *et* abstentions injustifiées
- Textual recovery fallback domaine-agnostic (utilise les chunks Qdrant existants)
- Validation orchestrée multi-tour (pas un pipeline figé)

Inconvénients :
- Coût LLM significativement plus élevé (3-4 LLM agents au lieu de 3 LLM calls séquentiels)
- Latence p95 probable > 60s (vs 30s actuel)
- Complexité orchestration (état partagé entre agents, retries, timeouts)

Estimation : ~3-4 semaines dev.

### Option 3.B — Pattern Mindful-RAG light (sufficiency check uniquement)

Architecture :
- Garder `Parse → Plan → Execute → Evaluate → Synthesize` actuel
- Ajouter **un check de sufficiency** entre Execute et Evaluate : *« le retrieval a-t-il ramené ≥1 claim avec score embedding ≥ 0.75 vis-à-vis de la question ? »*
- Si NON → activer **textual recovery** : retrieval Qdrant sections directement, bypass des claims
- Si OUI → continuer pipeline normal

Avantages :
- Préserve l'investissement A3 (parse/plan/execute/evaluate)
- Ajout incrémental, pas de refonte
- Domain-agnostic (sufficiency = score sémantique pur)

Inconvénients :
- Ne résout pas le problème si le retrieval ramène des claims **mauvais** mais avec embedding score élevé (cas observé HUM_0031)
- Reste un patch sur un paradigme potentiellement inadéquat

Estimation : ~1-1.5 semaines dev.

### Option 3.C — Workspace-based reasoning (à la V5.1 ADR §S4)

Architecture :
- Reprendre le pattern V5.1 Reading Agent qui a fait ses preuves sur 2 corpus (SAP=0.737, aerospace=0.779)
- Mais l'industrialiser proprement (cf ADR_CH52 déjà livré côté V5.1)
- Runtime_v6 abandonné — V5.1 promu production

Avantages :
- Réutilise du code déjà existant et benché (V5.1 a C1 0.45-0.77 selon corpus)
- Pattern Reading Agent prouvé domain-agnostic (validé aerospace ET SAP)
- ADR_CH52 V1.5 déjà finalisé et production-grade

Inconvénients :
- Abandon de l'investissement runtime_v6 (~3 mois dev A3.x)
- Perte de la traçabilité claim-based (V5.1 lit le texte source, runtime_v6 KG-only)
- Régression vs philosophie OSMOSE bitemporal claim-first

Estimation : ~1 semaine pour basculer production sur V5.1 (déjà industrialisé).

## 3. Critères de décision

Si on en arrive là, il faut trancher en consultation avec Fred sur :

1. **Priorité traçabilité vs qualité** : V5.1 (lecture libre PDF) a meilleure qualité mais moins de traçabilité claim-based ; runtime_v6 a meilleure traçabilité mais qualité actuelle insuffisante.
2. **Investissement vs réutilisation** : Option 3.A (Agentic) demande 3-4 semaines neuves ; Option 3.C réutilise V5.1.
3. **Vision produit OSMOSE** : si la traçabilité claim-by-claim est non-négociable (différenciation vs Microsoft Copilot/Google Gemini), Option 3.A est obligatoire. Sinon Option 3.C est tactiquement supérieure.

## 4. Recommandation provisoire

**Option 3.B (sufficiency check + textual recovery)** comme première tentative :
- Effort modéré (1-1.5 semaines)
- Préserve investissement A3
- Domain-agnostic strict
- Si gain marginal → bascule Option 3.A (Agentic RAG)
- Si gain marginal après Option 3.A → bascule Option 3.C (retour V5.1)

## 5. Hors scope cet ADR

- Implémentation détaillée des prompts agents (Option 3.A) — séparé en sous-ADR si activation
- Décision V5.1 vs runtime_v6 pour production — décision produit, pas technique

---

**Statut** : DRAFT. Reste à : (a) finaliser le critère d'activation depuis A4.9 ; (b) consulter Fred sur priorité traçabilité vs qualité ; (c) prototyper Option 3.B sufficiency check avant escalade Option 3.A.
