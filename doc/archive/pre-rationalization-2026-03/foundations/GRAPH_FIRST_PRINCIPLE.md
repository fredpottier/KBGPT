# Graph-First Principle

**Statut** : Invariant OSMOSE
**Dernière mise à jour** : 2026-01-06

---

## Principe

> **Le graphe est le routeur, les preuves sont textuelles.**

Le pipeline OSMOSE privilégie le graphe pour **structurer** et **délimiter** le contexte avant toute recherche dense. La recherche vectorielle sert ensuite à **valider** et **prouver** les faits identifiés par le graphe.

---

## Implications

- Le KG est interrogé **en premier** pour établir les chemins sémantiques et le scope.
- Les preuves textuelles (chunks, passages) sont **sélectionnées ensuite** pour étayer les relations.
- Le système doit dégrader gracieusement vers des réponses **anchored** ou **text-only** quand le graphe est incomplet.

---

## Référence

- Décision architecturale : [ADR-20260106-graph-first-architecture.md](../adr/ADR-20260106-graph-first-architecture.md)
