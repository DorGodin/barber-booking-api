VENV ?= .venv
PY   := $(VENV)/bin/python
PORT ?= 8100

.PHONY: install run test lock hooks docker-up docker-down reset-db

install:        ## create the venv and install the locked dependencies
	python3.13 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.lock.txt

run:            ## start the API on http://127.0.0.1:8100 (reads .env)
	@test -f .env || { echo "no .env - run: cp .env.example .env"; exit 1; }
	set -a; . ./.env; set +a; $(PY) -m uvicorn app.main:create_app --factory --port $(PORT) --workers 2

test:           ## the product's own tests, including the two-worker race
	$(PY) -m pytest -q

lock:           ## after editing requirements.txt: re-resolve and commit both files
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m pip freeze > requirements.lock.txt

hooks:          ## once per clone: secret scan and lint on every commit
	$(VENV)/bin/pre-commit install

reset-db:       ## delete the local database; the next start re-seeds it
	rm -f barber.db barber.db-wal barber.db-shm

docker-up:      ## run the API in a container on port 8100
	docker compose up --build -d

docker-down:
	docker compose down
