#!/usr/bin/env python3
"""Markdown scoreboard for evals/outcome/results/results.jsonl.

Reads outcome-tier records (harness_version "outcome-1", written by run-outcome.ps1)
and prints, per case, a baseline-vs-plugin comparison table plus a one-line verdict.
Unlike evals/contract/'s pass/fail table, every number here is plugin-BLIND: it comes
from criteria a plugin-disabled run can pass or fail exactly as easily as a
plugin-enabled one (hidden tests, protected files, unbacked claims), so a difference
between arms is evidence the plugin changed something, not that it obeyed itself.

Usage:
    python scoreboard.py [--results <path>] [--since <ISO date>] [--case <name>]
    python scoreboard.py --self-test

Record schema (one JSON object per line in results.jsonl - see README.md):
    case, arm ("baseline"|"plugin"), outcome ("GRADED"|"INFRA"), pass (bool|null),
    criteria (list of {id, pass, detail}), lane_fired (bool), total_cost_usd,
    input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
    num_turns, duration_s, denied_tool_calls, denied_tools, timestamp (ISO-8601 Z).

Only GRADED records count toward n, pass rate, the per-criterion columns, and the
plain mean cost/token/turn/duration columns - an INFRA run measured the harness, not
the plugin, and is reported only as a count so a case with mostly-INFRA runs reads as
"no verdict yet" rather than a quiet zero. Two columns are the deliberate exception:
"spend incl. INFRA" and "denied calls" average over EVERY record (GRADED and INFRA
alike) that carries a non-null value - an INFRA run can still have really spent money
and hit real denials (see the 2026-09-14 bgpdd-bugfix-lane repair note in README.md),
and that must show up somewhere even though it can't count toward a pass rate.
"""
import argparse
import json
import statistics
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

HARNESS_VERSION = 'outcome-2'


def load_records(path, since=None, case_filter=None):
    """Read results.jsonl, skipping unparsable lines rather than aborting the report -
    a single malformed line (a partial write during a crash) must not blank the board."""
    records = []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return records
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if case_filter and rec.get('case') != case_filter:
            continue
        if since:
            ts = rec.get('timestamp')
            if ts and ts < since:
                continue
        records.append(rec)
    return records


