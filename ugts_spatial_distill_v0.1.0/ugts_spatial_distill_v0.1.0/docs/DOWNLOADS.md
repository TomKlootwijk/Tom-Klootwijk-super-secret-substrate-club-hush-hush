# Manual Downloads

Snapshot date: 2026-08-16. Verify upstream licences and current checksums before
production use.

## 1. Minimal semantic teacher

```text
Repository: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF
File: Qwen3-Embedding-0.6B-Q8_0.gguf
Listed size: 639 MB
Licence: Apache-2.0 according to model card
Purpose: offline multilingual node embeddings
```

Start with a manually downloaded file:

```powershell
llama-server.exe -m D:\models\Qwen3-Embedding-0.6B-Q8_0.gguf --embedding --pooling last -ub 8192 --port 8080
```

## 2. Small Dutch place dataset

```text
https://download.geonames.org/export/dump/NL.zip
Listed size on 2026-08-16: 709 KiB
Purpose: stable place identities, names, feature classes and coordinates
```

## 3. Richer Flevoland map extract

```text
https://download.geofabrik.de/europe/netherlands/flevoland-latest.osm.pbf
August 2026 snapshot: about 34.5 MB
Purpose: roads, buildings, amenities and tagged spatial assets
```

The OSM adapter is optional and requires `osmium`. Keep attribution and licence
metadata with every derivative.

## Disk-conscious sequence

1. Run the bundled synthetic graph and checkpoint: no download.
2. Add GeoNames NL.zip: less than 1 MB.
3. Add Qwen 0.6B Q8: about 639 MB.
4. Add Flevoland OSM only when road/building topology is needed: about 35 MB.
5. Do not download a 20+ GB chat teacher until the compact pipeline and labels
   have shown value.
