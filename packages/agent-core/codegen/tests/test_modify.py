"""The modification executor, driven by a scripted proposer (no model involved)."""

import pytest
from sample_project import good_project

from androai_codegen.editing import TextEdit
from androai_codegen.modify import (
    ModificationPlan,
    ModificationTask,
    ModifyConfig,
    ModifyOutcome,
    ProposalRequest,
    ProposedEdit,
    ProposedEdits,
    run_modification,
)
from androai_codegen.review import ReviewSession

STRINGS = "app/src/main/res/values/strings.xml"
APP = "app/src/main/java/com/example/todo/ui/TodoApp.kt"
COLORS = "app/src/main/res/values/colors.xml"
NEW = "app/src/main/res/values/extra.xml"
EMPTY_LIST = '    <string name="empty_list">Nothing to do</string>'


class Scripted:
    """Returns the prepared proposals in order and records what it was asked."""

    def __init__(self, *proposals):
        self.proposals = list(proposals)
        self.requests: list[ProposalRequest] = []

    def propose(self, request):
        self.requests.append(request)
        item = self.proposals.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item


def add_string(path=STRINGS):
    return ProposedEdit(
        action="modify",
        path=path,
        description="add a string",
        edits=(
            TextEdit(old=EMPTY_LIST, new=EMPTY_LIST + '\n    <string name="done">Done</string>'),
        ),
    )


def make_task(**plan):
    values = {"summary": "Add a done label", "affected_files": (STRINGS,)}
    values.update(plan)
    return ModificationTask(
        project_id="proj-1",
        run_id="run-1",
        task_id="task-1",
        user_request="Add a done label",
        plan=ModificationPlan(**values),
    )


@pytest.fixture
def project(put, ws_root):
    for path, content in good_project().items():
        put(path, content)
    return ws_root


@pytest.fixture
def run(project, manager, engine):
    session = ReviewSession(engine)

    def _run(proposer, task=None, config=None):
        return run_modification(manager, session, proposer, task or make_task(), config)

    return _run


def test_completed_applies_and_checkpoints(run, project):
    result = run(Scripted(ProposedEdits(edits=(add_string(),))))
    assert result.outcome is ModifyOutcome.COMPLETED
    assert result.patch_id and result.checkpoint_id and result.review is not None
    assert [c.path for c in result.changes] == [STRINGS]
    assert 'name="done"' in (project / STRINGS).read_text()
    assert result.review.scope == "static"


def test_proposer_sees_files_marked_editable(run):
    proposer = Scripted(ProposedEdits())
    run(proposer)
    (request,) = proposer.requests
    view = {v.path: v for v in request.files}[STRINGS]
    assert view.editable and "empty_list" in view.content and view.checksum


def test_no_edits_is_no_progress(run):
    assert run(Scripted(ProposedEdits(notes="nothing"))).outcome is ModifyOutcome.NO_PROGRESS


def test_provider_failure_leaves_source_untouched(run, project):
    before = (project / STRINGS).read_text()
    result = run(Scripted(RuntimeError("model down: secret-detail")))
    assert result.outcome is ModifyOutcome.PROVIDER_FAILURE
    assert (project / STRINGS).read_text() == before
    assert not any("secret-detail" in w for w in result.warnings)


def test_out_of_scope_edit_is_fed_back_then_fixed(run):
    proposer = Scripted(
        ProposedEdits(edits=(add_string(COLORS),)), ProposedEdits(edits=(add_string(),))
    )
    result = run(proposer)
    assert result.outcome is ModifyOutcome.COMPLETED and result.attempts == 2
    assert "plan does not allow" in proposer.requests[1].feedback[0]


def test_out_of_scope_edit_repeated_is_rejected_and_nothing_written(run, project):
    before = (project / COLORS).read_text()
    bad = ProposedEdit(
        action="modify",
        path=COLORS,
        description="touch colours",
        edits=(TextEdit(old="<resources>", new="<resources><!-- x -->"),),
    )
    task = make_task().model_copy(update={"context_files": (COLORS,)})
    result = run(Scripted(ProposedEdits(edits=(bad,)), ProposedEdits(edits=(bad,))), task)
    assert result.outcome is ModifyOutcome.REJECTED and result.problems
    assert (project / COLORS).read_text() == before


