"""Bounded goal-to-plan generation; never edits or executes repository code."""
from typing import Protocol

from pydantic import ValidationError, Field

from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.domain.base import DomainModel, Summary
from autonomous_engineering.domain.product_planning import ProductPlanDraft, PlanningBasis


class GoalInput(DomainModel):
    user_request: str


class PlanningProject(DomainModel):
    name: str
    description: str
    stack: tuple[str, ...]


class ProductPlanningContext(DomainModel):
    task: GoalInput
    project: PlanningProject
    repository: PlanningBasis = Field(default_factory=lambda: PlanningBasis(mode='goal_only', reason='Repository context was not supplied.'))
    validation_feedback: Summary | None = None


class ProductPlanProvider(Protocol):
    def generate(self, context: ProductPlanningContext) -> ProductPlanDraft: ...


class ProductPlanningAgent:
    def __init__(self, provider: ProductPlanProvider):
        self.provider = provider
        self.attempts = 0

    def plan(self, goal: str, project: dict, basis: PlanningBasis | None = None) -> ProductPlanDraft:
        context = ProductPlanningContext(task=GoalInput(user_request=goal), project=PlanningProject(
            name=project['name'][:200], description=project.get('description', '')[:2000],
            stack=tuple(project.get('stack', [])[:20])), repository=basis or PlanningBasis(mode='goal_only', reason='Repository context was not supplied.'))
        for attempt in range(2):
            self.attempts = attempt + 1
            try:
                return ProductPlanDraft.model_validate(self.provider.generate(context))
            except ValidationError as exc:
                issues = exc.errors(include_input=False, include_context=False)[:6]
                feedback = '; '.join(str(item['loc']) + ': ' + item['msg'] for item in issues)[:3000]
            except PlanningError as exc:
                if exc.code != 'INVALID_PRODUCT_PLAN':
                    raise
                feedback = str(exc)[:3000]
            context = ProductPlanningContext(task=context.task, project=context.project, repository=context.repository, validation_feedback=feedback)
        raise PlanningError('INVALID_PRODUCT_PLAN', 'Product planning failed validation after two attempts. ' + feedback)
