# Zero-valued texture alignment diagnostic and erratum

## Why this corpus exists

The original all-zero texture curve alternated between extremely high and low rates. A four-process 174-210 MiB sweep in 2 MiB steps showed an exact three-MiB rhythm: allocations divisible by 3 MiB reached 225-362 Glookup/s, while adjacent sizes reached only 17-21 Glookup/s without generic compression and 103-122 Glookup/s with it.

This rhythm follows packed-table arithmetic. When the allocation size is divisible by 3 MiB, the table contains an integer multiple of `2^18` twelve-byte groups and `2^22` logical entries. A compile-time control that removes one 12-byte group from each aligned table collapses the non-compressible texture rate by 12.3-19.2x and the generic rate by 2.1-3.2x.

The CPU address replay rules out a software coverage shortcut. For both 192 MiB and 192 MiB minus one group, all generated word indices remain in bounds, approximately 100% of 128-byte lines are visited, and each warp-step averages approximately 32 unique lines. The rate discontinuity is therefore triggered by exact entry-count/address arithmetic, not by a smaller replayed working set.

## Semantic disqualification

A packed all-one (`ones6`, words `0xFFFFFFFF`) control then invalidated the apparent texture result. At 4 and 192 MiB:

- global all-one rows validate with zero mismatches;
- periodic and entropy-dense texture rows validate with zero mismatches;
- all-one texture rows produce zero valid cold or hot payloads in every paired process;
- the mismatch-total probe records 35,893,872 wrong codes out of 36,175,872 timed checks at 4 MiB and 22,609,920 out of 36,175,872 at 192 MiB for each compression mode;
- the all-zero texture checker still reports success because zero is its expected value.

Consequently, the fast all-zero texture curve is a **zero-sentinel false positive**. It cannot be used as texture-cache capacity, compression yield or valid decoded-code throughput. The rows are retained to document the failure mode. Information-bearing periodic and entropy texture rows remain valid, and they show no generic-compression benefit.

## Corpus counts

- fine zero-only alignment sweep: four processes, 304 raw rows, 322,191,360 built-in validated payloads and 109,974,650,880 timed lookups;
- one-group-trim control: four processes, 112 raw rows, 118,702,080 built-in validation payloads and 40,516,976,640 timed lookups;
- exact address replay: 18,087,936 generated lookups per case across five geometry cases;
- nonzero mismatch probe: two sizes, three patterns, two paths and two compression modes, with explicit mismatch totals.

The zero-only payload count describes the original checker, not independent nonzero semantic validation. The one-group-trim validated-payload total is available in its aggregate JSON and is deliberately not promoted into a correctness claim here.

## Provenance

- original zero-sweep source SHA-256: `C8B68006404278DE9C01F394E9A4A5571335D16A8858FA9403512CC04BEC06C6`;
- original zero-sweep executable SHA-256: `9ECD2C4785B3836A2FC1B2342BC4F8268E2E67B6FF50F87488C3125EB8C0E057`;
- archived original source and executable are in `../cuda_vmm_compression_lut_isolated/artifacts/`;
- one-group-trim source SHA-256: `1E534F50902FDC5836A8EFB99151337E92722775BDF47138BD889A52BC74D740`;
- one-group-trim executable SHA-256: `67700EA58E2A919D42C359212A403E8E8B0AC3EC03722A558EB1C192836F6D80`;
- mismatch-total probe source SHA-256: `4440CEFFB8331F9401D0F4E4E917A5B7F225D2DCACB1C9BEC3C0E3AB76A659ED`;
- mismatch-total probe executable SHA-256: `D6D4331428315BF1655FE21CA7646F57CBEEB53EFD749FC7B3AB91EB1747E4BC`;
- address-replay tool SHA-256 at measurement: `63AC8B6F64284D98AA27B803BE80D0D696187322E19D8ACB12EB256D9864C3ED`.

This diagnostic does not identify a documented cache set, bank, partition or texture-unit implementation detail. It establishes an exact arithmetic trigger and, more importantly, rejects the zero-valued texture path as semantic evidence.
