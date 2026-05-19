# Phase 5 — Polish & documentation

*Date : 30 avril 2026*

## Items P5 réalisés dans cette session

### ✅ P5.1 — 3 ADRs Armand
1. `doc/ongoing/ADR_INGESTION_CONFIDENCE.md` — seuils qualité ingestion + états (rejected/quarantined/warning/ok) + retry policy
2. `doc/ongoing/ADR_DOMAIN_PACK_LIFECYCLE.md` — versioning semver, validation pré-déploiement, rollback, tracking par claim
3. `doc/ongoing/ADR_RUNTIME_V2_OPERATIONAL.md` — SLA, 3 dashboards Grafana, disaster recovery, mode dégradé vLLM down

## Items P5 reportés (non réalisables sans setup spécifique)

### ⏳ P5.2 — Atlas narratif
Réflexion en cours dans memory `project_atlas_narratif.md`. Sortir du modèle "1 entité = 1 article" pour passer à "Atlas narratif 10-20 articles, sections dérivées des Perspectives V2". Chantier d'1-2 sem qui demande :
- Refonte UI atlas
- Repenser le pipeline de génération
- Tester sur 1 sujet pilote

→ Reporté : cohérent avec phasing (Phase 5 polish), pas critique pour démo V2.

### ⏳ P5.3 — Cockpit widget burst local
Mémoire `project_cockpit_widget_local_burst.md`. Throughput tok/s temps réel + courbe + KV cache + prefix cache, depuis vLLM `/metrics`.

→ Reporté : ops nice-to-have. Pas critique tant que vLLM EC2 marche.

### ⏳ P5.4 — RAGAS re-benchmark V2
Compare V2 vs V1.1 vs RAG pur sur faithfulness, context_relevance. Vérifier que V2 résout le gap -13.6 pts identifié antérieurement.

→ Reporté : nécessite vLLM stable + setup RAGAS qui était benchmark-spécifique. Non bloqueur, à scheduler en session dédiée.

## Bilan P5

- **3 ADRs Armand prêts** : prêts à soumettre à un test client réel
- **3 items polish reportés** : non-critiques pour la mission primaire V2

## Acceptation

✅ ADRs publiés dans doc/ongoing/
⏳ Atlas narratif : à reprendre après Armand validation (priorité business)
⏳ Cockpit burst widget : à scheduler quand bande passante dispo
⏳ RAGAS V2 bench : à scheduler avec vLLM stable
