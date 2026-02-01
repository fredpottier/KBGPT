# ADR — Concept Admissibility : frontières de candidature au linking

**Date :** 2026-01-30
**Statut :** PROPOSÉ
**Contexte :** Runs 4-6 du pipeline stratifié Pass 1

---

## Problème

Le linking (Pass 1.4) met **tous les concepts en concurrence pour chaque assertion**.
Résultat structurel observé sur 3 runs consécutifs :

| Symptôme | Valeur stable | Cause racine |
|----------|:---:|---|
| Concepts "aspirateurs" (TOM : 15-24 infos, precision 4-7%) | Persistant | Concept sans frontière → gagne par défaut sémantique |
| Concepts vides (41-59%) | Persistant | Concepts jamais compétitifs au scoring global |
| COMBINED mal-routées → thèmes vides (56-62%) | Persistant | Assertions proches d'un concept vide mais routées ailleurs |
| SINK élevé (38-77) | Variable | Aucun concept local assez fort → fallback SINK |

**Ce qu'on a prouvé (Runs 4→6) :**
- Ajuster les seuils de scoring (±10%) ne change pas l'équilibre fondamental
- Le signal de localité (page) est valide mais insuffisant comme tie-breaker
- Le problème n'est ni le LLM, ni le scoring, ni la localité — c'est **l'absence de frontières de candidature**

---

## Hypothèse

> Un concept n'est pas admissible partout.

Une assertion issue de la section "Database Backup" ne devrait pas concourir pour le concept "Technical Organisational Measures" (thème "Technical Basis") si un concept local ("Database backup") existe dans le thème "Database".

---

## Principe : restreindre l'espace de candidature AVANT le rerank

Pour chaque assertion :
1. Déterminer sa **section d'origine** (chunk → DocItem → section_id)
2. Identifier les **thèmes locaux** (thèmes dont les concepts ont des triggers actifs dans cette section)
3. Restreindre les concepts candidats :
   - Concepts des thèmes locaux (prioritaires)
   - Concepts CENTRAL (toujours admissibles)
   - Concepts SINK (toujours admissibles, filet de sécurité)
4. **Puis seulement** appliquer le rerank existant (scoring, pénalité, top-K)

**Variante soft (POC recommandée) :** ne pas exclure les concepts non-locaux, mais leur appliquer un malus d'admissibilité (ex: ×0.85) pour que les concepts locaux soient naturellement préférés.

---

## Non-objectifs explicites

- **Pas de refonte ontologique** — on ne change pas la façon dont les concepts sont identifiés
- **Pas de dépendance au domaine SAP** — le mécanisme est générique
- **Pas de scoring magique** — on ne touche plus aux seuils tant que ce point n'est pas testé
- **Pas de modification du LLM prompt** — le linking LLM reste identique

---

## Données disponibles au moment du linking

| Donnée | Disponible ? | Via |
|--------|:---:|---|
| assertion → chunk_id | Oui | RawAssertion.chunk_id |
| chunk → section_id | Oui | chunk_to_docitem_map → DocItem.section_id |
| concept → theme_id | Oui | Concept.theme_id |
| theme → sections scopées | **Non** (placeholder vide) | Theme.scoped_to_sections jamais rempli |
| concept → pages sources | Oui | _concept_source_pages (cascade 3 niveaux) |
| assertion → pages | Oui | _chunk_pages |

**Stratégie :** construire le scope thème→sections **dynamiquement** à partir des triggers des concepts (déjà pré-calculé dans `_concept_source_pages`), sans dépendre de `scoped_to_sections`.

---

## Critères de validation (Run 7 vs Run 6)

| Métrique | Run 6 (baseline) | Cible | Seuil d'échec |
|----------|:---:|:---:|:---:|
| Informations | 236 | >= 230 | < 200 (perte de rappel) |
| Concepts vides | 39/66 (59%) | < 45% | > 60% (régression) |
| TOM precision | 7% (1/15) | > 25% | < 7% (régression) |
| COMBINED mal-routées | 62% | < 50% | > 65% (régression) |
| SINK | 77 | < 60 | > 90 (explosion) |

**Critère d'arrêt :** si concepts vides baisse significativement sans explosion SINK → généraliser. Sinon → invalider l'hypothèse.

---

## Moratoire

**Tant que ce POC n'est pas testé, on ne touche plus :**
- Aux seuils de scoring (CONF_THRESHOLD_*, MARGIN_AMBIGUOUS)
- Aux bonus/malus (locality, lexical, semantic)
- À la logique SINK (bandes, gap)

**On peut continuer :**
- Le filtrage des thèmes vides (acquis)
- Les améliorations d'extraction (Pass 1.3)
- Les diagnostics et métriques
