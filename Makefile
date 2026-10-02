VENV ?= .venv
PY   := $(VENV)/bin/python
PORT ?= 8100

TEST_PORT ?= 8101
TEST_DB   ?= barber-test.db

.PHONY: install run run-test test lock migration hooks docker-up docker-down reset-db reset-test-db

install:        ## create the venv and install the locked dependencies
	python3.13 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.lock.txt

run:            ## start the API on http://127.0.0.1:8100 (reads .env)
	@test -f .env || { echo "no .env - run: cp .env.example .env"; exit 1; }
	set -a; . ./.env; set +a; $(PY) -m uvicorn app.main:create_app --factory --port $(PORT) --workers 2

run-test:       ## a second copy for the QA suites, on 8101 with its own database, so they never touch yours
	@test -f .env || { echo "no .env - run: cp .env.example .env"; exit 1; }
	set -a; . ./.env; set +a; DATABASE_URL=sqlite:///./$(TEST_DB) $(PY) -m uvicorn app.main:create_app --factory --port $(TEST_PORT) --workers 2

test:           ## the product's own tests, including the two-worker race
	$(PY) -m pytest -q

lock:           ## after editing requirements.txt: re-resolve and commit both files
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m pip freeze > requirements.lock.txt

migration:      ## after changing app/models.py: make migration m="add phone" - then read the file it writes
	@test -n "$(m)" || { echo 'name the change: make migration m="add phone"'; exit 1; }
	@d=$$(mktemp -d) && trap 'rm -rf "$$d"' EXIT && \
	DATABASE_URL=sqlite:///$$d/m.db $(VENV)/bin/alembic upgrade head && \
	DATABASE_URL=sqlite:///$$d/m.db $(VENV)/bin/alembic revision --autogenerate -m "$(m)"

hooks:          ## once per clone: secret scan and lint on every commit
	$(VENV)/bin/pre-commit install

# Refuse to delete a database while a server on its port is still serving it:
# the server keeps running on a file that no longer exists, and the next start
# fails with "address already in use". It happened twice in one day.
define refuse_if_running
	@if lsof -nP -iTCP:$(1) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "a server is still running on port $(1) - stop it first (Ctrl+C in its tab), then run this again"; exit 1; fi
endef

reset-db:       ## delete YOUR local database; the next `make run` re-seeds it. Stop `make run` first
	$(call refuse_if_running,$(PORT))
	rm -f barber.db barber.db-wal barber.db-shm

reset-test-db:  ## delete the test copy's database only; the next `make run-test` re-seeds it. Stop it first
	$(call refuse_if_running,$(TEST_PORT))
	rm -f $(TEST_DB) $(TEST_DB)-wal $(TEST_DB)-shm

docker-up:      ## run the API in a container on port 8100
	docker compose up --build -d

docker-down:
	docker compose down
