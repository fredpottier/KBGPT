@echo off
docker compose stop app
docker compose rm -f app
docker compose up -d app