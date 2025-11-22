"""
Script pour ajouter de nouveaux panels au dashboard Grafana OSMOSE.

Panels ajoutés:
- 🔀 Fusion Rate (concepts fusionnés vs préservés)
- 🌊 DomainContext Injections Count
- 🚪 Gatekeeper Promotion Rate
- 📊 Concepts by Type Distribution

Supprime aussi les panels obsolètes:
- LOW_QUALITY_NER Detection
- LLM-as-a-Judge Validations
"""

import json
import sys
from pathlib import Path

# Chemin dashboard
DASHBOARD_PATH = Path(__file__).parent.parent / "monitoring" / "dashboards" / "phase_1_8_metrics.json"


def load_dashboard():
    """Charge le dashboard JSON."""
    with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_dashboard(dashboard):
    """Sauvegarde le dashboard JSON."""
    with open(DASHBOARD_PATH, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)


def remove_obsolete_panels(dashboard):
    """Supprime les panels obsolètes LOW_QUALITY_NER et LLM-Judge."""
    panels_before = len(dashboard['panels'])

    # Filtrer panels obsolètes par titre
    dashboard['panels'] = [
        p for p in dashboard['panels']
        if "LOW_QUALITY_NER" not in p.get('title', '')
        and "LLM-Judge" not in p.get('title', '')
        and "LLM-as-a-Judge" not in p.get('title', '')
    ]

    panels_after = len(dashboard['panels'])
    removed = panels_before - panels_after

    print(f"✅ {removed} panels obsolètes supprimés ({panels_before} → {panels_after})")
    return removed


def get_next_id(dashboard):
    """Trouve le prochain ID disponible."""
    max_id = max(p.get('id', 0) for p in dashboard['panels'])
    return max_id + 1


def get_next_y_position(dashboard):
    """Trouve la prochaine position Y disponible."""
    max_y = 0
    for panel in dashboard['panels']:
        gridPos = panel.get('gridPos', {})
        panel_bottom = gridPos.get('y', 0) + gridPos.get('h', 0)
        max_y = max(max_y, panel_bottom)
    return max_y


def create_fusion_rate_panel(panel_id, y_pos):
    """Panel: Fusion Rate (concepts fusionnés vs préservés)."""
    return {
        "datasource": {
            "type": "loki",
            "uid": "loki"
        },
        "description": "Taux de fusion: concepts fusionnés / total concepts (SmartConceptMerger)",
        "fieldConfig": {
            "defaults": {
                "color": {
                    "mode": "thresholds"
                },
                "mappings": [],
                "max": 100,
                "min": 0,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 10},
                        {"color": "green", "value": 30}
                    ]
                },
                "unit": "percent"
            }
        },
        "gridPos": {
            "h": 8,
            "w": 6,
            "x": 0,
            "y": y_pos
        },
        "id": panel_id,
        "options": {
            "orientation": "auto",
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False
            },
            "showThresholdLabels": False,
            "showThresholdMarkers": True
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "datasource": {"type": "loki", "uid": "loki"},
                "editorMode": "code",
                "expr": "{service=\"app\"} |~ \"\\\\[OSMOSE:Fusion\\\\].*fusion_rate\" | pattern \"<_> fusion_rate=<rate>%\" | unwrap rate",
                "queryType": "range",
                "refId": "A"
            }
        ],
        "title": "🔀 Fusion Rate",
        "type": "gauge"
    }


def create_domain_context_panel(panel_id, y_pos):
    """Panel: DomainContext Injections Count."""
    return {
        "datasource": {
            "type": "loki",
            "uid": "loki"
        },
        "description": "Nombre d'injections DomainContext dans les prompts (enrichissement SAP)",
        "fieldConfig": {
            "defaults": {
                "color": {
                    "mode": "palette-classic"
                },
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None}
                    ]
                },
                "unit": "short"
            }
        },
        "gridPos": {
            "h": 8,
            "w": 6,
            "x": 6,
            "y": y_pos
        },
        "id": panel_id,
        "options": {
            "legend": {
                "calcs": [],
                "displayMode": "list",
                "placement": "bottom"
            },
            "tooltip": {
                "mode": "single",
                "sort": "none"
            }
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "datasource": {"type": "loki", "uid": "loki"},
                "editorMode": "code",
                "expr": "sum(count_over_time({service=\"app\"} |~ \"DomainContext injected\" [$__range]))",
                "queryType": "range",
                "refId": "A"
            }
        ],
        "title": "🌊 DomainContext Injections",
        "type": "stat"
    }


