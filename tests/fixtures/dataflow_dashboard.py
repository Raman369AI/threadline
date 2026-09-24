"""Source-only Dashboard fixture. Threadline parses this file; it is never imported."""

from fastapi import Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

templates = Jinja2Templates(directory='templates')


class BaseProject:
    tenant_id: int


class Project(BaseProject):
    id: int
    name: str
    approved: bool
    description: str = ''  # Deliberately unused by dashboard.


class Task:
    id: int
    project_id: int
    done: bool
    needs_attention: bool
    label: str = ''  # Deliberately unused by dashboard.


class AgentSession:
    id: int
    task_id: int
    status: str


class AgentApproval:
    id: int
    task_id: int
    status: str


class Repository:
    def get(self):
        return []


class Controller:
    def __init__(self, repo: Repository):
        self.repo: Repository = repo

    def index(self):
        return self.repo.get()


def call_receiver():
    repo = Repository()
    return repo.get()


def get_db():
    raise NotImplementedError


def _role_assignment_payload(db):
    return {'assigned': 0}


async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    projects_result = await db.execute(select(Project))
    projects = projects_result.scalars().all()
    visible_projects = [project for project in projects if project.approved]
    stats = {'total_projects': len(visible_projects)}
    recent_projects = sorted(visible_projects, key=lambda project: project.id)[:5]

    for project in recent_projects:
        task_count_result = await db.execute(select(func.count(Task.id)))
        project.task_count = task_count_result.scalar()

    task_result = await db.execute(select(Task))
    recent_tasks = task_result.scalars().all()
    total_tasks_result = await db.execute(select(func.count(Task.id)))
    stats['total_tasks'] = total_tasks_result.scalar()
    completed_tasks_result = await db.execute(select(func.count(Task.id)))
    stats['completed_tasks'] = completed_tasks_result.scalar()
    stats.update(_role_assignment_payload(db))

    visible_ids = {project.id for project in visible_projects}
    task_rows_result = await db.execute(select(Task))
    task_rows = [task for task in task_rows_result.scalars().all()
                 if task.project_id in visible_ids]
    tasks_by_id = {task.id: task for task in task_rows}
    approval_result = await db.execute(select(AgentApproval))
    approval_rows = approval_result.scalars().all()
    session_result = await db.execute(select(AgentSession))
    session_rows = session_result.scalars().all()
    latest_sessions = {}
    for session in session_rows:
        latest_sessions.setdefault(session.task_id, session)

    attention = []
    for task in task_rows:
        if task.needs_attention:
            attention.append({'task': task})
    for approval in approval_rows:
        if approval.status == 'pending':
            attention.append({'approval': approval})
    for session in latest_sessions.values():
        if session.status == 'error':
            attention.append({'session': session})
    attention = attention[:12]
    return templates.TemplateResponse(request, 'dashboard.html', {
        'request': request,
        'stats': stats,
        'recent_projects': recent_projects,
        'recent_tasks': recent_tasks,
        'attention': attention,
    }, headers={'x-test': 'fixture'})


def edit_values(items):
    original = items
    items = [1]
    copied = list(original)
    unknown = transform(original)
    original.append(2)
    values = {'old': original}
    values['new'] = items
    del values['old']
    return values


def branch(value, enabled):
    result = value
    if enabled:
        result = [value]
    return result


def expression_paths(flag, items):
    conditional = items.append(1) if flag else None
    flag and items.append(2)
    later = (transform(item) for item in items)
    return items, conditional, later


def mutate(items):
    items.append(3)
    return len(items)


def call_mutate(items):
    count = mutate(items)
    return items, count


def unknown_prior_state(mapping, project):
    mapping['new'] = 1
    project.task_count = 2
    del mapping['old']
    del project.label
    return mapping


def arbitrary_all(receiver):
    return receiver.all()


def shadowed_list(list, value):
    return list(value)


def finally_return(items):
    try:
        return items
    finally:
        items.append(1)