def test_deletion_needs_approval_first(run, project):
    delete = ProposedEdit(action="delete", path=COLORS, description="drop colours")
    task = make_task(deleted_files=(COLORS,), affected_files=())
    result = run(Scripted(ProposedEdits(edits=(delete,))), task)
    assert result.outcome is ModifyOutcome.NEEDS_APPROVAL
    assert result.approval_requests[0].kind == "delete_files"
    assert result.approval_requests[0].paths == (COLORS,)
    assert (project / COLORS).exists()


def test_approved_deletion_is_not_asked_for_again(run, project):
    delete = ProposedEdit(action="delete", path=NEW, description="drop it")
    (project / NEW).write_text("<resources/>\n")
    task = make_task(deleted_files=(NEW,), affected_files=()).model_copy(
        update={"approved_deletions": (NEW,)}
    )
    result = run(Scripted(ProposedEdits(edits=(delete,))), task)
    assert result.outcome is ModifyOutcome.COMPLETED and not (project / NEW).exists()


def test_create_new_file(run, project):
    create = ProposedEdit(
        action="create",
        path=NEW,
        description="new resources",
        content='<resources>\n    <string name="extra">Extra</string>\n</resources>\n',
    )
    task = make_task(new_files=(NEW,), affected_files=())
    result = run(Scripted(ProposedEdits(edits=(create,))), task)
    assert result.outcome is ModifyOutcome.COMPLETED and (project / NEW).exists()


def test_review_blocking_problem_is_fed_back(run, project):
    broken = ProposedEdit(
        action="modify",
        path=APP,
        description="use a string",
        edits=(
            TextEdit(
                old="Text(text = stringResource(R.string.app_name))",
                new="Text(text = stringResource(R.string.nope_missing))",
            ),
        ),
    )
    proposer = Scripted(ProposedEdits(edits=(broken,)), ProposedEdits(edits=(add_string(),)))
    result = run(proposer, make_task(affected_files=(APP, STRINGS)))
    assert len(proposer.requests) == 2
    assert "nope_missing" in " ".join(proposer.requests[1].feedback)
    assert result.outcome is ModifyOutcome.COMPLETED
    assert "nope_missing" not in (project / APP).read_text()


def test_conflict_with_a_manual_change_is_rejected_not_retried(run, project):
    def sneaky(request):
        (project / STRINGS).write_text("<resources/>\n")  # the user edits during the call
        return ProposedEdits(edits=(add_string(),))

    proposer = Scripted(sneaky, ProposedEdits(edits=(add_string(),)))
    result = run(proposer)
    assert result.outcome is ModifyOutcome.REJECTED and len(proposer.requests) == 1
    assert (project / STRINGS).read_text() == "<resources/>\n"


def test_unsafe_plan_path_is_rejected_before_any_call(run):
    proposer = Scripted(ProposedEdits())
    result = run(proposer, make_task(affected_files=("../outside.txt",)))
    assert result.outcome is ModifyOutcome.REJECTED and not proposer.requests


def test_protected_context_file_is_not_shown(run, put):
    put(".env", "TOKEN=abc")
    proposer = Scripted(ProposedEdits())
    task = make_task().model_copy(update={"context_files": (".env",)})
    result = run(proposer, task)
    assert all(v.path != ".env" for v in proposer.requests[0].files)
    assert any(".env" in w for w in result.warnings)


def test_cut_file_cannot_be_overwritten_with_full_content(run, project):
    whole = ProposedEdit(
        action="modify", path=STRINGS, description="rewrite", content="<resources/>\n"
    )
    rows = "".join(f'    <string name="s{i}">v{i}</string>\n' for i in range(400))
    long = "<resources>\n" + rows + "</resources>\n"
    (project / STRINGS).write_text(long)
    result = run(
        Scripted(ProposedEdits(edits=(whole,)), ProposedEdits(edits=(whole,))),
        config=ModifyConfig(max_file_chars=1000, max_revisions=1),
    )
    assert result.outcome is ModifyOutcome.REJECTED
    assert (project / STRINGS).read_text() == long
