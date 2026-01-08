# OSMOSE - Principes Fondateurs

**Version** : 1.0
**Date** : 2026-01-06
**Statut** : Canonique

---

## 1. North Star (Domain-Agnostic)

> **Le graphe stocke et relie. Le domaine décide de ce qu'il montre et de ce qu'il croit.**

Ce principe fondateur garantit que :
- Le Knowledge Graph reste **agnostique** vis-à-vis du domaine fonctionnel.
- La **topologie** n'est jamais contrainte par des considérations métier.
- La **responsabilité d'exposition** est déléguée à une couche externe.

Voir les détails d'implémentation et les invariants dans :
- [`foundations/KG_AGNOSTIC_ARCHITECTURE.md`](./KG_AGNOSTIC_ARCHITECTURE.md)

---

## 2. Séparation stricte des responsabilités (5 couches)

Le système doit rester strictement découpé en couches, chacune avec ses invariants :

1. **Stockage** : toute relation plausible est persistée.
2. **Topologie** : toute relation persistée est navigable.
3. **Profil de visibilité** : filtrage comportemental universel (pas de règles métier).
4. **UI/API** : exposition graduée selon la maturité/fiabilité.
5. **Décision** : l'humain reste l'arbitre final.

Ce modèle est détaillé dans :
- [`foundations/KG_AGNOSTIC_ARCHITECTURE.md`](./KG_AGNOSTIC_ARCHITECTURE.md)

---

## 3. Épistémologie explicite (maturité cognitive)

OSMOSE doit traiter la connaissance comme un **continuum de maturité** plutôt qu'une vérité binaire.
Les états de maturité guident la gouvernance, l'exposition et la décision.

Voir :
- [`foundations/OSMOSE_COGNITIVE_MATURITY.md`](./OSMOSE_COGNITIVE_MATURITY.md)

---

## 4. KG comme couche mémoire (et non simple index)

Le KG n'est pas un index statique : il doit porter la mémoire, les liens, les preuves,
et permettre un raisonnement guidé.

Voir :
- [`foundations/OSMOSE_KG_AS_MEMORY_LAYER.md`](./OSMOSE_KG_AS_MEMORY_LAYER.md)

---

## 5. Gouvernance documentaire

- **Décisions** : consignées en ADR, indexées dans `doc/decisions/`.
- **Spécifications** : décrivent le « comment » (design cible), dans `doc/specs/`.
- **Tracking** : décrit l'état réel, dans `doc/tracking/`.
- **Research** : analyses et explorations, dans `doc/research/`.

Ces catégories sont définies et détaillées dans [`doc/README.md`](../README.md).
