# Docker commands

```bash
# local dependencies (Postgres, MinIO, Jaeger)
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml down

# build and run the API image
docker build -f docker/Dockerfile -t docintel:dev .
docker run --rm -p 8000:8000 --env-file config/.env docintel:dev
```
