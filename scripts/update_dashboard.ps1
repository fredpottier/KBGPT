$path = "C:\Projects\SAP_KB\monitoring\dashboards\phase_1_8_metrics.json"
$dashboard = Get-Content $path -Raw | ConvertFrom-Json

$before = $dashboard.panels.Count
Write-Host "Panels avant: $before"

# Remove obsolete panels
$dashboard.panels = @($dashboard.panels | Where-Object {
    $_.title -notmatch 'LOW_QUALITY_NER' -and
    $_.title -notmatch 'LLM-Judge' -and
    $_.title -notmatch 'LLM-as-a-Judge'
})

$after = $dashboard.panels.Count
$removed = $before - $after
Write-Host "Panels après: $after"
Write-Host "Panels supprimés: $removed"

# Find max ID and Y
$maxId = ($dashboard.panels | Measure-Object -Property id -Maximum).Maximum
$maxY = 0
foreach ($p in $dashboard.panels) {
    if ($p.gridPos) {
        $y = $p.gridPos.y + $p.gridPos.h
        if ($y -gt $maxY) { $maxY = $y }
    }
}

$nextId = $maxId + 1
Write-Host "Next ID: $nextId"
Write-Host "Next Y: $maxY"

# Create new panels
$fusionPanel = @{
    datasource = @{
        type = "loki"
        uid = "loki"
    }
    description = "Taux de fusion: concepts fusionnés / total concepts (SmartConceptMerger)"
    fieldConfig = @{
        defaults = @{
            color = @{ mode = "thresholds" }
            mappings = @()
            max = 100
            min = 0
            thresholds = @{
                mode = "absolute"
                steps = @(
                    @{ color = "red"; value = $null },
                    @{ color = "yellow"; value = 10 },
                    @{ color = "green"; value = 30 }
                )
            }
            unit = "percent"
        }
    }
    gridPos = @{
        h = 8
        w = 6
        x = 0
        y = $maxY
    }
    id = $nextId
    options = @{
        orientation = "auto"
        reduceOptions = @{
            calcs = @("lastNotNull")
            fields = ""
            values = $false
        }
        showThresholdLabels = $false
        showThresholdMarkers = $true
    }
    pluginVersion = "10.0.0"
    targets = @(
        @{
            datasource = @{ type = "loki"; uid = "loki" }
            editorMode = "code"
            expr = '{service="app"} |~ "\\[OSMOSE:Fusion\\].*fusion_rate" | pattern "<_> fusion_rate=<rate>%" | unwrap rate'
            queryType = "range"
            refId = "A"
        }
    )
    title = "Fusion Rate"
    type = "gauge"
}

$domainPanel = @{
    datasource = @{
        type = "loki"
        uid = "loki"
    }
    description = "Nombre d'injections DomainContext dans les prompts (enrichissement SAP)"
    fieldConfig = @{
        defaults = @{
            color = @{ mode = "palette-classic" }
            mappings = @()
            thresholds = @{
                mode = "absolute"
                steps = @(@{ color = "green"; value = $null })
            }
            unit = "short"
        }
    }
    gridPos = @{
        h = 8
        w = 6
        x = 6
        y = $maxY
    }
    id = ($nextId + 1)
    options = @{
        legend = @{
            calcs = @()
            displayMode = "list"
            placement = "bottom"
        }
        tooltip = @{
            mode = "single"
            sort = "none"
        }
    }
    pluginVersion = "10.0.0"
    targets = @(
        @{
            datasource = @{ type = "loki"; uid = "loki" }
            editorMode = "code"
            expr = 'sum(count_over_time({service="app"} |~ "DomainContext injected" [$__range]))'
            queryType = "range"
            refId = "A"
        }
    )
    title = "DomainContext Injections"
    type = "stat"
}

$gatekeeperPanel = @{
    datasource = @{
        type = "loki"
        uid = "loki"
    }
    description = "Taux de promotion par Gatekeeper: concepts promus / total évalués"
    fieldConfig = @{
        defaults = @{
            color = @{ mode = "thresholds" }
            mappings = @()
            max = 100
            min = 0
            thresholds = @{
                mode = "absolute"
                steps = @(
                    @{ color = "red"; value = $null },
                    @{ color = "yellow"; value = 40 },
                    @{ color = "green"; value = 60 }
                )
            }
            unit = "percent"
        }
    }
    gridPos = @{
        h = 8
        w = 6
        x = 12
        y = $maxY
    }
    id = ($nextId + 2)
    options = @{
        orientation = "auto"
        reduceOptions = @{
            calcs = @("lastNotNull")
            fields = ""
            values = $false
        }
        showThresholdLabels = $false
        showThresholdMarkers = $true
    }
    pluginVersion = "10.0.0"
    targets = @(
        @{
            datasource = @{ type = "loki"; uid = "loki" }
            editorMode = "code"
            expr = '{service="app"} |~ "\\[OSMOSE:Metrics\\].*promotion_rate" | pattern "<_> promotion_rate=<rate>%" | unwrap rate'
            queryType = "range"
            refId = "A"
        }
    )
    title = "Gatekeeper Promotion Rate"
    type = "gauge"
}

$conceptsPanel = @{
    datasource = @{
        type = "loki"
        uid = "loki"
    }
    description = "Distribution des concepts par type (ENTITY, PRODUCT, TECHNOLOGY, etc.)"
    fieldConfig = @{
        defaults = @{
            color = @{ mode = "palette-classic" }
            mappings = @()
        }
    }
    gridPos = @{
        h = 8
        w = 6
        x = 18
        y = $maxY
    }
    id = ($nextId + 3)
    options = @{
        legend = @{
            displayMode = "list"
            placement = "bottom"
        }
        pieType = "pie"
        tooltip = @{
            mode = "single"
            sort = "none"
        }
    }
    pluginVersion = "10.0.0"
    targets = @(
        @{
            datasource = @{ type = "loki"; uid = "loki" }
            editorMode = "code"
            expr = 'sum by (type) (count_over_time({service="app"} |~ "\\[OSMOSE:Concept\\].*type=" | pattern "<_> type=<type>" [$__range]))'
            queryType = "range"
            refId = "A"
        }
    )
    title = "Concepts by Type"
    type = "piechart"
}

# Add new panels
$dashboard.panels += $fusionPanel
$dashboard.panels += $domainPanel
$dashboard.panels += $gatekeeperPanel
$dashboard.panels += $conceptsPanel

Write-Host "✅ 4 nouveaux panels ajoutés"

# Save
$dashboard | ConvertTo-Json -Depth 50 | Set-Content $path -Encoding UTF8

Write-Host "🎉 Dashboard mis à jour avec succès!"
Write-Host "   Total panels: $($dashboard.panels.Count)"
