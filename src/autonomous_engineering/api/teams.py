"""Team management and explicit assignment decisions, without execution."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from autonomous_engineering.domain.teams import SquadInput, SquadEdit, MemberInput, MemberEdit, ProjectMemberInput, MembershipInput, MembershipEdit, AssignmentInput, ApplyAssignments
from autonomous_engineering.infrastructure.planning_store import PlanningConflict
from autonomous_engineering.infrastructure.team_store import AssignmentWarnings, TeamNotFound


def team_router(store):
    router = APIRouter(tags=['Teams and assignments'])

    def origin(request):
        if request.headers.get('origin') not in {None, str(request.base_url).rstrip('/')}:
            raise HTTPException(403, 'Requests must originate from this local workspace.')

    def project(project_id):
        if store.planning.project(project_id) is None: raise HTTPException(404, 'Project not found.')

    def call(action):
        try: return action()
        except AssignmentWarnings as exc:
            raise HTTPException(409, dict(message=str(exc), warnings=exc.warnings)) from exc
        except PlanningConflict as exc: raise HTTPException(409, str(exc)) from exc
        except TeamNotFound as exc: raise HTTPException(404, str(exc)) from exc
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc

    @router.get('/projects/{project_id}/teams')
    def teams(project_id: UUID):
        project(project_id)
        return store.snapshot(project_id)

    @router.get('/projects/{project_id}/squads')
    def list_squads(project_id: UUID):
        project(project_id)
        return {'squads': store.snapshot(project_id)['squads']}

    @router.post('/projects/{project_id}/squads', status_code=201)
    def create_squad(project_id: UUID, body: SquadInput, request: Request):
        origin(request); project(project_id)
        return call(lambda: store.save_squad(project_id, body))

    @router.patch('/squads/{squad_id}')
    def edit_squad(squad_id: UUID, body: SquadEdit, request: Request):
        origin(request)
        found = store.squad(squad_id)
        if found is None: raise HTTPException(404, 'Squad not found.')
        return call(lambda: store.save_squad(found.project_id, body, squad_id))

    @router.get('/projects/{project_id}/members')
    def list_members(project_id: UUID):
        project(project_id)
        snapshot = store.snapshot(project_id)
        return {'members': snapshot['members'], 'capacities': snapshot['capacities']}

    @router.post('/projects/{project_id}/members', status_code=201)
    def create_member(project_id: UUID, body: ProjectMemberInput, request: Request):
        origin(request); project(project_id)
        return call(lambda: store.save_member(project_id, body))

    @router.patch('/members/{member_id}')
    def edit_member(member_id: UUID, body: MemberEdit, request: Request):
        origin(request)
        found = store.member(member_id)
        if found is None: raise HTTPException(404, 'Member not found.')
        return call(lambda: store.save_workspace_member(body, member_id))

    @router.get('/workspace/members')
    @router.get('/workspace/capacity')
    @router.get('/workspace/teams')
    def workspace():
        return store.workspace_snapshot()

    @router.post('/workspace/members', status_code=201)
    def create_workspace_member(body: MemberInput, request: Request):
        origin(request)
        return call(lambda: store.save_workspace_member(body))

    @router.patch('/workspace/members/{member_id}')
    def edit_workspace_member(member_id: UUID, body: MemberEdit, request: Request):
        origin(request)
        return call(lambda: store.save_workspace_member(body, member_id))

    @router.get('/workspace/members/{member_id}/capacity')
    def member_capacity(member_id: UUID):
        snapshot = store.workspace_snapshot()
        found = next((item for item in snapshot['capacities'] if item.member_id == member_id), None)
        if found is None: raise HTTPException(404, 'Workspace member not found.')
        return found

    @router.get('/projects/{project_id}/memberships')
    def project_memberships(project_id: UUID):
        project(project_id)
        return {'memberships': store.snapshot(project_id)['memberships']}

    @router.post('/projects/{project_id}/memberships', status_code=201)
    def join_project(project_id: UUID, body: MembershipInput, request: Request):
        origin(request); project(project_id)
        return call(lambda: store.save_membership(project_id, body))

    @router.patch('/project-memberships/{membership_id}')
    def edit_membership(membership_id: UUID, body: MembershipEdit, request: Request):
        origin(request)
        found = store.membership(membership_id)
        if found is None: raise HTTPException(404, 'Project membership not found.')
        return call(lambda: store.save_membership(found.project_id, body, membership_id))

    @router.post('/engineering-tasks/{task_id}/assignment')
    def assign(task_id: UUID, body: AssignmentInput, request: Request):
        origin(request)
        return call(lambda: store.assign(task_id, body))

    @router.delete('/engineering-tasks/{task_id}/assignment')
    def unassign(task_id: UUID, revision: int, request: Request):
        origin(request)
        if revision < 0: raise HTTPException(422, 'Revision must be nonnegative.')
        return call(lambda: store.assign(task_id, revision=revision))

    @router.get('/engineering-tasks/{task_id}/recommendations')
    def recommendations(task_id: UUID):
        return call(lambda: store.recommendations(task_id))

    @router.get('/projects/{project_id}/assignment-recommendations')
    def suggested_plan(project_id: UUID):
        project(project_id)
        return store.suggested_plan(project_id)

    @router.post('/projects/{project_id}/apply-assignment-recommendations')
    def apply(project_id: UUID, body: ApplyAssignments, request: Request):
        origin(request); project(project_id)
        return call(lambda: store.apply(project_id, body))

    return router
