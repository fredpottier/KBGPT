# 📚 Répertoire Études - KnowWhere OSMOSE

**Statut:** Études exploratoires (non validées)

---

## 📂 Contenu

Ce répertoire contient des études techniques exploratoires pour le projet KnowWhere OSMOSE. Ces études sont **en attente de validation** avant intégration dans les phases officielles.

### Études Disponibles

#### 1. **ARCHITECTURE_AGENTIQUE_OSMOSE.md** (70 KB)

**Sujet:** Architecture agentique pour orchestration pipeline Dual-KG

**Objectif:** Maîtriser coûts LLM tout en préservant qualité sémantique

**Contenu:**
- Design agentique minimal (5 agents spécialisés)
- FSM orchestration stricte (10 états, timeouts, guardrails)
- 15 tools avec JSON schemas I/O précis
- Politiques de routing quantifiées (NO_LLM/SMALL/BIG/VISION)
- Gate profiles objectivés avec formules chiffrées
- Budget Governor avec caps durs et cost model
- KPIs mesurables (10 métriques avec seuils)
- Redlines documentation existante
- Plan pilote 3 semaines (100 docs A/B test)

**Livrables:**
- Executive summary (≤15 lignes)
- 10 sections détaillées avec tableaux, YAML, JSON, pseudo-code
- Annexes (configs complètes, schemas, calculs)

**Estimation Coûts:**
- Scénario A (mostly SMALL): $0.20/doc (250 pages) = $0.81/1000 pages
- Scénario B (mix BIG): $0.64/doc = $2.56/1000 pages

**Décision Requise:** GO/NO-GO après lecture

---

## 🎯 Objectif du Répertoire

**Pourquoi un répertoire séparé ?**

Les études dans ce répertoire sont **exploratoires**:
- Propositions techniques non encore validées
- Analyses d'alternatives architecturales
- Études de faisabilité avant commitment
- Benchmarks et comparaisons

**Workflow**:
1. Étude créée dans `/doc/etudes/`
2. Revue et discussion
3. Décision GO/NO-GO
4. Si GO → intégration dans roadmap officielle (phase_X_osmose/)
5. Si NO-GO → archivage dans `/doc/archive/etudes/`

---

## 📋 Statuts Possibles

| Statut | Signification | Action Suivante |
|--------|---------------|-----------------|
| 🟡 **DRAFT** | En rédaction | Finaliser étude |
| 🟠 **REVIEW** | En revue | Feedback, itération |
| 🟢 **VALIDATED** | Approuvée | Intégration roadmap |
| 🔴 **REJECTED** | Rejetée | Archivage |
| ⏸️ **ON-HOLD** | En pause | Décision différée |

---

## 🗂️ Index Études

| Étude | Date | Statut | Décision Requise |
|-------|------|--------|------------------|
| **ARCHITECTURE_AGENTIQUE_OSMOSE.md** | 2025-10-13 | 🟡 DRAFT | GO/NO-GO architecture agentique |

---

## 🚀 Prochaines Étapes

### Si GO Architecture Agentique

1. **Valider étude** ARCHITECTURE_AGENTIQUE_OSMOSE.md
2. **Plan pilote 3 semaines** (100 docs A/B test)
3. **Intégration Phase 2** si pilote succès
4. **Déplacer étude** vers `/doc/phase2_osmose/ARCHITECTURE_AGENTIQUE.md`

### Si NO-GO

1. **Archiver étude** vers `/doc/archive/etudes/`
2. **Continuer Phase 1** sans architecture agentique
3. **Re-évaluer** approche dans 3-6 mois si besoin

---

## 📞 Questions

**Architecture Générale:**
- Référence: `OSMOSE_ARCHITECTURE_TECHNIQUE.md` (doc/ root)

**Roadmap Phases:**
- Référence: `OSMOSE_AMBITION_PRODUIT_ROADMAP.md` (doc/ root)

**Phase 1 Actuelle:**
- Référence: `phase1_osmose/PHASE1_IMPLEMENTATION_PLAN.md`

---

**Version:** 1.0
**Dernière MAJ:** 2025-10-13
