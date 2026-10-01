VENV ?= .venv
PY   := $(VENV)/bin/python
PORT ?= 8100

TEST_PORT ?= 8101
TEST_DB   ?= barber-test.db

.PHONY: install run run-test test lock hooks docker-up docker-down reset-db reset-test-db

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

hooks:          ## once per clone: secret scan and lint on every commit
	$(VENV)/bin/pre-commit install

reset-db:       ## delete YOUR local database; the next `make run` re-seeds it
	rm -f barber.db barber.db-wal barber.db-shm

reset-test-db:  ## delete the test copy's database only; the next `make run-test` re-seeds it
	rm -f $(TEST_DB) $(TEST_DB)-wal $(TEST_DB)-shm

docker-up:      ## run the API in a container on port 8100
	docker compose up --build -d

docker-down:
	docker compose down
