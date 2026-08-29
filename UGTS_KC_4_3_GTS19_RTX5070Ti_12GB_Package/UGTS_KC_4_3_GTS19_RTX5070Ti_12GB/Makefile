.PHONY: test fixtures cpu acceptance manifest

PYTHON ?= python

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

fixtures:
	PYTHONPATH=src $(PYTHON) scripts/generate_fixtures.py

cpu:
	cmake -S cpp -B build-cpu -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
	cmake --build build-cpu --config Release
	ctest --test-dir build-cpu --output-on-failure

acceptance:
	./codex/acceptance.sh

manifest:
	$(PYTHON) scripts/make_manifest.py
	$(PYTHON) scripts/verify_release.py
