"""Typed local-rule reports. No provider calls or business writes."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .pilot_models import utcnow


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    input: str = Field(min_length=1, max_length=2000)
    expectContains: str | None = Field(default=None, max_length=500)
    expectStatus: Literal['success', 'failed'] = 'success'

    @model_validator(mode='after')
    def meaningful_expectation(self):
        if self.expectStatus == 'success' and not self.expectContains:
            raise ValueError('成功用例须填写非空的预期结果')
        return self


class EvaluationStep(BaseModel):
    node_id: str
    label: str
    status: Literal['success', 'failed', 'skipped']
    output_preview: str
    truncated: bool
    error: str | None = None


class EvaluationRow(BaseModel):
    number: int
    input: str
    expectContains: str | None
    expectStatus: Literal['success', 'failed']
    actual_status: Literal['success', 'failed']
    output_preview: str
    truncated: bool
    passed: bool
    steps: list[EvaluationStep]


class EvaluationReport(BaseModel):
    id: str
    domain: Literal['knowledge'] = 'knowledge'
    revision: Literal[1] = 1
    purpose: Literal['evaluation'] = 'evaluation'
    application_id: str
    application_revision: int
    definition_sha256: str
    passed: int
    total: int
    pass_rate: float
    cases: list[EvaluationRow]
    model_enabled: Literal[False] = False
    created_at: str


async def evaluate_rules(app, definition, graph, cases, actor, report_id):
    from .applications import _execute, RunBody
    from .security import Actor
    rows = []
    for index, case in enumerate(cases, 1):
        result = await _execute(definition, RunBody(input=case.input, mode='draft'),
            Actor(actor.id, 'user', ''), {'id': report_id + '-' + str(index),
                'applicationId': app.id, 'steps': [], 'output': '', 'createdAt': utcnow()}, graph, persist=False)
        status = result['status']
        output = result.get('output', '')
        passed = status == case.expectStatus and (not case.expectContains or case.expectContains in output)
        steps = [EvaluationStep(node_id=s['nodeId'], label=s['label'], status=s['status'],
            output_preview=s.get('output', '')[:400], truncated=len(s.get('output', '')) > 400,
            error=s.get('error')) for s in result['steps']]
        rows.append(EvaluationRow(number=index, input=case.input, expectContains=case.expectContains,
            expectStatus=case.expectStatus, actual_status=status, output_preview=output[:1000],
            truncated=len(output) > 1000, passed=passed, steps=steps))
    passed = sum(row.passed for row in rows)
    return EvaluationReport(id=report_id, application_id=app.id, application_revision=app.revision,
        definition_sha256=hashlib.sha256(json.dumps(definition, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        passed=passed, total=len(rows), pass_rate=passed / len(rows), cases=rows, created_at=utcnow())
