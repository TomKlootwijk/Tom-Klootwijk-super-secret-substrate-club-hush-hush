.PHONY: test fixtures cpu acceptance evidence manifest

PYTHON ?= python

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

fixtures:
	PYTHONPATH=src $(PYTHON) scripts/generate_fixtures.py

cpu:
	cmake -S cpp -B build-cpu -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
	cmake --build build-cpu --config Release
	ctest --test-dir build-cpu --output-on-failure

acceptance:
	./codex/acceptance.sh

evidence:
	$(PYTHON) scripts/parity_gate.py evidence/local_m1_cpp_python_parity_v2_1m.json
	$(PYTHON) scripts/storage_gate.py --validate evidence/local_m2_storage_gate.json
	$(PYTHON) scripts/persistent_pndag_gate.py --validate evidence/local_m2_persistent_pndag_gate.json

manifest:
	$(PYTHON) scripts/make_manifest.py
	$(PYTHON) scripts/verify_release.py
