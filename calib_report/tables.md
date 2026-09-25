## Near-half ground error per stage (median / 95th percentile, cm)

| Stage | Kept | Broadcast | Wimbledon | Delhi | Arthur Ashe | Naples | Hanoi | Val-d'Oingt |
|---|---|---|---|---|---|---|---|---|
| 00 Baseline | yes | 9 / 16 | 4 / 5 | **wrong** (0.9 m) | 6 / 9 | 5 / 18 | **wrong** (8.3 m) | refused |
| 01 Ambiguous-angle band | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 8 / 14 | **wrong** (8.3 m) | refused |
| 02 Refine top 8 candidates (rejected) | no | 9 / 16 | **wrong** (84 m) | 9 / 13 | 6 / 9 | 8 / 14 | **wrong** (8.3 m) | refused |
| 03 Band lines fill leftover slots | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 18 | **wrong** (8.3 m) | refused |
| 04 Refinement outline guard | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 18 | **wrong** (8.3 m) | refused |
| 05 Score partially visible courts | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 18 | **wrong** (12 m) | wrong fit* |
| 06 Vanishing-point line families | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 18 | 11 / 42 | wrong fit* |
| 07 Refine against far half too (rejected) | no | 10 / 19 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 17 | 10 / 33 | wrong fit* |
| 08 Stricter bar for partial views | yes | 9 / 16 | 4 / 5 | 7 / 18 | 6 / 9 | 5 / 18 | 11 / 42 | refused |

## Baseline vs final

| Photo | Before: near half | After: near half | Before: far half | After: far half |
|---|---|---|---|---|
| Broadcast | 9 / 16 | 9 / 16 | 13 / 35 | 13 / 35 |
| Wimbledon | 4 / 5 | 4 / 5 | 4 / 5 | 4 / 5 |
| Delhi | **wrong** (0.9 m) | 7 / 18 | **wrong** (0.9 m) | 13 / 23 |
| Arthur Ashe | 6 / 9 | 6 / 9 | 4 / 6 | 4 / 6 |
| Naples | 5 / 18 | 5 / 18 | 31 / 58 | 31 / 58 |
| Hanoi | **wrong** (8.3 m) | 11 / 42 | **wrong** (18 m) | 120 / 213 |
| Val-d'Oingt | refused | refused | refused | refused |
