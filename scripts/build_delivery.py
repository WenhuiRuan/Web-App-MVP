"""Export reviewed project sources and selected evidence, without reading runtime secrets."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {'.gitignore', '.gitattributes', '.env.example', 'AGENTS.md', 'README.md', 'pyproject.toml', 'pytest.ini'}
SOURCE_DIRS = {'backend', 'frontend', 'scripts', 'db', 'docs', 'data'}
EVIDENCE_PREFIXES = (
    'data/quality/model-recovery/',
    'data/quality/stage6c-interaction/',
    'data/quality/stage6a-acceptance/complete-final/',
    'data/quality/stage6a-acceptance/final-prompts/',
)
EVIDENCE_FILES = {
    'data/quality/stage6a/topic-1.json', 'data/quality/stage6a/topic-2.json',
    'data/quality/stage6a/known-calls.json',
    'data/quality/stage6a-revision/complete-browser.json',
    'data/quality/stage6a-revision/manifest.json',
    'data/quality/stage6a-revision/database-evidence.json',
    'data/quality/stage6a-revision/browser-report.json',
    'data/quality/stage6a-revision/call-statistics.json',
    'data/quality/stage6a-acceptance/verified-version.json',
}
FORBIDDEN_PARTS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.cache',
                   '.pytest_cache', 'work', 'outputs', 'dist', 'test-results', 'playwright-report',
                   'local-data', 'secrets', 'credentials'}


def permitted(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or set(path.parts) & FORBIDDEN_PARTS:
        return False
    if path.name.startswith('.env') and not path.name.endswith('.example'):
        return False
    if re.search(r'\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$', path.name, re.I):
        return False
    if path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.jks', '.log', '.zip', '.pyc'}:
        return False
    if len(path.parts) == 1 and name not in TOP_LEVEL:
        return False
    if len(path.parts) > 1 and path.parts[0] not in SOURCE_DIRS:
        return False
    if name.startswith('data/quality/'):
        return name in EVIDENCE_FILES or name.startswith(EVIDENCE_PREFIXES)
    return True


def audit(name, content):
    if name.endswith(('.json', '.jsonl')):
        documents = [json.loads(line) for line in content.decode('utf-8').splitlines() if line] if name.endswith('.jsonl') else [json.loads(content)]
        def walk(value):
            if isinstance(value, dict):
                if {'reasoning_content', 'chain_of_thought'} & value.keys():
                    raise ValueError(f'Unexpected hidden reasoning field: {name}')
                for item in value.values(): walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        for document in documents: walk(document)
    # Deliberately do not read environment credentials for byte comparisons.
    if re.search(rb'sk-[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', content):
        raise ValueError(f'Possible credential material: {name}; inspect locally without printing values')


def build(output):
    names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'], cwd=ROOT).decode('utf-8').split('\0')
    names = sorted({name for name in names if name and permitted(name) and (ROOT / name).is_file()})
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain'], cwd=ROOT).strip())
    files = {}
    for name in names:
        files[name] = (ROOT / name).read_bytes()
        audit(name, files[name])
    history = subprocess.check_output(['git','log','--date=iso-strict','--format=%h %ad %s'], cwd=ROOT)
    files['delivery/git-history.txt'] = history
    manifest = dict(format='ai-panel-studio-delivery-v1', revision=revision, working_tree_dirty=dirty,
                    files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
                    omissions=['runtime .env/keys/dependencies/caches/databases/.git', 'redundant historical diagnostic dumps'],
                    evidence_policy='Selected final public input/output, snapshot, metrics, version, preserved original interaction and focused correction evidence; no runtime database or hidden reasoning. Redundant historic audits remain in original local repository.',
                    security_check='Path exclusions, common credential patterns and JSON hidden-reasoning fields; no runtime key read.')
    files['delivery/manifest.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items(): archive.writestr('ai-panel-studio/'+name,data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, digest in manifest['files'].items():
            assert hashlib.sha256(archive.read('ai-panel-studio/'+name)).hexdigest() == digest
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf-8')
    print(json.dumps(dict(zip=str(output),files=len(files),bytes=output.stat().st_size,sha256=digest,
                          revision=revision,working_tree_dirty=dirty),ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/ai-panel-studio-delivery.zip')
    build(parser.parse_args().output.resolve())
