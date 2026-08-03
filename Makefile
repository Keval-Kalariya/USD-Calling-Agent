.PHONY: install dev

install:
	python -m venv backend\venv
	backend\venv\Scripts\python -m pip install -r requirements.txt

dev:
	backend\venv\Scripts\honcho start -f Procfile
