"""构建并编译 LangGraph 检索失败改写工作流。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import AgentNodes
from .state import AgentState


class ResearchGraph:
    """真实 LangGraph StateGraph；最多一次改写和一次二次检索。"""

    def __init__(self, nodes: AgentNodes) -> None:
        self._nodes = nodes
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(AgentState)
        builder.add_node("retrieve_initial", self._nodes.retrieve_initial)
        builder.add_node(
            "assess_initial_evidence",
            self._nodes.assess_initial_evidence,
        )
        builder.add_node("rewrite_query", self._nodes.rewrite_query)
        builder.add_node("retrieve_retry", self._nodes.retrieve_retry)
        builder.add_node(
            "assess_retry_evidence",
            self._nodes.assess_retry_evidence,
        )
        builder.add_node(
            "answer_with_evidence",
            self._nodes.answer_with_evidence,
        )
        builder.add_node("refuse", self._nodes.refuse)

        builder.add_edge(START, "retrieve_initial")
        builder.add_edge("retrieve_initial", "assess_initial_evidence")
        builder.add_conditional_edges(
            "assess_initial_evidence",
            self._nodes.route_initial,
            {
                "answer": "answer_with_evidence",
                "rewrite": "rewrite_query",
                "refuse": "refuse",
            },
        )
        builder.add_conditional_edges(
            "rewrite_query",
            self._nodes.route_rewrite,
            {
                "retrieve_retry": "retrieve_retry",
                "refuse": "refuse",
            },
        )
        builder.add_edge("retrieve_retry", "assess_retry_evidence")
        builder.add_conditional_edges(
            "assess_retry_evidence",
            self._nodes.route_retry,
            {
                "answer": "answer_with_evidence",
                "refuse": "refuse",
            },
        )
        builder.add_edge("answer_with_evidence", END)
        builder.add_edge("refuse", END)
        return builder.compile()

    async def ainvoke(self, state: AgentState) -> AgentState:
        """运行一次图；设置递归上限，防止任何意外循环。"""
        return await self.graph.ainvoke(
            state,
            config={"recursion_limit": 12},
        )
