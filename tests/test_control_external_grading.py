import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.aggregate_control import aggregate

FORBIDDEN_TEXT = [
    '"administration_id"',
    '"run_id"',
    '"source_file"',
    '"model"',
    '"effort"',
    '"contributor"',
    '"date"',
    '"score"',
    'score_total',
    'score_max',
    'score_key',
    'grade_note',
    'grader_conflict',
    'evidence_class',
    'single-source',
    'corroborated',
    'grader shares subject lineage',
    'claude-opus-4-8',
    'fable-5',
    'haiku',
    'opus',
    'sonnet',
    'bigbird',
    '20260707',
    '__b',
    'data/control-results',
]


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def export_packet(tmp_path, seed='TEST-SEED'):
    packet = tmp_path / 'packet.json'
    key = tmp_path / 'key.json'
    run([
        sys.executable,
        'scripts/export_blind_control_packet.py',
        '--packet', str(packet),
        '--key', str(key),
        '--source-commit', 'TESTCOMMIT',
        '--seed', seed,
    ])
    return packet, key


def grades_for_key(key_path, score=1):
    key_obj = json.loads(key_path.read_text(encoding='utf-8'))
    return [
        {'id': oid, 'score': score, 'rationale': 'test external rationale'}
        for oid in key_obj['items']
    ]


def test_blind_packet_serialization_excludes_source_and_grade_information(tmp_path):
    packet, key = export_packet(tmp_path)

    packet_text = packet.read_text(encoding='utf-8')
    packet_obj = json.loads(packet_text)
    assert packet_obj['_meta'] == {
        'packet_schema': 'tier-bench.control_blind_packet.v1',
        'source_commit': 'TESTCOMMIT',
        'permutation_seed': 'TEST-SEED',
        'item_count': 80,
        'instructions': "Return exactly one JSON object per item as an array of {id, score, rationale}. Score only from this packet's rubric and verbatim responses. Do not infer subject model identity.",
    }
    assert len(packet_obj['items']) == 80
    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in packet_text
    for item in packet_obj['items']:
        assert set(item) == {'id', 'probe_id', 'probe_shape', 'prompt_surface', 'response'}
        assert 'score' not in item
        assert 'grader' not in item
        assert 'model' not in item

    key_obj = json.loads(key.read_text(encoding='utf-8'))
    assert key_obj['_meta']['packet_sha256']
    assert key_obj['_meta']['source_commit'] == 'TESTCOMMIT'
    assert key_obj['_meta']['permutation_seed'] == 'TEST-SEED'
    assert len(key_obj['items']) == 80
    assert any(v['administration_id'].endswith('__b') for v in key_obj['items'].values())


def test_packet_order_is_seeded_and_deterministic(tmp_path):
    p1, _ = export_packet(tmp_path / 'a', seed='A')
    p2, _ = export_packet(tmp_path / 'b', seed='A')
    p3, _ = export_packet(tmp_path / 'c', seed='B')
    ids1 = [x['id'] for x in json.loads(p1.read_text())['items']]
    ids2 = [x['id'] for x in json.loads(p2.read_text())['items']]
    ids3 = [x['id'] for x in json.loads(p3.read_text())['items']]
    assert ids1 == ids2
    assert ids1 != ids3
    assert sorted(ids1) == sorted(ids3)


def merge(tmp_path, key, grades, grade_run_id='run-1', check=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    grades_path = tmp_path / f'{grade_run_id}.json'
    grades_path.write_text(json.dumps(grades), encoding='utf-8')
    out_dir = tmp_path / 'merged'
    result = run([
        sys.executable,
        'scripts/merge_external_grades.py',
        '--grades', str(grades_path),
        '--key', str(key),
        '--grader', 'external-gpt-lineage-unverified',
        '--grade-run-id', grade_run_id,
        '--out', str(out_dir),
    ], check=check)
    return result, out_dir, grades_path


def test_merge_is_complete_additive_idempotent_and_preserves_fable_administrations(tmp_path):
    _packet, key = export_packet(tmp_path)
    grades = grades_for_key(key, score=1)
    _result, out_dir, grades_path = merge(tmp_path, key, grades, grade_run_id='run-1')
    # Reapplying the same run is idempotent and does not duplicate judgments.
    merge(tmp_path, key, grades, grade_run_id='run-1')

    outputs = sorted(out_dir.glob('*.jsonl'))
    assert len(outputs) == 8
    assert (out_dir / 'fable-5__high__bigbird__20260707.jsonl').exists()
    assert (out_dir / 'fable-5__high__bigbird__20260707__b.jsonl').exists()
    manifest = json.loads((out_dir / '_external_grade_runs' / 'run-1' / 'manifest.json').read_text())
    assert manifest['grade_run_id'] == 'run-1'
    assert manifest['grader'] == 'external-gpt-lineage-unverified'
    assert manifest['packet_sha256']
    assert manifest['packet_source_commit'] == 'TESTCOMMIT'
    assert (out_dir / manifest['raw_artifact_file']).read_text() == grades_path.read_text()

    original = Path('data/control-results/fable-5__high__bigbird__20260707.jsonl').read_text(encoding='utf-8').splitlines()
    merged = (out_dir / 'fable-5__high__bigbird__20260707.jsonl').read_text(encoding='utf-8').splitlines()
    orig_meta, orig_p1 = json.loads(original[0]), json.loads(original[1])
    merged_meta, merged_p1 = json.loads(merged[0]), json.loads(merged[1])
    assert merged_meta['grader'] == orig_meta['grader']
    assert merged_meta['score_total'] == orig_meta['score_total']
    assert merged_p1['score'] == orig_p1['score']
    assert merged_p1['grader'] == orig_p1['grader']
    assert merged_p1['grade_note'] == orig_p1['grade_note']
    assert len(merged_p1['external_grades']) == 1
    ext = merged_p1['external_grades'][0]
    assert ext['score'] == 1
    assert ext['grader'] == 'external-gpt-lineage-unverified'
    assert ext['grade_run_id'] == 'run-1'
    assert ext['packet_sha256'] == manifest['packet_sha256']
    assert ext['packet_source_commit'] == 'TESTCOMMIT'

    agg = aggregate(str(out_dir))
    fable_p1 = agg['fable-5|high|P1']
    assert fable_p1['n_runs'] == 2
    assert sorted(fable_p1['administration_ids']) == [
        'fable-5__high__bigbird__20260707',
        'fable-5__high__bigbird__20260707__b',
    ]
    assert fable_p1['n_judgments'] == 4

    conflicting = [dict(g) for g in grades]
    conflicting[0]['score'] = 2
    result, _out, _grades_path = merge(tmp_path, key, conflicting, grade_run_id='run-1', check=False)
    assert result.returncode != 0
    assert 'Conflicting artifact' in result.stderr


def test_merge_rejects_incomplete_unknown_duplicate_and_invalid_scores(tmp_path):
    _packet, key = export_packet(tmp_path)
    grades = grades_for_key(key, score=1)

    cases = []
    cases.append(grades[:-1])
    cases.append(grades + [{'id': 'unknown', 'score': 1, 'rationale': 'x'}])
    cases.append(grades + [dict(grades[0])])
    bad_type = [dict(g) for g in grades]; bad_type[0]['score'] = '1'; cases.append(bad_type)
    bad_range = [dict(g) for g in grades]; bad_range[0]['score'] = 3; cases.append(bad_range)

    for i, bad in enumerate(cases):
        result, _out, _path = merge(tmp_path / f'case-{i}', key, bad, grade_run_id=f'bad-{i}', check=False)
        assert result.returncode != 0
