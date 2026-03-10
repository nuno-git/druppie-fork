"""Quick test: does pre-approval Mermaid validation catch structural errors?"""
from druppie.execution.tool_executor import ToolExecutor

# Subgraph zonder 'end' — regex vangt dit niet, alleen mmdc
content = """# Test
```mermaid
flowchart TD
  subgraph x
    A --> B
```
"""

te = ToolExecutor.__new__(ToolExecutor)
result = te._validate_make_design_content(content)
print("GELUKT" if result else "NIET GELUKT")
if result:
    print(result[:200])
