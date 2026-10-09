"""Stage 4A-2: lifecycle decisions without HTTP/SQLite dependencies."""
import pytest
from backend.app.lifecycle import LifecycleError, generation_revision, require_capacity


@pytest.mark.parametrize('state,stage,revision,expected', [
    ('DRAFT', None, 0, 1), ('FAILED','roster',0,1), ('INTERRUPTED','roster',2,3),
])
def test_generation_revision_for_draft_and_roster_retry(state, stage, revision, expected):
    assert generation_revision(state, stage, revision) == expected


@pytest.mark.parametrize('state,stage', [('GENERATING',None),('READY',None),('RUNNING',None),('COMPLETED',None),('FAILED','discussion'),('FAILED','summary')])
def test_generation_rejects_illegal_lifecycle_state(state, stage):
    with pytest.raises(LifecycleError) as error:
        generation_revision(state, stage, 1)
    assert error.value.code == 'INVALID_STATE'


def test_capacity_boundary():
    require_capacity(2, 3)
    with pytest.raises(LifecycleError) as error:
        require_capacity(3, 3)
    assert error.value.code == 'CAPACITY_EXCEEDED'
