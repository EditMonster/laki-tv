#!/bin/sh
# Rakentaa kiinteän testisivun (data 30.9.2026) ja ajaa kaikki testisarjat.
cd "$(dirname "$0")/.." || exit 1
python3 build.py >/dev/null || exit 1
python3 test/shift_fixture.py || exit 1
python3 tools/lakitv.py inject preview.html test/fixture_data.json test/fixture.html --force >/dev/null || exit 1
rc=0
for t in test/v7_test.py test/interact.py test/en_test.py test/new_test.py test/search_test.py test/sec_test.py test/v9_test.py test/v11_test.py test/tool_test.py test/live_test.py test/onepage_test.py; do
  printf '%s: ' "$t"; python3 "$t" 2>&1 | tail -1 || rc=1
done
for l in fi sv en; do printf 'sweep %s: ' "$l"; python3 test/sweep.py "$l" 2>&1 | grep -E '"(errors|overlaps|jsErrors)"' | tr -d '\n '; echo; done
printf 'overlap_filter: '; python3 test/overlap_filter.py 2>&1 | tail -1
printf 'site_test: '; python3 test/site_test.py 2>&1 | tail -1
exit $rc
