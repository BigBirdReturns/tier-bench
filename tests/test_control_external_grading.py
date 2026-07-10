import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
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


def commitment(label, secret):
    return hashlib.sha256(f'{label}\0{secret}'.encode()).hexdigest()


def export_packet(tmp_path, seed='TEST-SEED-123456', salt='S' * 64,
                  secrets_from_key=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    packet = tmp_path / 'packet.json'
    key = tmp_path / 'key.json'
    cmd = [
        sys.executable,
        'scripts/export_blind_control_packet.py',
        '--packet', str(packet),
        '--key', str(key),
        '--source-commit', 'TESTCOMMIT',
    ]
    if secrets_from_key:
        cmd.extend(['--secrets-from-key', str(secrets_from_key)])
    else:
        salt_path = tmp_path / 'id-salt.txt'
        salt_path.write_text(salt, encoding='utf-8')
        cmd.extend(['--seed', seed, '--id-salt-file', str(salt_path)])
    run(cmd)
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
        'packet_schema': 'tier-bench.control_blind_packet.v2',
        'source_commit': 'TESTCOMMIT',
        'id_salt_commitment': commitment('id-salt', 'S' * 64),
        'permutation_commitment': commitment('permutation', 'TEST-SEED-123456'),
        'item_count': 80,
        'instructions': "Return exactly one JSON object per item as an array of {id, score, rationale}. Score only from this packet's rubric and verbatim responses. Do not infer subject model identity.",
    }
    assert len(packet_obj['items']) == 80
    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in packet_text
    assert 'S' * 64 not in packet_text
    assert 'TEST-SEED-123456' not in packet_text
    assert '"id_salt"' not in packet_text
    assert '"permutation_seed"' not in packet_text
    for item in packet_obj['items']:
        assert set(item) == {'id', 'probe_id', 'probe_shape', 'prompt_surface', 'response'}
        assert 'score' not in item
        assert 'grader' not in item
        assert 'model' not in item

    key_obj = json.loads(key.read_text(encoding='utf-8'))
    assert key_obj['_meta']['packet_sha256']
    assert key_obj['_meta']['source_commit'] == 'TESTCOMMIT'
    assert key_obj['_meta']['key_schema'] == 'tier-bench.control_blind_key.v2'
    assert key_obj['_meta']['id_salt'] == 'S' * 64
    assert key_obj['_meta']['permutation_seed'] == 'TEST-SEED-123456'
    assert key_obj['_meta']['id_salt_commitment'] == packet_obj['_meta']['id_salt_commitment']
    assert key_obj['_meta']['permutation_commitment'] == packet_obj['_meta']['permutation_commitment']
    assert len(key_obj['items']) == 80
    assert any(v['administration_id'].endswith('__b') for v in key_obj['items'].values())


def test_packet_order_is_seeded_and_deterministic(tmp_path):
    p1, k1 = export_packet(tmp_path / 'a', seed='A' * 16)
    p2, _ = export_packet(tmp_path / 'b', seed='A' * 16)
    p3, _ = export_packet(tmp_path / 'c', seed='B' * 16)
    p4, _ = export_packet(tmp_path / 'd', seed='A' * 16, salt='T' * 64)
    p5, _ = export_packet(tmp_path / 'e', secrets_from_key=k1)
    ids1 = [x['id'] for x in json.loads(p1.read_text())['items']]
    ids2 = [x['id'] for x in json.loads(p2.read_text())['items']]
    ids3 = [x['id'] for x in json.loads(p3.read_text())['items']]
    ids4 = [x['id'] for x in json.loads(p4.read_text())['items']]
    ids5 = [x['id'] for x in json.loads(p5.read_text())['items']]
    assert ids1 == ids2
    assert ids1 != ids3
    assert sorted(ids1) == sorted(ids3)
    assert set(ids1).isdisjoint(ids4)
    assert ids1 == ids5
    assert p1.read_bytes() == p5.read_bytes()


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
    assert manifest['packet_schema'] == 'tier-bench.control_blind_packet.v2'
    assert manifest['id_salt_commitment'] == commitment('id-salt', 'S' * 64)
    assert manifest['permutation_commitment'] == commitment('permutation', 'TEST-SEED-123456')
    assert 'id_salt' not in manifest
    assert 'permutation_seed' not in manifest
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


def _run_standalone() -> int:
    test_root = ROOT / '.test-tmp'
    test_root.mkdir(exist_ok=True)
    failed = 0
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith('test_') and callable(fn)]
    for fn in tests:
        tmp = Path(tempfile.mkdtemp(prefix=f'{fn.__name__}-', dir=test_root))
        try:
            fn(tmp)
            print(f'  ok  {fn.__name__}')
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f'FAIL  {fn.__name__}: {e}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(_run_standalone())