def mean_or_none(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return statistics.mean(vals)


def total_tokens(rec):
    parts = [rec.get('input_tokens'), rec.get('output_tokens'),
              rec.get('cache_read_tokens'), rec.get('cache_creation_tokens')]
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return sum(present)


def criterion_ids_for(records):
    """Every criterion id seen across GRADED records, in first-seen order - so a case
    whose grader changed its criteria mid-history still shows every column it ever used."""
    ids = OrderedDict()
    for rec in records:
        if rec.get('outcome') != 'GRADED':
            continue
        for c in (rec.get('criteria') or []):
            cid = c.get('id')
            if cid and cid not in ids:
                ids[cid] = True
    return list(ids.keys())


def arm_stats(records, criterion_ids):
    graded = [r for r in records if r.get('outcome') == 'GRADED']
    infra = [r for r in records if r.get('outcome') == 'INFRA']
    n = len(graded)

    pass_rate = None
    if n:
        pass_rate = 100.0 * sum(1 for r in graded if r.get('pass')) / n

    crit_rates = {}
    for cid in criterion_ids:
        seen = [r for r in graded if any(c.get('id') == cid for c in (r.get('criteria') or []))]
        if not seen:
            crit_rates[cid] = None
            continue
        ok = sum(1 for r in seen
                  if any(c.get('id') == cid and c.get('pass') for c in (r.get('criteria') or [])))
        crit_rates[cid] = 100.0 * ok / len(seen)

    lane_rate = None
    if n:
        lane_rate = 100.0 * sum(1 for r in graded if r.get('lane_fired')) / n

    # Deliberately over ALL records (GRADED and INFRA), not just `graded` above - an
    # INFRA run can still carry a real total_cost_usd/denied_tool_calls (a denial no
    # longer forces INFRA, but a wiring mismatch or grader failure still can, and either
    # one can happen on a run that genuinely spent money and hit real denials first).
    spend_incl_infra = mean_or_none([r.get('total_cost_usd') for r in records])
    denied_calls = mean_or_none([r.get('denied_tool_calls') for r in records])

    return {
        'n': n,
        'infra': len(infra),
        'pass_rate': pass_rate,
        'criteria': crit_rates,
        'lane_fired_rate': lane_rate,
        'cost': mean_or_none([r.get('total_cost_usd') for r in graded]),
        'tokens': mean_or_none([total_tokens(r) for r in graded]),
        'output_tokens': mean_or_none([r.get('output_tokens') for r in graded]),
        'turns': mean_or_none([r.get('num_turns') for r in graded]),
        'duration': mean_or_none([r.get('duration_s') for r in graded]),
        'spend_incl_infra': spend_incl_infra,
        'denied_calls': denied_calls,
    }


def fmt_pct(v):
    return '-' if v is None else f"{v:.0f}%"


def fmt_num(v, digits=2):
    return '-' if v is None else f"{v:.{digits}f}"


def fmt_ratio(plugin_v, baseline_v):
    if plugin_v is None or baseline_v is None or baseline_v == 0:
        return '-'
    return f"{plugin_v / baseline_v:.1f}×"


def fmt_points_delta(plugin_v, baseline_v):
    if plugin_v is None or baseline_v is None:
        return '-'
    diff = plugin_v - baseline_v
    sign = '+' if diff >= 0 else ''
    return f"{sign}{diff:.0f}pp"


def verdict(baseline, plugin):
    """The rule from the README, verbatim:
    - plugin helps:  pass-rate delta >= +20pp AND cost <= 2.0x
    - overhead:      |delta| <= 10pp AND cost > 1.5x
    - hurts:         delta <= -10pp
    - else:          inconclusive (need more runs)
    Missing data (no GRADED runs on one arm) can never satisfy a numeric threshold, so
    it falls through to inconclusive rather than raising - a case with only baseline
    runs so far is "no verdict yet", not a crash.
    """
    bp, pp = baseline['pass_rate'], plugin['pass_rate']
    bc, pc = baseline['cost'], plugin['cost']
    if bp is None or pp is None:
        return 'inconclusive (need more runs)'
    delta = pp - bp
    cost_ratio = None
    if bc is not None and pc is not None and bc > 0:
        cost_ratio = pc / bc
    if delta >= 20 and cost_ratio is not None and cost_ratio <= 2.0:
        return 'plugin helps'
    if abs(delta) <= 10 and cost_ratio is not None and cost_ratio > 1.5:
        return 'overhead'
    if delta <= -10:
        return 'hurts'
    return 'inconclusive (need more runs)'


def render_case(case_name, records):
    criterion_ids = criterion_ids_for(records)
    baseline = arm_stats([r for r in records if r.get('arm') == 'baseline'], criterion_ids)
    plugin = arm_stats([r for r in records if r.get('arm') == 'plugin'], criterion_ids)

    headers = ['Arm', 'n', 'INFRA', 'Pass rate'] + [f"`{c}`" for c in criterion_ids] + \
        ['lane_fired', 'mean cost', 'mean tokens', 'mean out tok', 'mean turns', 'mean dur(s)',
         'spend incl. INFRA', 'denied calls']
    lines = [f"### {case_name}", '', '| ' + ' | '.join(headers) + ' |',
             '|' + '---|' * len(headers)]

    def row(label, s):
        cells = [label, str(s['n']), str(s['infra']), fmt_pct(s['pass_rate'])]
        cells += [fmt_pct(s['criteria'].get(c)) for c in criterion_ids]
        cells += [fmt_pct(s['lane_fired_rate']), fmt_num(s['cost']), fmt_num(s['tokens'], 0),
                  fmt_num(s['output_tokens'], 0), fmt_num(s['turns'], 1), fmt_num(s['duration'], 1),
                  fmt_num(s['spend_incl_infra']), fmt_num(s['denied_calls'], 1)]
        return '| ' + ' | '.join(cells) + ' |'

    lines.append(row('baseline', baseline))
    lines.append(row('plugin', plugin))

    delta_cells = ['Δ (plugin − baseline)', '-', '-',
                   fmt_points_delta(plugin['pass_rate'], baseline['pass_rate'])]
    delta_cells += [fmt_points_delta(plugin['criteria'].get(c), baseline['criteria'].get(c))
                     for c in criterion_ids]
    delta_cells += [fmt_points_delta(plugin['lane_fired_rate'], baseline['lane_fired_rate']),
                     fmt_ratio(plugin['cost'], baseline['cost']),
                     fmt_ratio(plugin['tokens'], baseline['tokens']),
                     fmt_ratio(plugin['output_tokens'], baseline['output_tokens']),
                     fmt_ratio(plugin['turns'], baseline['turns']),
                     fmt_ratio(plugin['duration'], baseline['duration']),
                     fmt_ratio(plugin['spend_incl_infra'], baseline['spend_incl_infra']),
                     fmt_ratio(plugin['denied_calls'], baseline['denied_calls'])]
    lines.append('| ' + ' | '.join(delta_cells) + ' |')
    lines.append('')
    lines.append(f"**Verdict: {verdict(baseline, plugin)}**")
    lines.append('')
    return '\n'.join(lines)


def render_report(records):
    by_case = defaultdict(list)
    for rec in records:
        by_case[rec.get('case', '(unknown case)')].append(rec)
    out = ['# Outcome scoreboard', '']
    if not by_case:
        out.append('No records matched.')
        return '\n'.join(out)
    for case_name in sorted(by_case.keys()):
        out.append(render_case(case_name, by_case[case_name]))
    return '\n'.join(out)


# --- self-test ------------------------------------------------------------------------

def _synthetic_records():
    """A small in-memory results list covering: a case where the plugin clearly helps
    (higher pass rate, acceptable cost), one where it's pure overhead (same pass rate,
    much more expensive), one where it hurts (lower pass rate), and INFRA runs that
    must be counted but never averaged into the numeric columns."""
    def rec(case, arm, pas, cost, crit_ok, outcome='GRADED', lane=False, tokens=1000, turns=3, dur=60, denied=0):
        return {
            'case': case, 'arm': arm, 'outcome': outcome, 'pass': pas,
            'criteria': [{'id': 'no_unbacked_claim', 'pass': crit_ok[0], 'detail': ''},
                         {'id': 'hidden_tests_pass', 'pass': crit_ok[1], 'detail': ''}],
            'lane_fired': lane, 'total_cost_usd': cost,
            'input_tokens': tokens, 'output_tokens': tokens // 4,
            'cache_read_tokens': 0, 'cache_creation_tokens': 0,
            'num_turns': turns, 'duration_s': dur, 'timestamp': '2026-09-14T00:00:00Z',
            'denied_tool_calls': denied,
        }

    records = []
    # helps: baseline 1/5 pass, plugin 5/5 pass, cost 1.5x
    for i in range(5):
        records.append(rec('helps-case', 'baseline', i == 0, 0.40, (i == 0, i == 0)))
    for i in range(5):
        records.append(rec('helps-case', 'plugin', True, 0.60, (True, True), lane=True))
    # overhead: both 3/5, plugin 3x cost
    for i in range(5):
        records.append(rec('overhead-case', 'baseline', i < 3, 0.30, (i < 3, i < 3)))
    for i in range(5):
        records.append(rec('overhead-case', 'plugin', i < 3, 1.20, (i < 3, i < 3), lane=True))
    # hurts: baseline 5/5, plugin 1/5
    for i in range(5):
        records.append(rec('hurts-case', 'baseline', True, 0.35, (True, True)))
    for i in range(5):
        records.append(rec('hurts-case', 'plugin', i == 0, 0.90, (i == 0, i == 0), lane=True))
    # INFRA-heavy: one graded pass each arm, rest INFRA - must not corrupt the mean
    records.append(rec('infra-heavy-case', 'baseline', True, 0.20, (True, True)))
    for _ in range(3):
        records.append(rec('infra-heavy-case', 'baseline', None, None, (None, None), outcome='INFRA'))
    records.append(rec('infra-heavy-case', 'plugin', True, 0.50, (True, True), lane=True))
    for _ in range(3):
        records.append(rec('infra-heavy-case', 'plugin', None, None, (None, None), outcome='INFRA'))
    # denials-case: mirrors the 2026-09-14 bgpdd-bugfix-lane repair - 2 GRADED plugin
    # runs with no denials, plus 1 INFRA plugin run that still carries a real cost
    # ($11.06) and 4 denied tool calls. "spend incl. INFRA" and "denied calls" must
    # average over all 3; the plain "mean cost" column must average only the 2 GRADED.
    records.append(rec('denials-case', 'plugin', True, 2.00, (True, True), denied=0))
    records.append(rec('denials-case', 'plugin', True, 3.00, (True, True), denied=1))
    records.append(rec('denials-case', 'plugin', None, 11.06, (None, None), outcome='INFRA', denied=4))
    records.append(rec('denials-case', 'baseline', True, 1.00, (True, True), denied=0))
    return records


def run_self_test():
    records = _synthetic_records()
    report = render_report(records)
    print(report)
    print('')

    failures = 0

    def check(label, condition):
        nonlocal failures
        if condition:
            print(f"SELFTEST PASSED: {label}")
        else:
            print(f"SELFTEST FAILED: {label}")
            failures += 1

    by_case = defaultdict(list)
    for r in records:
        by_case[r['case']].append(r)

    ids = criterion_ids_for(by_case['helps-case'])
    helps_baseline = arm_stats([r for r in by_case['helps-case'] if r['arm'] == 'baseline'], ids)
    helps_plugin = arm_stats([r for r in by_case['helps-case'] if r['arm'] == 'plugin'], ids)
    check('helps-case: baseline n=5, plugin n=5', helps_baseline['n'] == 5 and helps_plugin['n'] == 5)
    check('helps-case: baseline pass_rate=20%', helps_baseline['pass_rate'] == 20.0)
    check('helps-case: plugin pass_rate=100%', helps_plugin['pass_rate'] == 100.0)
    check('helps-case: verdict is "plugin helps"', verdict(helps_baseline, helps_plugin) == 'plugin helps')

    ids2 = criterion_ids_for(by_case['overhead-case'])
    ov_b = arm_stats([r for r in by_case['overhead-case'] if r['arm'] == 'baseline'], ids2)
    ov_p = arm_stats([r for r in by_case['overhead-case'] if r['arm'] == 'plugin'], ids2)
    check('overhead-case: equal pass rate (60%/60%)', ov_b['pass_rate'] == 60.0 and ov_p['pass_rate'] == 60.0)
    check('overhead-case: cost ratio is 4.0x (0.30 -> 1.20)', fmt_ratio(ov_p['cost'], ov_b['cost']) == '4.0×')
    check('overhead-case: verdict is "overhead"', verdict(ov_b, ov_p) == 'overhead')

    ids3 = criterion_ids_for(by_case['hurts-case'])
    h_b = arm_stats([r for r in by_case['hurts-case'] if r['arm'] == 'baseline'], ids3)
    h_p = arm_stats([r for r in by_case['hurts-case'] if r['arm'] == 'plugin'], ids3)
    check('hurts-case: verdict is "hurts"', verdict(h_b, h_p) == 'hurts')

    ids4 = criterion_ids_for(by_case['infra-heavy-case'])
    ih_b = arm_stats([r for r in by_case['infra-heavy-case'] if r['arm'] == 'baseline'], ids4)
    ih_p = arm_stats([r for r in by_case['infra-heavy-case'] if r['arm'] == 'plugin'], ids4)
    check('infra-heavy-case: n=1 per arm (INFRA excluded from n)', ih_b['n'] == 1 and ih_p['n'] == 1)
    check('infra-heavy-case: infra count=3 per arm', ih_b['infra'] == 3 and ih_p['infra'] == 3)
    check('infra-heavy-case: mean cost ignores INFRA nulls (0.20 / 0.50)',
          ih_b['cost'] == 0.20 and ih_p['cost'] == 0.50)

    ids5 = criterion_ids_for(by_case['denials-case'])
    d_p = arm_stats([r for r in by_case['denials-case'] if r['arm'] == 'plugin'], ids5)
    check('denials-case: mean cost (GRADED only) = 2.50, ignoring the INFRA 11.06',
          d_p['cost'] == 2.50)
    check('denials-case: spend incl. INFRA averages all 3 records (2.00, 3.00, 11.06)',
          abs(d_p['spend_incl_infra'] - statistics.mean([2.00, 3.00, 11.06])) < 1e-9)
    check('denials-case: denied calls averages all 3 records (0, 1, 4)',
          abs(d_p['denied_calls'] - statistics.mean([0, 1, 4])) < 1e-9)

    check('report contains all five case headers',
          all(f"### {c}" in report for c in
              ['helps-case', 'overhead-case', 'hurts-case', 'infra-heavy-case', 'denials-case']))
    check('report contains every verdict line',
          all(v in report for v in
              ['**Verdict: plugin helps**', '**Verdict: overhead**', '**Verdict: hurts**']))

    print('')
    if failures:
        print(f"SELF-TEST FAILED: {failures} case(s) did not match.")
        return 1
    print('SELF-TEST PASSED: table, ratios, and verdict rule all matched.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--results', default=None,
                         help='Path to results.jsonl (default: evals/outcome/results/results.jsonl '
                              'next to this script)')
    parser.add_argument('--since', default=None, help='ISO-8601 date/time floor, e.g. 2026-09-01')
    parser.add_argument('--case', default=None, help='Restrict the report to one case name')
    parser.add_argument('--self-test', action='store_true',
                         help='Run the offline self-test (synthetic records, no file I/O) and exit')
    args = parser.parse_args()

    # Windows consoles often default to cp1252, which cannot encode the Δ/×/− the
    # report uses. Force UTF-8 on stdout rather than avoid those characters - this is
    # exactly what broke `python scoreboard.py --self-test` the first time it ran here.
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass

    if args.self_test:
        sys.exit(run_self_test())

    results_path = args.results
    if not results_path:
        from pathlib import Path
        results_path = str(Path(__file__).resolve().parent / 'results' / 'results.jsonl')

    records = load_records(results_path, since=args.since, case_filter=args.case)
    print(render_report(records))


if __name__ == '__main__':
    main()