def create_gatekeeper_panel(panel_id, y_pos):
    """Panel: Gatekeeper Promotion Rate."""
    return {
        "datasource": {
            "type": "loki",
            "uid": "loki"
        },
        "description": "Taux de promotion par Gatekeeper: concepts promus / total évalués",
        "fieldConfig": {
            "defaults": {
                "color": {
                    "mode": "thresholds"
                },
                "mappings": [],
                "max": 100,
                "min": 0,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 40},
                        {"color": "green", "value": 60}
                    ]
                },
                "unit": "percent"
            }
        },
        "gridPos": {
            "h": 8,
            "w": 6,
            "x": 12,
            "y": y_pos
        },
        "id": panel_id,
        "options": {
            "orientation": "auto",
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False
            },
            "showThresholdLabels": False,
            "showThresholdMarkers": True
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "datasource": {"type": "loki", "uid": "loki"},
                "editorMode": "code",
                "expr": "{service=\"app\"} |~ \"\\\\[OSMOSE:Metrics\\\\].*promotion_rate\" | pattern \"<_> promotion_rate=<rate>%\" | unwrap rate",
                "queryType": "range",
                "refId": "A"
            }
        ],
        "title": "🚪 Gatekeeper Promotion Rate",
        "type": "gauge"
    }


def create_concepts_by_type_panel(panel_id, y_pos):
    """Panel: Concepts by Type Distribution (pie chart)."""
    return {
        "datasource": {
            "type": "loki",
            "uid": "loki"
        },
        "description": "Distribution des concepts par type (ENTITY, PRODUCT, TECHNOLOGY, etc.)",
        "fieldConfig": {
            "defaults": {
                "color": {
                    "mode": "palette-classic"
                },
                "mappings": []
            }
        },
        "gridPos": {
            "h": 8,
            "w": 6,
            "x": 18,
            "y": y_pos
        },
        "id": panel_id,
        "options": {
            "legend": {
                "displayMode": "list",
                "placement": "bottom"
            },
            "pieType": "pie",
            "tooltip": {
                "mode": "single",
                "sort": "none"
            }
        },
        "pluginVersion": "10.0.0",
        "targets": [
            {
                "datasource": {"type": "loki", "uid": "loki"},
                "editorMode": "code",
                "expr": "sum by (type) (count_over_time({service=\"app\"} |~ \"\\\\[OSMOSE:Concept\\\\].*type=\" | pattern \"<_> type=<type>\" [$__range]))",
                "queryType": "range",
                "refId": "A"
            }
        ],
        "title": "📊 Concepts by Type",
        "type": "piechart"
    }


def main():
    print("🔧 Modification du dashboard Grafana OSMOSE...")

    # Charger dashboard
    dashboard = load_dashboard()
    print(f"📄 Dashboard chargé: {len(dashboard['panels'])} panels existants")

    # Supprimer panels obsolètes
    removed_count = remove_obsolete_panels(dashboard)

    # Préparer nouveaux panels
    next_id = get_next_id(dashboard)
    y_pos = get_next_y_position(dashboard)

    new_panels = [
        ("🔀 Fusion Rate", create_fusion_rate_panel(next_id, y_pos)),
        ("🌊 DomainContext Injections", create_domain_context_panel(next_id + 1, y_pos)),
        ("🚪 Gatekeeper Promotion Rate", create_gatekeeper_panel(next_id + 2, y_pos)),
        ("📊 Concepts by Type", create_concepts_by_type_panel(next_id + 3, y_pos))
    ]

    # Ajouter nouveaux panels
    for title, panel in new_panels:
        dashboard['panels'].append(panel)
        print(f"✅ Panel ajouté: {title} (ID: {panel['id']}, y={panel['gridPos']['y']})")

    # Sauvegarder
    save_dashboard(dashboard)

    print(f"\n🎉 Dashboard mis à jour avec succès!")
    print(f"   - Panels supprimés: {removed_count}")
    print(f"   - Panels ajoutés: {len(new_panels)}")
    print(f"   - Total panels: {len(dashboard['panels'])}")
    print(f"\n📍 Fichier: {DASHBOARD_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Erreur: {e}", file=sys.stderr)
        sys.exit(1)
