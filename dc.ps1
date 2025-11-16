# Alias docker-compose pour KnowWhere/OSMOSE
# Usage: ./dc.ps1 ps | ./dc.ps1 up -d | ./dc.ps1 logs app --tail 50
docker-compose -f docker-compose.infra.yml -f docker-compose.yml $args
