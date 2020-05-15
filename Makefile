build:
	@docker-compose build

start:
	@docker-compose run --rm api python3 manage.py migrate
	@docker-compose run --rm api python3 manage.py collectstatic --noinput
	@docker-compose run --rm api python3 manage.py createsuperuser
	@docker-compose up

stop:
	@docker-compose down

import:
	@docker-compose run --rm api python3 manage.py cleardb
	@docker-compose run --rm api ./manage.py shell --command="from stockmanagement.importer import run; run()"

upgrade:
	git submodule update --remote