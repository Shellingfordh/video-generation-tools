build-app:
	./build_mac_app.sh

build-cli:
	./venv/bin/pyinstaller --onefile --name VideoGeneratorCLI videogen_cli.py

run-cli:
	python3 videogen_cli.py

venv:
	python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt

.PHONY: build-app build-cli run-cli venv
