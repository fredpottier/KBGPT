# ADR — Confidence d'ingestion et échec explicite

*Date : 30 avril 2026*
*Statut : Proposé pour test client*

## Contexte

OSMOSIS doit garantir au compliance officer que l'information indexée est fiable. Aujourd'hui, l'ingestion n'a pas de mécanisme explicite de "rejet" : si le LLM extracteur produit du JSON dégénéré (cas WEF Presidio observé), le système persiste quelques claims partiels sans signaler l'échec qualitatif.

## Décision

### Seuils de qualité d'ingestion (validators post-extract)

Chaque doc ingéré doit passer 4 validators :

| Validator | Métrique | Seuil minimum | Action si échec |
|---|---|---|---|
| **JSON validity** | % batches LLM avec JSON valide | ≥ 95% | Retry avec Qwen3-235B fallback |
| **Claim density** | claims / (kchars full_text) | ≥ 0.5 / 1k chars | Quarantine + log |
| **Cross-corpus contamination** | claims mentionnant entités hors-doc | < 10% | Reject doc, log warning |
| **ApplicabilityFrame V2 fields** | fields non-null / 7 axes | ≥ 4 / 7 | Quarantine + log |

### États du doc post-ingestion

```
ingested_ok       : 4/4 validators OK
ingested_warning  : 1 validator échoué, claims persistés mais flag warning
quarantined       : 2+ validators échoués, claims NON persistés, doc dans /docs_quarantine/
rejected          : JSON validity < 50%, doc déplacé vers /docs_failed/ avec log d'échec
```

### Surfacement au user

- UI Cockpit : badge sur chaque doc ingéré (vert/orange/rouge)
- Mode Audit : liste des docs en quarantine avec raisons
- API `/api/admin/ingestion_health` retourne le résumé

### Retry policy

- Quarantine + 1 retry automatique avec Qwen3-235B (fallback model)
- Si retry échoue → rejected, alerte admin (notification UI)
- L'humain peut force-import manuellement après inspection

## Conséquences

✅ Le compliance officer voit immédiatement quels docs sont fiables vs douteux
✅ Pas de claims pollués qui dégradent silencieusement le KG
⚠️ Coût : un cycle de retry sur Qwen3-235B ≈ 2× le budget extraction
⚠️ Implémentation : nécessite refactor pipeline post-extract pour insérer les validators

## Alternatives rejetées

- **Tout passer sans validation** : statut quo, mais incompatible avec la mission "vérité fiable"
- **Validation manuelle obligatoire** : trop lourd, casse l'autonomie du système
- **Reject silencieux** : pas d'apprentissage pour le user, frustrant en debug

## Migration

1. Ajouter les 4 validators dans `src/knowbase/ingestion/quality/`
2. Pipeline post-extract → invoquer chaque validator + écrire score dans DocumentContext.ingestion_health
3. UI Cockpit : nouvelle widget "Ingestion Health" lisant DocumentContext.ingestion_health
4. Rétroactif sur les 17 docs aerospace_compliance + 71 docs réglementaires existants
