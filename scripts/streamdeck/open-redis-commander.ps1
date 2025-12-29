# Stream Deck - Launch Redis Commander
# Verifie si le container existe deja
$existing = docker ps -a --filter "name=redis-commander" --format "{{.Names}}"

if ($existing -eq "redis-commander") {
    # Container existe, verifier s'il tourne
    $running = docker ps --filter "name=redis-commander" --format "{{.Names}}"
    if ($running -eq "redis-commander") {
        Write-Host "Redis Commander deja en cours..." -ForegroundColor Green
    } else {
        Write-Host "Demarrage Redis Commander..." -ForegroundColor Cyan
        docker start redis-commander
    }
} else {
    # Creer et lancer le container
    Write-Host "Installation et demarrage de Redis Commander..." -ForegroundColor Cyan
    docker run -d `
        --name redis-commander `
        --network knowbase_network `
        -p 8081:8081 `
        -e REDIS_HOSTS=local:knowbase-redis:6379 `
        rediscommander/redis-commander:latest
}

# Attendre un peu et ouvrir le navigateur
Start-Sleep -Seconds 2
Start-Process "http://localhost:8081"
