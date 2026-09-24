"""Types for the source-backed analysis and its public projections.

These records describe source evidence and static candidates. They do not describe
observed execution. Python functions use snake_case; model and JSON response keys use
the existing camelCase wire names. TypedDicts mirror those wire names rather than
converting keys at a module boundary. The runtime JSON API remains dictionary based.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


TargetStatus = Literal['supported', 'possible', 'external', 'unknown']
ExpansionStatus = Literal['recursive', 'truncated']
ReasonCode = Literal[
    'source_definition', 'external_source', 'unresolved_target',
    'untyped_instance_attribute', 'untyped_call_result', 'inferred_receiver',
    'dynamic_method_dispatch', 'local_binding', 'comprehension_binding',
    'binding_not_established',
    'descriptor_result',
    'constructor_dispatch', 'unreachable_source', 'recursive_expansion',
    'event_route_candidate',
]


class Span(TypedDict):
    file: str
    start: int
    end: int
    col: int
    endCol: int
    hash: str


class Guard(TypedDict):
    kind: str
    condition: str
    branch: NotRequired[str]
    requirement: NotRequired[str]
    span: Span


class ArgumentBinding(TypedDict):
    argument: str
    parameter: str
    certainty: str


class ReceiverBinding(TypedDict):
    mode: Literal['construction', 'implicit', 'explicit', 'not-applicable']
    expression: str | None
    certainty: Literal['possible', 'syntax', 'not-applicable']


class ExecutionContext(TypedDict):
    kind: str
    deferred: bool
    effectiveDeferred: NotRequired[bool]
    inheritedDeferred: NotRequired[bool]
    deferredBy: NotRequired[str]


class TargetCandidate(TypedDict):
    scope: str
    status: TargetStatus
    reason: str
    reasonCode: NotRequired[ReasonCode]


class CandidateEvidence(TypedDict):
    scope: str
    receiverType: str
    label: str
    span: Span
    evidenceId: NotRequired[str]


class ScopeRecord(TypedDict):
    id: str
    symbolKey: str
    file: str
    module: str
    name: str
    qualified: str
    kind: str
    parent: str | None
    span: Span
    params: list[dict[str, Any]]
    output: dict[str, Any]
    flow: list[dict[str, Any]]


class CallRecord(TypedDict):
    id: str
    scope: str
    name: str
    expression: str
    span: Span
    targets: list[str]
    status: TargetStatus
    reason: str
    reasonCode: NotRequired[ReasonCode]
    arguments: list[str]
    bindings: dict[str, list[ArgumentBinding]]
    receiverBindings: NotRequired[dict[str, ReceiverBinding]]
    candidateEvidence: NotRequired[list[CandidateEvidence]]
    destination: str
    conditional: bool
    awaited: bool
    execution: str
    guards: NotRequired[list[Guard]]
    unreachable: NotRequired[bool]
    executionContext: NotRequired[ExecutionContext]


class WorkflowStage(TypedDict):
    id: str
    label: str
    scope: str
    methods: list[str]
    span: Span
    status: TargetStatus
    input: NotRequired[list[dict[str, Any]]]
    output: NotRequired[dict[str, Any]]
    parent: NotRequired[str]
    depth: NotRequired[int]
    condition: NotRequired[str]
    data: NotRequired[str]
    possibleTargets: NotRequired[list[str]]
    constructorCandidates: NotRequired[list[str]]
    callerScope: NotRequired[str]
    destination: NotRequired[str]
    targetLabels: NotRequired[dict[str, str]]
    guards: NotRequired[list[Guard]]
    executionContext: NotRequired[ExecutionContext]
    conditional: NotRequired[bool]
    unreachable: NotRequired[bool]
    callsite: NotRequired[bool]
    construction: NotRequired[bool]
    reason: NotRequired[str]
    reasonCode: NotRequired[ReasonCode]
    evidence: NotRequired[list[dict[str, Any]]]
    candidateEvidence: NotRequired[list[CandidateEvidence]]
    receiverBindings: NotRequired[dict[str, ReceiverBinding]]
    bindings: NotRequired[dict[str, list[ArgumentBinding]]]
    recursive: NotRequired[bool]
    moduleLink: NotRequired[dict[str, str]]
    expansionTruncated: NotRequired[bool]


class AnalysisDiagnostic(TypedDict):
    file: str
    message: str


class Page(TypedDict):
    items: list[Any]
    nextCursor: int | None
    total: int
    omitted: int


class SnapshotRecord(TypedDict):
    schemaVersion: str
    snapshotId: str
    analysisOptions: dict[str, Any]
    files: dict[str, dict[str, Any]]
    scopes: dict[str, ScopeRecord]
    errors: list[AnalysisDiagnostic]
    excluded: list[dict[str, Any]]
    coverage: dict[str, Any]
    limits: list[str]


class AnalysisCompleteness(TypedDict):
    complete: bool
    parsedFiles: int
    discoveredFiles: int
    skippedFiles: int
    analysisErrors: int
    parseErrors: int
    configurationErrors: int
    excludedPaths: int
    unmodeledCalls: int
    sourceOnly: bool


class ResponseEnvelope(TypedDict):
    schemaVersion: str
    operation: str
    detail: NotRequired[str]
    snapshotId: str
    analysisOptions: dict[str, Any]
    analysis: AnalysisCompleteness
    pagination: dict[str, Any]
    truncated: bool
    omittedRecords: int
    result: dict[str, Any]


class Workflow(TypedDict):
    id: str
    title: str
    description: str
    provenance: str
    root: str
    nested: bool
    stages: list[WorkflowStage]
    links: list[dict[str, Any]]
    alternatives: list[dict[str, Any]]
    uncertainties: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]
    truncated: bool
    omitted: int
    limit: int
