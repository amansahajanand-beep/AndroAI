"""The three LangGraph workflows. All share the coding loop and the validation/repair tail.

new_app:  requirements -> [clarify] -> architecture -> decompose -> approval
          -> coding loop -> validate -> (finish | classify -> repair/infra-retry)
modify:   analyze_project -> index_context -> modification_plan -> [clarify]
          -> modification_tasks -> approval -> coding loop -> validate ...
repair:   analyze_project -> classify -> (infra retry | repair_plan -> coding loop -> validate ...)
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .deps import WorkflowDeps, WorkflowState
from .nodes import FAIL, Nodes, bad, route


def _common(g: StateGraph, n: Nodes) -> None:
    """Coding loop + validation + repair + terminals (identical across workflows)."""
    for name, fn in [
        ("dispatch_coding", n.dispatch_coding), ("await_coding", n.await_coding), ("apply_coding", n.apply_coding),
        ("validate", n.validate), ("await_validation", n.await_validation), ("evaluate", n.evaluate),
        ("classify", n.classify), ("infra_retry", n.infra_retry), ("repair_plan", n.repair_plan),
    ]:
        g.add_node(name, n.step(name)(fn))
    g.add_node("finish", n.finish)
    g.add_node(FAIL, n.fail)

    g.add_conditional_edges("dispatch_coding", route("await_coding"), ["await_coding", FAIL])
    g.add_conditional_edges("await_coding", route("apply_coding"), ["apply_coding", FAIL])
    g.add_conditional_edges("apply_coding", n.after_apply, ["dispatch_coding", "validate", FAIL])
    g.add_conditional_edges("validate", route("await_validation"), ["await_validation", FAIL])
    g.add_conditional_edges("await_validation", route("evaluate"), ["evaluate", FAIL])
    g.add_conditional_edges("evaluate", n.after_evaluate, ["finish", "classify", FAIL])
    g.add_conditional_edges("classify", n.after_classify, ["infra_retry", "repair_plan"])
    g.add_conditional_edges("infra_retry", route("validate"), ["validate", FAIL])
    g.add_conditional_edges("repair_plan", route("dispatch_coding"), ["dispatch_coding", FAIL])
    g.add_edge("finish", END)
    g.add_edge(FAIL, END)


def _approval_edges(g: StateGraph, n: Nodes, revise_to: str) -> None:
    g.add_node("approval", n.step("approval")(n.approval))
    g.add_conditional_edges(
        "approval",
        lambda s: FAIL if bad(s) else ("dispatch_coding" if s.get("plan_approved") else revise_to),
        ["dispatch_coding", revise_to, FAIL],
    )


def build_new_app_graph(deps: WorkflowDeps, checkpointer: BaseCheckpointSaver):
    n = Nodes(deps)
    g = StateGraph(WorkflowState)
    for name, fn in [("requirements", n.requirements), ("clarify", n.clarify),
                     ("architecture", n.architecture), ("decompose", n.decompose)]:
        g.add_node(name, n.step(name)(fn))
    g.add_edge(START, "requirements")
    g.add_conditional_edges(
        "requirements", lambda s: FAIL if bad(s) else ("clarify" if n.needs_clarification(s) else "architecture"),
        ["clarify", "architecture", FAIL])
    g.add_edge("clarify", "requirements")
    g.add_conditional_edges("architecture", route("decompose"), ["decompose", FAIL])
    g.add_conditional_edges("decompose", route("approval"), ["approval", FAIL])
    _approval_edges(g, n, revise_to="requirements")
    _common(g, n)
    return g.compile(checkpointer=checkpointer)


def build_modify_graph(deps: WorkflowDeps, checkpointer: BaseCheckpointSaver):
    n = Nodes(deps)
    g = StateGraph(WorkflowState)
    for name, fn in [("analyze_project", n.analyze_project), ("index_context", n.index_context),
                     ("modification_plan", n.modification_plan), ("clarify", n.clarify),
                     ("modification_tasks", n.modification_tasks)]:
        g.add_node(name, n.step(name)(fn))
    g.add_edge(START, "analyze_project")
    g.add_conditional_edges("analyze_project", route("index_context"), ["index_context", FAIL])
    g.add_conditional_edges("index_context", route("modification_plan"), ["modification_plan", FAIL])
    g.add_conditional_edges(
        "modification_plan", lambda s: FAIL if bad(s) else ("clarify" if n.needs_clarification(s) else "modification_tasks"),
        ["clarify", "modification_tasks", FAIL])
    g.add_edge("clarify", "modification_plan")
    g.add_conditional_edges("modification_tasks", route("approval"), ["approval", FAIL])
    _approval_edges(g, n, revise_to="modification_plan")
    _common(g, n)
    return g.compile(checkpointer=checkpointer)


def build_repair_graph(deps: WorkflowDeps, checkpointer: BaseCheckpointSaver):
    """Entry state must contain `failure` ({log,error_code,retryable}) and `source_key`."""
    n = Nodes(deps)
    g = StateGraph(WorkflowState)
    g.add_node("analyze_project", n.step("analyze_project")(n.analyze_project))
    g.add_edge(START, "analyze_project")
    g.add_conditional_edges("analyze_project", route("classify"), ["classify", FAIL])
    _common(g, n)
    return g.compile(checkpointer=checkpointer)


GRAPH_BUILDERS = {"new_app": build_new_app_graph, "modify": build_modify_graph, "repair": build_repair_graph}
