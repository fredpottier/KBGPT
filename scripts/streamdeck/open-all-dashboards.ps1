# Stream Deck - Open All Dashboards in Chrome
$urls = @(
    "http://localhost:3000",           # Frontend
    "http://localhost:8000/docs",      # API Swagger
    "http://localhost:6333/dashboard", # Qdrant
    "http://localhost:7474",           # Neo4j Browser
    "http://localhost:3001",           # Grafana
    "http://localhost:8501"            # Streamlit UI
)

# Ouvrir Chrome avec tous les onglets
$chromeArgs = $urls -join " "
Start-Process "chrome" -ArgumentList $chromeArgs

Write-Host "Chrome ouvert avec tous les dashboards!" -ForegroundColor Green
