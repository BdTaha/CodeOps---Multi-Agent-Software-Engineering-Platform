"""Explainable resource recommendations. No LLM and no execution side effects."""
from autonomous_engineering.domain.teams import AssignmentRecommendation, MemberCapacity


def capacities(members, tasks):
    result = {}
    for member in members:
        owned = [task for task in tasks if task.assignee_id == member.id and task.status != 'done']
        load = sum(task.estimated_hours for task in owned)
        human = member.member_type == 'human'
        assignable = member.weekly_capacity_hours * member.target_utilization if human else None
        result[member.id] = MemberCapacity(member_id=member.id, planned_load_hours=round(load, 4),
            assigned_task_count=len(owned), assignable_capacity_hours=round(assignable, 4) if human else None,
            reserved_capacity_hours=round(member.weekly_capacity_hours - assignable, 4) if human else None,
            remaining_capacity_hours=round(assignable - load, 4) if human else None,
            remaining_task_slots=None if human else member.max_concurrent_tasks - len(owned))
    return result


def dependency_warnings(task, tasks):
    indexed = {item.id: item for item in tasks}
    return [f'{task.key} depends on {indexed[ref.task_id].key}; dependency not completed.'
        for ref in task.dependencies if ref.task_id in indexed and indexed[ref.task_id].status != 'done']


def assignment_warnings(task, member, squad, capacity, tasks):
    warnings = dependency_warnings(task, tasks)
    if not member.active:
        warnings.append(f'{member.name} is inactive.')
    if task.technical_area not in {skill.technical_area for skill in member.skills}:
        warnings.append(f'{member.name} has no configured {task.technical_area} skill.')
    if task.technical_area not in squad.technical_areas:
        warnings.append(f'{squad.name} does not cover {task.technical_area}.')
    # Reassigning the same task must not count its estimate or slot twice.
    already_owned = task.assignee_id == member.id and task.status != 'done'
    extra_hours = task.estimated_hours if task.status != 'done' and not already_owned else 0
    extra_slots = int(task.status != 'done' and not already_owned)
    if member.member_type == 'human':
        excess = extra_hours - capacity.remaining_capacity_hours
        if excess > 0:
            warnings.append(f'This assignment would exceed {member.name}\'s planned capacity by {excess:g}h.')
    else:
        if member.availability != 'available':
            warnings.append(f'{member.name} is {member.availability}.')
        if extra_slots > capacity.remaining_task_slots:
            warnings.append(f'{member.name} has no remaining planned task slots (limit {member.max_concurrent_tasks}).')
    return warnings


def recommend(task, members, squads, tasks):
    if task.assignee_id is not None or task.status == 'done':
        return []
    loads = capacities(members, tasks)
    squad_map = {squad.id: squad for squad in squads}
    result = []
    for member in members:
        if not member.active or (member.member_type == 'ai' and member.availability != 'available'):
            continue
        skill = next((skill for skill in member.skills if skill.technical_area == task.technical_area), None)
        squad = squad_map[member.squad_id]
        if skill is None or (task.squad_id is not None and member.squad_id != task.squad_id):
            continue
        capacity = loads[member.id]
        human = member.member_type == 'human'
        fits = capacity.remaining_capacity_hours >= task.estimated_hours if human else capacity.remaining_task_slots >= 1
        squad_match = task.technical_area in squad.technical_areas
        remaining_fraction = max(0, min(1, capacity.remaining_capacity_hours / capacity.assignable_capacity_hours)) if human and capacity.assignable_capacity_hours else (max(0, capacity.remaining_task_slots) / member.max_concurrent_tasks if not human else 0)
        score = skill.proficiency * 10 + int(squad_match) * 5 + remaining_fraction * 5
        reasons = [f'Skill match: {task.technical_area} {skill.proficiency}/5.',
            f'Squad area match: {"yes" if squad_match else "no"}.',
            f'Remaining planned capacity: {capacity.remaining_capacity_hours:g}h.' if human else f'Available; {capacity.remaining_task_slots} planned task slots remaining.']
        result.append(AssignmentRecommendation(task_id=task.id, member_id=member.id, squad_id=member.squad_id,
            score=round(score, 4), skill_proficiency=skill.proficiency, fits_capacity=fits,
            reasons=tuple(reasons), warnings=tuple(assignment_warnings(task, member, squad, capacity, tasks)),
            remaining_capacity_hours=capacity.remaining_capacity_hours, remaining_task_slots=capacity.remaining_task_slots))
    return sorted(result, key=lambda item: (not item.fits_capacity, -item.score, str(item.member_id)))
