# module-archimate

**Port:** 9006. **Type:** core. **Dockerfile:** `druppie/mcp-servers/module-archimate/Dockerfile`.

Read-only query interface over ArchiMate models (Open Exchange Format XML). 8 tools. Used primarily by the `architect` agent to reason about existing enterprise architecture.

## Dockerfile

- Base: `python:3.11-slim`.
- Creates `/models` (read-only mount from `druppie/mcp-servers/module-archimate/models/` or whichever host path is configured).
- Standard FastMCP setup.

## Model support

Parses ArchiMate 3.0 Open Exchange Format XML. Namespace: `http://www.opengroup.org/xsd/archimate/3.0/`.

`v1/module.py:LAYER_MAP` maps element types to architecture layers:
- **Strategy** — Capability, Resource, CourseOfAction
- **Business** — BusinessActor, BusinessRole, BusinessProcess, BusinessService, BusinessObject, Contract
- **Application** — ApplicationComponent, ApplicationService, ApplicationInterface, DataObject
- **Technology** — Node, Device, TechnologyService, Artifact, CommunicationNetwork, SystemSoftware
- **Motivation** — Stakeholder, Driver, Assessment, Goal, Outcome, Principle, Requirement, Constraint

`SKIP_PROPERTIES` excludes Archi-tool internal metadata from property returns.

## Tools (8)

### `list_models`

Returns all model files in `/models`.

### `get_statistics`

Args: `model_name?`.

Element counts per layer/type, relationship counts, view counts. Used by architect to get a high-level overview before diving in.

### `list_elements`

Args: `model_name`, `layer?`, `element_type?`, `max_results?`, `offset?`.

Paginated list of elements, filterable by ArchiMate layer and element type.

### `get_element`

Args: `element_name` or `element_id`, `model_name`.

Full element detail: relationships in/out, views it appears on, properties.

### `list_views`

Args: `model_name`.

All views (diagrams) in the model.

### `get_view`

Args: `view_id`, `model_name`.

Elements and relationships shown on a specific view.

### `search_model`

Args: `query`, `model_name`, `layer?`, `element_type?`, `max_results?`.

Text search across element names, descriptions, property values.

### `get_impact`

Args: `element_name`, `model_name`, `direction?` (`upstream` | `downstream` | `both`), `max_depth?`.

Traverses relationships from the given element, returns connected elements. Intended for change-impact analysis.

## Used by

- **architect** — when proposing a new component, the architect checks existing ArchiMate models for components with overlapping purpose, impact-analyses the change, and cites specific model elements in `technical_design.md`.

## Content management

Model files are curated per deployment; there is no upload tool. To add a new model, drop the `.xml` into the mounted directory and restart the module (cache is module-lifetime).
