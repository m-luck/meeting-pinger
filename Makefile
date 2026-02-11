dev-install:
	poetry install

run:
	poetry run python main.py

auth:
	poetry run python -c "from meeting_pinger.calendar_client import CalendarClient; from meeting_pinger.config import Settings; c = CalendarClient(Settings()); c.authenticate(); print('Auth complete')"

print-token:
	@poetry run python -c "import json; print(open('credentials/token.json').read().strip())"

deploy:
	./deploy.sh
