"""Global human budgets and AI queue balancing, without runtime inference."""
from autonomous_engineering.domain.teams import AssignmentRecommendation, MemberCapacity, ProjectCapacity


def capacities(members, tasks, projects=None):
    names = projects or {}
    result = {}
    for member in members:
        owned = [task for task in tasks if task.assignee_id == member.id and task.status != 'done']
        human = member.member_type == 'human'
        load = sum(task.estimated_hours for task in owned)
        assignable = member.weekly_capacity_hours * member.target_utilization if human else None
        project_ids = sorted({task.project_id for task in owned}, key=str)
        breakdown = tuple(ProjectCapacity(project_id=identity, project_name=names.get(str(identity), str(identity)),
            planned_load_hours=round(sum(task.estimated_hours for task in owned if task.project_id == identity), 4) if human else None,
            assigned_task_count=sum(task.project_id == identity for task in owned)) for identity in project_ids)
        result[member.id] = MemberCapacity(member_id=member.id,
            planned_load_hours=round(load, 4) if human else None, assigned_task_count=len(owned),
            assignable_capacity_hours=round(assignable, 4) if human else None,
            reserved_capacity_hours=round(member.weekly_capacity_hours - assignable, 4) if human else None,
            remaining_capacity_hours=round(assignable - load, 4) if human else None,
            assigned_queue_depth=None if human else len(owned),
            max_concurrent_executions=None if human else member.max_concurrent_executions,
            project_breakdown=breakdown)
    return result


def dependency_warnings(task, tasks):
    indexed = {item.id: item for item in tasks}
    return [f'{task.key} depends on {indexed[ref.task_id].key}; dependency not completed.'
        for ref in task.dependencies if ref.task_id in indexed and indexed[ref.task_id].status != 'done']


def assignment_warnings(task, member, squad, capacity, tasks):
    warnings = dependency_warnings(task, tasks)
    if not member.active: warnings.append(f'{member.name} is inactive.')
    if task.technical_area not in {skill.technical_area for skill in member.skills}:
        warnings.append(f'{member.name} has no configured {task.technical_area} skill.')
    if task.technical_area not in squad.technical_areas:
        warnings.append(f'{squad.name} does not cover {task.technical_area}.')
    already_owned = task.assignee_id == member.id and task.status != 'done'
    extra = task.estimated_hours if task.status != 'done' and not already_owned else 0
    if member.member_type == 'human':
        excess = extra - capacity.remaining_capacity_hours
        if excess > 0:
            warnings.append(f'This assignment would exceed {member.name}\'s global planned capacity by {excess:g}h.')
    elif member.availability != 'available':
        warnings.append(f'{member.name} is {member.availability}.')
    return warnings


def recommend(task, members, squads, tasks, memberships):
    if task.assignee_id is not None or task.status == 'done': return []
    loads = capacities(members, tasks)
    squad_map = {squad.id: squad for squad in squads}
    joined = {membership.member_id: membership for membership in memberships
        if membership.project_id == task.project_id and membership.active}
    result = []
    for member in members:
        membership = joined.get(member.id)
        if membership is None or not member.active or (member.member_type == 'ai' and member.availability != 'available'):
            continue
        skill = next((skill for skill in member.skills if skill.technical_area == task.technical_area), None)
        squad = squad_map.get(membership.squad_id)
        if squad is None or skill is None or (task.squad_id is not None and membership.squad_id != task.squad_id): continue
        capacity = loads[member.id]
        human = member.member_type == 'human'
        fits = capacity.remaining_capacity_hours >= task.estimated_hours if human else True
        squad_match = task.technical_area in squad.technical_areas
        # Queue balancing is bounded to <5 points, below one proficiency level.
        balance = max(0, min(1, capacity.remaining_capacity_hours / capacity.assignable_capacity_hours)) if human and capacity.assignable_capacity_hours else (1 / (1 + capacity.assigned_queue_depth) if not human else 0)
        score = skill.proficiency * 10 + int(squad_match) * 5 + balance * 5
        reasons = [f'Skill match: {task.technical_area} {skill.proficiency}/5.', f'Squad area match: {"yes" if squad_match else "no"}.',
            f'Remaining global planned capacity: {capacity.remaining_capacity_hours:g}h.' if human else f'Available; assigned queue: {capacity.assigned_queue_depth} unfinished tasks. Queue is ownership, not execution concurrency.']
        result.append(AssignmentRecommendation(task_id=task.id, member_id=member.id, squad_id=membership.squad_id,
            score=round(score,4), skill_proficiency=skill.proficiency, fits_capacity=fits, reasons=tuple(reasons),
            warnings=tuple(assignment_warnings(task,member,squad,capacity,tasks)), remaining_capacity_hours=capacity.remaining_capacity_hours,
            assigned_queue_depth=capacity.assigned_queue_depth))
    return sorted(result,key=lambda item:(not item.fits_capacity,-item.score,str(item.member_id)))
