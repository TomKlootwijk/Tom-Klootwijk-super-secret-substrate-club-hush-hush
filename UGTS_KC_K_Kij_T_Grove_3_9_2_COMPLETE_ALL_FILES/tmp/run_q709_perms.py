from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import itertools
import json
import sys
import time

sys.path.insert(0, "tmp")
import polar_codeword_bench as benchmark  # noqa: E402


def main() -> None:
    names = [
        "q709_perm_" + "".join(map(str, permutation))
        for permutation in itertools.permutations(range(3))
        if permutation != (0, 1, 2)
    ]
    started = time.perf_counter()
    output = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(benchmark._run_candidate, name): name  # noqa: SLF001
            for name in names
        }
        for future in as_completed(futures):
            result = future.result()
            output.append(result)
            print(
                "PASS",
                result["candidate"],
                result["ugrice1_stream_bytes"],
                f"{result['elapsed_seconds']:.2f}s",
                flush=True,
            )
    output.sort(key=lambda item: item["ugrice1_stream_bytes"])
    print(
        json.dumps(
            {"elapsed_seconds": time.perf_counter() - started, "results": output},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
