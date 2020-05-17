build:
	@docker-compose build

start:
	@docker-compose run --rm api python3 manage.py migrate
	@docker-compose run --rm api python3 manage.py collectstatic --noinput
	@docker-compose run --rm api python3 manage.py createsuperuser --noinput
	@docker-compose run --rm -v "$(shell pwd)/db:/tmp/db" api python3 manage.py loaddata /tmp/db/populatedb_data.json
	@docker-compose up

stop:
	@docker-compose down -v --remove-orphans

import:
	@docker-compose run --rm api python3 manage.py cleardb
	@docker-compose run --rm api python3 manage.py shell --command="from stockmanagement.importer import run; run()"
	@docker-compose run --rm api python3 manage.py dumpdata --indent 2 account product warehouse shipping plugins > ./db/populatedb_data.json

update:
	git submodule update --remote

upgrade:
	# Switching to a new submodule branch
	git submodule foreach --recursive git clean -xfd
	git submodule foreach --recursive git reset --hard
	git submodule update --init --recursive

# populate_data:
# 	@docker-compose run --rm api python3 manage.py cleardb
# 	@docker-compose run --rm -v "$(shell pwd)/db:/tmp/db" api python3 manage.py loaddata /tmp/db/dump.json