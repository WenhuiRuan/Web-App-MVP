import json

from jsonschema import Draft202012Validator, FormatChecker

from backend.app.contracts import ContractExamples
from scripts.export_contracts import ROOT, artifacts


def test_machine_contracts_and_examples_are_current():
    for path, data in artifacts().items():
        assert json.loads(path.read_text(encoding='utf-8')) == data
    data = json.loads((ROOT / 'data/samples/contracts.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'docs/contracts/schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    ContractExamples.model_validate(data)


def test_openapi_refs_resolve_and_future_routes_are_explicit():
    spec = artifacts()[ROOT / 'docs/contracts/openapi.json']
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == '$ref':
                    current = spec
                    for part in value.removeprefix('#/').split('/'):
                        current = current[part]
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(spec)
    assert spec['paths']['/api/health/ready']['get']['x-implemented'] is True
    assert spec['paths']['/api/discussions']['post']['x-implemented'] is True
    for path,method in [('/api/discussions','get'),('/api/discussions/{discussion_id}','get'),('/api/discussions/{discussion_id}/roster-generation','post'),('/api/discussions/{discussion_id}/start','post'),('/api/discussions/{discussion_id}/operations/{operation_id}','get')]:
        assert spec['paths'][path][method]['x-implemented'] is True
    assert spec['paths']['/api/discussions/{discussion_id}/events']['get']['x-implemented'] is False
    assert spec['paths']['/api/discussions/{discussion_id}/summary-retry']['post']['x-implemented'] is True
