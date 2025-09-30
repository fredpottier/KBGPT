# 🎯 Guide Interface Utilisateur Gouvernance Facts - Phase 3

## 📍 Accès aux Pages de Gouvernance

### URL d'accès principal
**http://localhost:3000/governance**

### Menu de Navigation

La nouvelle section "**Gouvernance**" est maintenant accessible via :

1. **Sidebar** (navigation latérale gauche) - Icône ✓ CheckCircle
2. **TopNavigation** (barre de navigation supérieure) - Lien "Gouvernance"

Position dans le menu : **Chat > Documents > Gouvernance > Administration**

---

## 🎨 Pages Disponibles

### 1. Dashboard Principal
**URL**: http://localhost:3000/governance

**Fonctionnalités** :
- 📊 Statistiques globales (total facts, en attente, approuvés, conflits, rejetés)
- 📈 Métriques de qualité (taux d'approbation, taux de conflits, facts en attente)
- 🔗 Actions rapides vers les autres pages
- 🏷️ Badge du groupe multi-tenant actif

---

### 2. Facts en Attente
**URL**: http://localhost:3000/governance/pending

Liste des facts avec statut "proposed" nécessitant validation.

---

### 3. Résolution des Conflits
**URL**: http://localhost:3000/governance/conflicts

Interface pour résoudre les conflits détectés entre facts contradictoires.

---

### 4. Tous les Facts
**URL**: http://localhost:3000/governance/facts

Liste paginée de tous les facts avec filtres avancés.

---

**Date de création** : 29 septembre 2025
**Version** : 1.0.0
**Statut** : ✅ Production Ready
