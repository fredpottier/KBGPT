# ADR — Domain Pack lifecycle (versioning, validation, déploiement)

*Date : 30 avril 2026*
*Statut : Proposé pour test client*

## Contexte

Les Domain Packs (`aerospace_compliance`, `regulatory`, `biomedical`, etc.) portent les hints sémantiques injectés dans les prompts LLM (extracteurs, classifier, lifecycle). Aujourd'hui :

- Pas de versioning explicite — un changement de hint impacte rétroactivement tous les claims passés
- Pas de validation — un Domain Pack mal écrit (regex glissées en hint, contradictions internes) passe sans alerte
- Pas de stratégie déploiement — l'admin commit le manifest, pas de rollback simple

Pour un test client multi-pack (Armand a possiblement plusieurs domaines), il faut formaliser.

## Décision

### Versioning

Chaque Domain Pack manifest porte `schema_version` (déjà présent) **et** `pack_version` (nouveau, semver).

```json
{
  "schema_version": 1,
  "pack_version": "1.2.0",
  "name": "aerospace_compliance",
  "compatible_with_core": ">=2.0.0",
  ...
}
```

Lors d'un changement, bump pack_version :
- Patch (1.2.0→1.2.1) : correction d'un hint, pas de re-ingestion requise
- Minor (1.2.0→1.3.0) : ajout d'un nouveau hint, re-extraction recommandée pour bénéficier
- Major (1.2.0→2.0.0) : changement structurel, re-extraction obligatoire

### Validation pré-déploiement

Linter automatique avant commit :

| Règle | Vérification |
|---|---|
| **No regex/keywords** | Aucun hint ne doit contenir `[a-z]` patterns ou `re.compile` syntaxe |
| **Domain-agnostic phrasing** | Hints sémantiques en prose, pas de listes hardcodées |
| **Internal coherence** | Pas de contradictions entre hints du même pack |
| **Manifest schema valid** | pydantic validation contre `PackManifest` |

Outil : `scripts/validate_domain_pack.py <pack_name>` → exit code 0 si OK.

### Déploiement

3 environnements logiques :

```
manifest_active.json    : version en production
manifest_staging.json   : version en cours de test
manifest_archive/       : versions précédentes (rollback)
```

Process déploiement :
1. Modifier `manifest_staging.json`
2. Linter passe
3. Bench régression sur 5 docs représentatifs (compare claims V_old vs V_new)
4. Si pass → renommer `manifest_active.json → archive/v<old>.json` + `staging → active`
5. Backfill optionnel selon impact

Rollback : copier la version archive souhaitée en `active`.

### Tracking du pack utilisé par claim

Ajouter sur chaque Claim créé : `domain_pack_version` (string semver).

```cypher
CREATE (c:Claim {
  claim_id: $cid,
  ...,
  domain_pack: "aerospace_compliance",
  domain_pack_version: "1.2.0"
})
```

Permet d'auditer quel pack a produit quel claim, et de re-extraire sélectivement après upgrade.

## Conséquences

✅ Versioning clair, audit possible
✅ Validation pré-déploiement attrape les bugs de hint avant prod
✅ Rollback rapide
⚠️ Coût : nouvel attribut sur tous les Claim (Neo4j storage marginal)
⚠️ Process déploiement plus lourd (linter + bench)

## Alternatives rejetées

- **Pas de versioning** : statut quo, mais ingérable à >1 pack
- **Versioning automatique git-based** : pas standardisé, dépend du commit message
- **Re-extraction systématique** : trop coûteux à chaque modif

## Migration

1. Créer `scripts/validate_domain_pack.py`
2. Ajouter `pack_version` dans tous les manifests existants (aerospace_compliance v1.0.0)
3. Modifier `domain_packs/manager.py` pour propager `pack_version` aux extracteurs
4. Modifier ClaimPersister pour écrire `domain_pack_version` sur Claim
5. UI Admin : page `/admin/domain-packs` avec tableau version + validate button
