"""Parameter models for archimate MCP tools.

These define the parameter types for validation. Descriptions come from
mcp_config.yaml - these models are purely for type-safe validation.
"""

from pydantic import BaseModel, Field


class GetStatisticsParams(BaseModel):
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")


class ListElementsParams(BaseModel):
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")
    layer: str = Field(default="", description="Filter by layer: Strategy, Motivation, Business, Application, Technology, Physical")
    element_type: str = Field(default="", description="Filter by type: BusinessProcess, ApplicationComponent, etc.")
    max_results: int = Field(default=50, description="Maximum results to return (default: 50)")
    offset: int = Field(default=0, description="Offset for pagination (default: 0)")


class GetElementParams(BaseModel):
    element_name: str = Field(description="Element name or ID")
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")


class ListViewsParams(BaseModel):
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")


class GetViewParams(BaseModel):
    view_id: str = Field(description="View name or ID")
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")


class SearchModelParams(BaseModel):
    query: str = Field(description="Search term (matches name, description, properties)")
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")
    layer: str = Field(default="", description="Filter by layer")
    element_type: str = Field(default="", description="Filter by element type")
    max_results: int = Field(default=20, description="Maximum results (default: 20)")


class GetImpactParams(BaseModel):
    element_name: str = Field(description="Element name or ID to start from")
    model_name: str = Field(default="", description="Name of the ArchiMate model (optional, defaults to first model)")
    direction: str = Field(default="both", description="Direction: 'downstream' (what this serves), 'upstream' (what depends on this), or 'both' (default)")
    max_depth: int = Field(default=3, description="Maximum traversal depth (default: 3)")
