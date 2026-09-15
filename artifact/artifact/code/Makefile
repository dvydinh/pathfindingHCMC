.PHONY: up down seed storm dev test eval demo freeze fetch gazetteer env-refresh

up:
	docker compose up -d --build

down:
	docker compose down

fetch:            ## download raw OSM + DEM + ambient snapshot into data/raw (network required once)
	docker compose run --rm api python scripts/fetch_raw.py
	docker compose run --rm api python scripts/fetch_env.py
	docker compose run --rm api python scripts/fetch_charging.py

env-refresh:      ## re-fetch the ambient snapshot only (real weather/air data ages)
	docker compose run --rm api python scripts/fetch_env.py

seed:             ## build graph, attach terrain, gazetteer, load PostGIS
	docker compose run --rm api python scripts/build_graph.py
	docker compose run --rm api python scripts/attach_terrain.py
	docker compose run --rm api python scripts/build_gazetteer.py
	docker compose run --rm api python scripts/seed.py

gazetteer:        ## rebuild place names only (safe: never invalidates a scenario)
	docker compose run --rm api python scripts/build_gazetteer.py

storm:            ## precompute scenario ensemble -> data/scenarios/
	docker compose run --rm api python -m app.sim.storm

dev:
	cd apps/web && npm run dev

test:
	docker compose run --rm api pytest tests -q
	cd apps/web && npm run typecheck

eval:
	docker compose run --rm api python scripts/replay_eval.py

demo: up
	@docker compose exec -T db psql -U duongan -d duongan -tc "SELECT count(*) FROM edges" >/dev/null 2>&1 || 	  (echo "restoring DB snapshot..." && gunzip -c data/snapshot.sql.gz | docker compose exec -T db psql -q -U duongan duongan)
	cd apps/web && npm run build && npm run preview

freeze:
	docker compose exec -T db pg_dump -U duongan duongan | gzip > data/snapshot.sql.gz
	git tag -f demo-freeze
