# Manual Model and Data Downloads

No model or external dataset is downloaded by the package. `assets/manual_downloads.json` is the machine-readable manifest.

## Minimal disk configuration

### Semantic teacher only

```text
Qwen3-Embedding-0.6B-Q8_0.gguf
about 639 MB
SHA-256 06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439
```

Use this first. It is sufficient to replace the deterministic hash-vector smoke teacher with multilingual semantic vectors.

## Balanced local configuration

```text
Qwen3-Embedding-4B-Q4_K_M.gguf   about 2.497 GB
Qwen3-4B-Q4_K_M.gguf             about 2.5 GB
combined                          about 5 GB
```

Embedding file SHA-256:

```text
aaeddb737110a166dbc7155753bb60d8c3ba9a93e69938c18bf3fdd7f23f0381
```

Relation teacher SHA-256:

```text
7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5
```

This pair gives stronger semantic transfer while remaining modest on disk. Run one model at a time when VRAM headroom is important; teacher outputs persist after each pass.

## Model serving

Official Qwen GGUF pages document both the modern command and the standalone server:

```bash
llama serve -hf Qwen/Qwen3-Embedding-4B-GGUF:Q4_K_M
llama-server -hf Qwen/Qwen3-Embedding-4B-GGUF:Q4_K_M
```

For manually downloaded local files, the supplied scripts use `-m <path>` and start an OpenAI-compatible endpoint.

## Data

### GeoNames Netherlands

```text
NL.zip
roughly 709 KiB at package preparation time
```

GeoNames is useful for named persistent places and ontology labels. It is updated daily, so the package does not pin a permanent hash. Record the file date and a local SHA-256 in your experiment manifest.

### OpenStreetMap Flevoland

```text
flevoland-latest.osm.pbf
roughly 33–35 MB at package preparation time
```

Use the regional Flevoland extract rather than the full Netherlands file to minimize disk and ingestion cost. Geofabrik also publishes an MD5 sidecar for current PBF files.

## Manual verification

```bash
python scripts/verify_manual_asset.py \
  path/to/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --sha256 06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439
```

On PowerShell:

```powershell
Get-FileHash D:\models\Qwen3-Embedding-0.6B-Q8_0.gguf -Algorithm SHA256
```

## License reminder

- Official Qwen model repositories declare Apache-2.0 for the listed models.
- GeoNames requires attribution and publishes its own terms.
- OpenStreetMap data is governed by ODbL and requires attribution.
- llama.cpp, PyTorch, H3, ULTRA, and other tools retain their own licenses.

Always preserve the third-party source, model revision, quantization, file hash, prompt version, and embedding dimension alongside student training outputs.
