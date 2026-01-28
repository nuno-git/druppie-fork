"""Admin API routes for database exploration.

Full database browser with navigation between linked records.

NOTE: The following tables have been removed (data now stored as JSONB):
- tool_call_arguments → arguments now in tool_calls.arguments
- hitl_question_choices → choices now in hitl_questions.choices

See druppie/db/models.py for design decision rationale.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func, inspect
import structlog

from druppie.api.deps import get_db, require_admin
from druppie.db.models import (
    User, UserRole, UserToken,
    Project, Session, Workspace,
    Workflow, WorkflowStep,
    AgentRun, Message, ToolCall,
    # NOTE: ToolCallArgument removed - arguments now JSONB in ToolCall.arguments
    Approval, HitlQuestion,
    # NOTE: HitlQuestionChoice removed - choices now JSONB in HitlQuestion.choices
    Build, Deployment, LlmCall,
    SessionEvent,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

# All models mapped by table name
# NOTE: tool_call_arguments and hitl_question_choices removed - data now in JSONB columns
MODELS = {
    "users": User,
    "user_roles": UserRole,
    "user_tokens": UserToken,
    "projects": Project,
    "sessions": Session,
    "workspaces": Workspace,
    "workflows": Workflow,
    "workflow_steps": WorkflowStep,
    "agent_runs": AgentRun,
    "messages": Message,
    "tool_calls": ToolCall,
    # tool_call_arguments removed - see tool_calls.arguments JSONB column
    "approvals": Approval,
    "hitl_questions": HitlQuestion,
    # hitl_question_choices removed - see hitl_questions.choices JSONB column
    "builds": Build,
    "deployments": Deployment,
    "llm_calls": LlmCall,
    "session_events": SessionEvent,
}

# Define foreign key relationships for navigation
RELATIONS = {
    "sessions": {
        "user_id": ("users", "id"),
        "project_id": ("projects", "id"),
    },
    "workspaces": {
        "session_id": ("sessions", "id"),
        "project_id": ("projects", "id"),
    },
    "workflows": {
        "session_id": ("sessions", "id"),
    },
    "workflow_steps": {
        "workflow_id": ("workflows", "id"),
    },
    "agent_runs": {
        "session_id": ("sessions", "id"),
        "workflow_step_id": ("workflow_steps", "id"),
        "parent_run_id": ("agent_runs", "id"),
    },
    "messages": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
    },
    "tool_calls": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
    },
    # tool_call_arguments removed - arguments now JSONB in tool_calls.arguments
    "approvals": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
        "tool_call_id": ("tool_calls", "id"),
        "workflow_step_id": ("workflow_steps", "id"),
        "resolved_by": ("users", "id"),
    },
    "hitl_questions": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
    },
    # hitl_question_choices removed - choices now JSONB in hitl_questions.choices
    "builds": {
        "project_id": ("projects", "id"),
        "session_id": ("sessions", "id"),
    },
    "deployments": {
        "build_id": ("builds", "id"),
        "project_id": ("projects", "id"),
    },
    "llm_calls": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
    },
    "user_roles": {
        "user_id": ("users", "id"),
    },
    "user_tokens": {
        "user_id": ("users", "id"),
    },
    "session_events": {
        "session_id": ("sessions", "id"),
        "agent_run_id": ("agent_runs", "id"),
        "tool_call_id": ("tool_calls", "id"),
        "approval_id": ("approvals", "id"),
        "hitl_question_id": ("hitl_questions", "id"),
    },
}

# Reverse relations (what tables link TO this table)
REVERSE_RELATIONS = {
    "users": [
        ("sessions", "user_id"),
        ("projects", "owner_id"),
        ("user_roles", "user_id"),
        ("user_tokens", "user_id"),
        ("approvals", "resolved_by"),
    ],
    "projects": [
        ("sessions", "project_id"),
        ("workspaces", "project_id"),
        ("builds", "project_id"),
        ("deployments", "project_id"),
    ],
    "sessions": [
        ("workspaces", "session_id"),
        ("workflows", "session_id"),
        ("agent_runs", "session_id"),
        ("messages", "session_id"),
        ("tool_calls", "session_id"),
        ("approvals", "session_id"),
        ("hitl_questions", "session_id"),
        ("builds", "session_id"),
        ("llm_calls", "session_id"),
        ("session_events", "session_id"),
    ],
    "workflows": [
        ("workflow_steps", "workflow_id"),
    ],
    "workflow_steps": [
        ("agent_runs", "workflow_step_id"),
        ("approvals", "workflow_step_id"),
    ],
    "agent_runs": [
        ("agent_runs", "parent_run_id"),
        ("messages", "agent_run_id"),
        ("tool_calls", "agent_run_id"),
        ("approvals", "agent_run_id"),
        ("hitl_questions", "agent_run_id"),
        ("llm_calls", "agent_run_id"),
        ("session_events", "agent_run_id"),
    ],
    "tool_calls": [
        ("tool_call_arguments", "tool_call_id"),
        ("approvals", "tool_call_id"),
        ("session_events", "tool_call_id"),
    ],
    "hitl_questions": [
        ("hitl_question_choices", "question_id"),
        ("session_events", "hitl_question_id"),
    ],
    "builds": [
        ("deployments", "build_id"),
    ],
    "approvals": [
        ("session_events", "approval_id"),
    ],
}


def serialize_value(val):
    """Convert a value to JSON-serializable format."""
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    if hasattr(val, '__str__') and not isinstance(val, (str, int, float, bool, list, dict)):
        return str(val)
    return val


def row_to_dict(row) -> dict:
    """Convert a SQLAlchemy model instance to a dictionary."""
    if hasattr(row, 'to_dict'):
        return row.to_dict()

    result = {}
    mapper = inspect(row.__class__)
    for column in mapper.columns:
        val = getattr(row, column.key)
        result[column.key] = serialize_value(val)
    return result


class TableInfo(BaseModel):
    name: str
    count: int
    columns: list[str]


class TablesResponse(BaseModel):
    tables: list[TableInfo]
    total_records: int


class TableDataResponse(BaseModel):
    table: str
    columns: list[str]
    rows: list[dict]
    total: int
    page: int
    limit: int
    total_pages: int
    relations: dict  # field -> (target_table, target_field)


class RecordResponse(BaseModel):
    table: str
    record: dict
    relations: dict  # field -> (target_table, target_field)
    reverse_relations: dict  # table -> [{field, count}]


@router.get("/tables", response_model=TablesResponse)
async def list_tables(
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """List all database tables with counts."""
    tables = []
    total = 0

    for name, model in MODELS.items():
        try:
            count = db.query(func.count()).select_from(model).scalar() or 0
            mapper = inspect(model)
            columns = [col.key for col in mapper.columns]
            tables.append(TableInfo(name=name, count=count, columns=columns))
            total += count
        except Exception as e:
            logger.warning("table_count_error", table=name, error=str(e))
            tables.append(TableInfo(name=name, count=0, columns=[]))

    # Sort by count descending
    tables.sort(key=lambda t: t.count, reverse=True)

    return TablesResponse(tables=tables, total_records=total)


@router.get("/table/{table_name}", response_model=TableDataResponse)
async def get_table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    order_by: str = Query(None, description="Column to sort by"),
    order_dir: str = Query("desc", description="Sort direction: asc or desc"),
    filter_field: str = Query(None, description="Field to filter on"),
    filter_value: str = Query(None, description="Value to filter by"),
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Get paginated data from a table."""
    if table_name not in MODELS:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")

    model = MODELS[table_name]
    mapper = inspect(model)
    columns = [col.key for col in mapper.columns]

    query = db.query(model)

    # Apply filter
    if filter_field and filter_value:
        if hasattr(model, filter_field):
            col = getattr(model, filter_field)
            # Try exact match for UUIDs, otherwise use ilike for strings
            try:
                query = query.filter(col == filter_value)
            except Exception:
                query = query.filter(col.ilike(f"%{filter_value}%"))

    # Get total count
    total = query.count()

    # Apply ordering
    if order_by and hasattr(model, order_by):
        col = getattr(model, order_by)
        if order_dir == "asc":
            query = query.order_by(col.asc())
        else:
            query = query.order_by(col.desc())
    elif hasattr(model, 'created_at'):
        query = query.order_by(model.created_at.desc())
    elif hasattr(model, 'id'):
        query = query.order_by(model.id.desc())

    # Paginate
    offset = (page - 1) * limit
    rows = query.offset(offset).limit(limit).all()

    # Convert to dicts
    row_dicts = [row_to_dict(r) for r in rows]

    # Get relations for this table
    relations = RELATIONS.get(table_name, {})

    total_pages = (total + limit - 1) // limit if limit > 0 else 0

    return TableDataResponse(
        table=table_name,
        columns=columns,
        rows=row_dicts,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        relations=relations,
    )


