"""Check requirement traceability and local documentation links without app claims."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = r'(?:S2-\d{2}|[FTPDS]-\d{2})'


def main():
    requirements = (ROOT / 'docs/requirements.md').read_text(encoding='utf-8')
    acceptance = (ROOT / 'docs/acceptance.md').read_text(encoding='utf-8')
    ids = re.findall(r'^\| (' + ID + r') \|', requirements, re.M)
    primary_rows = re.findall(r'^\| (AC-[A-Z0-9-]+) \| (' + ID + r') \|', acceptance, re.M)
    mapped = [requirement for case, requirement in primary_rows if not case.startswith('AC-R')]
    assert len(ids) == len(set(ids)), 'Duplicate requirement ID'
    assert sorted(ids) == sorted(mapped), 'Requirement/acceptance mapping is incomplete or duplicated'
    ac = re.findall(r'^\| (AC-[A-Z0-9-]+) \|', acceptance, re.M)
    assert len(ac) == len(set(ac)), 'Duplicate acceptance ID'
    questions = set(re.findall(r'^\| (Q-\d{2}) \|', (ROOT / 'docs/decisions.md').read_text(encoding='utf-8'), re.M))
    files = [ROOT / 'README.md', ROOT / 'AGENTS.md', *sorted((ROOT / 'docs').glob('*.md'))]
    for file in files:
        text = file.read_text(encoding='utf-8')
        assert len(re.findall(r'^```', text, re.M)) % 2 == 0, f'Unbalanced fences: {file.name}'
        for ref in re.findall(r'(?<![A-Z0-9-])' + ID + r'\b', text):
            assert ref in ids, f'Unknown requirement {ref}: {file.name}'
        for question in re.findall(r'(?<![A-Z0-9-])Q-\d{2}\b', text):
            assert question in questions, f'Unknown question {question}: {file.name}'
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in target or target.startswith('#'):
                continue
            assert (file.parent / target.split('#')[0]).exists(), f'Broken link {target}: {file.name}'
    print(f'PASS: {len(ids)} unique requirements mapped 1:1; {len(ac)} unique acceptance cases; {len(files)} documents checked.')


if __name__ == '__main__':
    main()
