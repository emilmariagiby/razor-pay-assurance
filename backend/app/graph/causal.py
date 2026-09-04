"""
Causal Event Graph
------------------
Reconstructs WHY something happened, not just WHAT happened.

The causal graph answers:
    "Payment B was not an independent purchase.
     It was a consequence of an automated retry while Payment A was unresolved."

That's the difference between:
    DUPLICATE_COLLECTION — descriptive
    RETRY_WHILE_UNCERTAIN — explanatory

Architecture:
    Nodes = financial events
    Edges = causal relationships (explicit or inferred)

Explicit causality: event carries caused_by_event_id.
Inferred causality: we derive it from temporal proximity and domain rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from app.models.event import EventStream, EventType, FinancialEvent, EventSource


# ---------------------------------------------------------------------------
# Causal Relationship Types
# ---------------------------------------------------------------------------

class CausalRelation(str):
    TRIGGERED       = "triggered"       # Event A directly caused Event B
    CREATED         = "created"         # Event A resulted in entity B being created
    RESOLVED        = "resolved"        # Event A resolved the uncertainty from Event B
    PRECEDED        = "preceded"        # Event A happened before B (temporal, not causal)
    CONTRADICTS     = "contradicts"     # Event A contradicts the assumption in Event B


# ---------------------------------------------------------------------------
# Causal Chain — a human-readable path through the graph
# ---------------------------------------------------------------------------

@dataclass
class CausalStep:
    event:       FinancialEvent
    relation:    Optional[str] = None   # Relation to the NEXT step
    explanation: str = ""


@dataclass
class CausalChain:
    """
    A linearized path through the causal graph explaining how we got
    from an initiating event to a terminal outcome.
    """
    steps:   list[CausalStep] = field(default_factory=list)
    summary: str = ""

    def __repr__(self) -> str:
        lines = [self.summary]
        for i, step in enumerate(self.steps):
            prefix = f"  [{i+1}]"
            lines.append(f"{prefix} {step.event}")
            if step.relation and i < len(self.steps) - 1:
                lines.append(f"       ↓ {step.relation}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Causal Graph Builder
# ---------------------------------------------------------------------------

class CausalGraphBuilder:
    """
    Builds a directed causal graph from an EventStream.

    The graph has two passes:
    1. Add explicit causal edges (from caused_by_event_id fields)
    2. Infer additional causal edges from domain rules
    """

    def build(self, stream: EventStream) -> nx.DiGraph:
        graph = nx.DiGraph()

        # --- Pass 1: Add all events as nodes ---
        for event in stream:
            graph.add_node(
                event.event_id,
                event=event,
                event_type=event.event_type,
                timestamp=event.timestamp,
                payment_id=event.payment_id,
                amount=event.amount,
                source=event.source,
            )

        # --- Pass 2: Explicit causal edges ---
        for event in stream:
            if event.caused_by_event_id and event.caused_by_event_id in graph.nodes:
                graph.add_edge(
                    event.caused_by_event_id,
                    event.event_id,
                    relation=CausalRelation.TRIGGERED,
                    explicit=True,
                )

        # --- Pass 3: Infer domain-specific causal edges ---
        self._infer_retry_causality(graph, stream)
        self._infer_payment_lifecycle(graph, stream)
        self._infer_late_authorization(graph, stream)

        return graph

    # -----------------------------------------------------------------------
    # Inference Rules
    # -----------------------------------------------------------------------

    def _infer_retry_causality(self, graph: nx.DiGraph, stream: EventStream) -> None:
        """
        Rule: If a PAYMENT_TIMEOUT is followed by an AGENT_RETRY_INITIATED,
        the retry was triggered by the timeout.

        Rule: If an AGENT_RETRY_INITIATED is followed by a PAYMENT_CREATED
        (within a short window, from source=agent), the payment was created
        by the agent action.
        """
        timeout_events = stream.by_type(EventType.PAYMENT_TIMEOUT)
        retry_events   = stream.by_type(EventType.AGENT_RETRY_INITIATED)
        create_events  = stream.by_type(EventType.PAYMENT_CREATED)

        for timeout in timeout_events:
            # Find retries that happened after this timeout (same payment context)
            subsequent_retries = [
                r for r in retry_events
                if r.timestamp > timeout.timestamp
                and (r.payment_id == timeout.payment_id or r.order_id == timeout.order_id)
                and not graph.has_edge(timeout.event_id, r.event_id)
            ]
            for retry in subsequent_retries:
                graph.add_edge(
                    timeout.event_id,
                    retry.event_id,
                    relation=CausalRelation.TRIGGERED,
                    explicit=False,
                    inference_rule="timeout_triggers_retry",
                )

        for retry in retry_events:
            # Find payments created after this retry (by the agent)
            subsequent_creates = [
                c for c in create_events
                if c.timestamp > retry.timestamp
                and c.source == EventSource.AGENT
                and c.order_id == retry.order_id
                and not graph.has_edge(retry.event_id, c.event_id)
            ]
            for create in subsequent_creates:
                graph.add_edge(
                    retry.event_id,
                    create.event_id,
                    relation=CausalRelation.CREATED,
                    explicit=False,
                    inference_rule="retry_creates_payment",
                )

    def _infer_payment_lifecycle(self, graph: nx.DiGraph, stream: EventStream) -> None:
        """
        Rule: Within the same payment_id, events form a causal chain.
        payment.created → payment.authorized → payment.captured
        """
        lifecycle_order = [
            EventType.PAYMENT_CREATED,
            EventType.PAYMENT_TIMEOUT,
            EventType.PAYMENT_AUTHORIZED,
            EventType.PAYMENT_CAPTURED,
            EventType.PAYMENT_FAILED,
        ]

        for payment_id in stream.payment_ids:
            payment_events = sorted(
                stream.for_payment(payment_id),
                key=lambda e: e.timestamp
            )
            for i in range(len(payment_events) - 1):
                src = payment_events[i]
                dst = payment_events[i + 1]
                if not graph.has_edge(src.event_id, dst.event_id):
                    graph.add_edge(
                        src.event_id,
                        dst.event_id,
                        relation=CausalRelation.PRECEDED,
                        explicit=False,
                        inference_rule="lifecycle_sequence",
                    )

    def _infer_late_authorization(self, graph: nx.DiGraph, stream: EventStream) -> None:
        """
        Rule: If Payment A timed out, a retry was initiated, and then Payment A
        was subsequently authorized/captured AFTER the retry payment also captured,
        the original capture RESOLVES the UNCERTAIN state caused by the timeout.
        """
        timeout_events   = stream.by_type(EventType.PAYMENT_TIMEOUT)
        captured_events  = stream.by_type(EventType.PAYMENT_CAPTURED)

        for timeout in timeout_events:
            # Find a late capture for the same payment
            late_captures = [
                c for c in captured_events
                if c.payment_id == timeout.payment_id
                and c.timestamp > timeout.timestamp
            ]
            for capture in late_captures:
                if not graph.has_edge(timeout.event_id, capture.event_id):
                    graph.add_edge(
                        timeout.event_id,
                        capture.event_id,
                        relation=CausalRelation.RESOLVED,
                        explicit=False,
                        inference_rule="late_authorization",
                    )


# ---------------------------------------------------------------------------
# Causal Chain Extractor
# ---------------------------------------------------------------------------

class CausalChainExtractor:
    """
    Given a causal graph and a "violation event" (e.g. the second CAPTURED),
    extracts a human-readable causal chain explaining how we got there.
    """

    def extract(
        self,
        graph:            nx.DiGraph,
        stream:           EventStream,
        target_event_id:  str,
        max_depth:        int = 10,
    ) -> CausalChain:
        """
        Walk backwards from the target event to find its causal root.
        Returns a CausalChain from root → target.
        """
        if target_event_id not in graph.nodes:
            return CausalChain(summary="No causal chain found — event not in graph.")

        # Find all ancestors
        try:
            # Try to find a meaningful root (a node with no predecessors that
            # is an ancestor of our target)
            ancestors = nx.ancestors(graph, target_event_id)
            ancestors.add(target_event_id)

            # Build subgraph of just this causal neighborhood
            subgraph = graph.subgraph(ancestors)

            # Find root nodes in the subgraph
            roots = [n for n in subgraph.nodes if subgraph.in_degree(n) == 0]

            if not roots:
                roots = [target_event_id]

            # Find the most "interesting" root — prefer TIMEOUT events
            best_root = self._pick_best_root(roots, graph)

            # Find shortest path from root to target
            path = nx.shortest_path(graph, best_root, target_event_id)

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            path = [target_event_id]

        # Build steps
        steps = []
        for i, node_id in enumerate(path):
            event = graph.nodes[node_id].get("event")
            if event is None:
                continue

            # Get the relation to the next node
            relation = None
            if i < len(path) - 1:
                edge_data = graph.get_edge_data(node_id, path[i + 1]) or {}
                relation = edge_data.get("relation")

            steps.append(CausalStep(
                event=event,
                relation=relation,
                explanation=self._explain_step(event, relation),
            ))

        summary = self._summarize_chain(steps)
        return CausalChain(steps=steps, summary=summary)

    def _pick_best_root(self, roots: list[str], graph: nx.DiGraph) -> str:
        """Prefer TIMEOUT events as roots — they're usually where things go wrong."""
        for root in roots:
            et = graph.nodes[root].get("event_type", "")
            if et == EventType.PAYMENT_TIMEOUT:
                return root
        return roots[0]

    def _explain_step(self, event: FinancialEvent, relation: Optional[str]) -> str:
        explanations = {
            EventType.PAYMENT_CREATED:     "Payment initiated",
            EventType.PAYMENT_TIMEOUT:     "Gateway returned timeout — outcome uncertain",
            EventType.AGENT_RETRY_INITIATED: "Autonomous agent initiated retry (assumed failure)",
            EventType.PAYMENT_AUTHORIZED:  "Payment authorized by bank",
            EventType.PAYMENT_CAPTURED:    "Payment captured — funds collected",
            EventType.PAYMENT_FAILED:      "Payment definitively failed",
            EventType.REFUND_REQUESTED:    "Refund requested",
            EventType.REFUND_PROCESSED:    "Refund processed by gateway",
            EventType.REFUND_COMPLETED:    "Refund completed — funds returned",
        }
        return explanations.get(event.event_type, event.event_type)

    def _summarize_chain(self, steps: list[CausalStep]) -> str:
        if not steps:
            return "No causal chain found."

        event_types = [s.event.event_type for s in steps]

        if (
            EventType.PAYMENT_TIMEOUT in event_types
            and EventType.AGENT_RETRY_INITIATED in event_types
        ):
            return (
                "A retry was initiated after a gateway timeout (uncertain state). "
                "Both the original payment and the retry ultimately succeeded, "
                "resulting in a duplicate collection."
            )

        return f"Causal chain of {len(steps)} events traced from root to outcome."