@router.get("/table/{table_name}/{record_id}", response_model=RecordResponse)
async def get_record(
    table_name: str,
    record_id: str,
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Get a single record with its relations."""
    if table_name not in MODELS:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")

    model = MODELS[table_name]

    # Find the record
    record = None
    if hasattr(model, 'id'):
        record = db.query(model).filter(model.id == record_id).first()

    if not record:
        raise HTTPException(status_code=404, detail=f"Record not found: {record_id}")

    record_dict = row_to_dict(record)

    # Get relations for this table
    relations = RELATIONS.get(table_name, {})

    # Get reverse relations with counts
    reverse_rels = {}
    for ref_table, ref_field in REVERSE_RELATIONS.get(table_name, []):
        if ref_table in MODELS:
            ref_model = MODELS[ref_table]
            if hasattr(ref_model, ref_field):
                col = getattr(ref_model, ref_field)
                count = db.query(func.count()).select_from(ref_model).filter(col == record_id).scalar() or 0
                if count > 0:
                    if ref_table not in reverse_rels:
                        reverse_rels[ref_table] = []
                    reverse_rels[ref_table].append({"field": ref_field, "count": count})

    return RecordResponse(
        table=table_name,
        record=record_dict,
        relations=relations,
        reverse_relations=reverse_rels,
    )


# Keep the stats endpoint for backwards compatibility
@router.get("/stats")
async def get_database_stats(
    user: dict = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Get database statistics."""
    tables_response = await list_tables(user, db)
    return {
        "tables": [{"name": t.name, "count": t.count} for t in tables_response.tables],
        "total_records": tables_response.total_records,
    }
