# Integrating glassworm-hunter into Druppie's Architecture

## Context

Jeremy Bode (Information Security Officer) specified the following requirements:

> "Ik wil de glassworm-hunter tool structureel integreren in onze AI-architectuur. De security agent gaat iedere output van de builder agent scannen met de hunter, alle agents moeten werken in een geïsoleerde container, waarbij er een verplichte scan moet plaatsvinden voordat de code deze sandbox verlaat en daarnaast een 'filter' dat de output van de agents automatisch stript van Unicode-tekens."

Translation of requirements:
1. **Structural integration**: glassworm-hunter must be a permanent part of our AI architecture
2. **Security agent scanning**: A security agent scans every output of the builder agent
3. **Isolated containers**: All agents work in isolated containers
4. **Mandatory exit scan**: Code must be scanned before leaving the sandbox
5. **Unicode stripping filter**: Agent output is automatically stripped of Unicode characters

This document details how to implement each requirement.

---

## Requirement 1: Structural Integration of glassworm-hunter

### Architecture

```
                    ┌─────────────────────┐
                    │   Developer / User   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │    Druppie Backend   │
                    │    (FastAPI)         │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Orchestrator       │
                    │   (LangGraph)        │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │  Builder Agent  │ │ Reviewer Agent│ │ Other Agents  │
    │  (Sandbox)      │ │ (Sandbox)     │ │ (Sandbox)     │
    └─────────┬──────┘ └──────┬───────┘ └──────┬───────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   SECURITY GATE     │  ◄── NEW: glassworm-hunter
                    │   (Scan + Strip)    │      + Unicode filter
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Workspace Volume   │
                    │   (Clean output)     │
                    └─────────────────────┘
```

### Integration Points

**A. Pre-installed in sandbox base image:**

Add glassworm-hunter to `Dockerfile.sandbox`:
```dockerfile
# Install glassworm-hunter in sandbox
RUN pip install glassworm-hunter
```

**B. As a CI/CD pipeline step:**

Add to `.github/workflows/security-scan.yml`:
```yaml
- name: Run GlassWorm scan
  run: |
    pip install glassworm-hunter
    glassworm-hunter scan --path .
```

**C. As a Docker Compose service (cache scanner enhancement):**

Extend the existing `cache-scanner` service or add a parallel `security-scanner` service that runs glassworm-hunter against the workspace and sandbox output.

---

## Requirement 2: Security Agent Scanning Builder Output

### Design: Security Gate in Control Plane

The control plane (`background-agents/packages/local-control-plane/`) already bridges the sandbox and main networks. This is the natural place to add a security gate.

### Implementation Options

**Option A: Inline scan in control plane (Recommended)**

Modify the control plane to intercept all file writes from sandbox to workspace:

```
Builder Agent → writes file → Sandbox filesystem
                                    │
                              Control Plane intercepts
                                    │
                              ┌─────▼─────┐
                              │ 1. Strip   │  Unicode stripping filter
                              │    Unicode │
                              ├───────────┤
                              │ 2. Scan    │  glassworm-hunter
                              │    Content │
                              ├───────────┤
                              │ 3. Decide  │  Clean → allow
                              │            │  Flagged → quarantine + alert
                              └─────┬─────┘
                                    │
                              Workspace Volume (if clean)
```

**Pros**: Single enforcement point, cannot be bypassed, inline with existing architecture
**Cons**: Adds latency to every file operation, control plane becomes critical path

**Option B: Dedicated security-scanner sidecar**

Run a separate container alongside each sandbox that monitors file changes:

**Pros**: Decoupled from control plane, can be updated independently
**Cons**: More infrastructure, potential race conditions

**Option C: Post-session batch scan**

Scan all output after the agent session completes, before merging to workspace:

**Pros**: Simplest implementation, no latency impact during session
**Cons**: Doesn't catch issues in real-time, malicious code could already have executed within the sandbox

### Recommendation: Option A (inline scan)

The control plane is already the gatekeeper between sandbox and main networks. Adding security scanning here is architecturally clean and provides real-time protection.

---

## Requirement 3: Isolated Containers

See [05-ai-agent-sandboxing.md](05-ai-agent-sandboxing.md) for full analysis.

**Summary**: 
- Immediate: Switch to gVisor runtime (`runsc`) for better-than-Docker isolation
- Production: Enable Kata Containers via existing `SANDBOX_RUNTIME=kata` config
- Enhance network isolation: Set sandbox network to `internal: true`

---

## Requirement 4: Mandatory Exit Scan

### Design: Scan-Before-Exit Gate

Every piece of code/data that leaves the sandbox must pass through the security gate:

```python
# Pseudocode for security gate
async def security_gate(file_content: str, file_path: str) -> ScanResult:
    """Mandatory security scan before code exits sandbox."""
    
    # Step 1: Strip suspicious Unicode
    cleaned_content, stripped_chars = unicode_filter.strip(file_content)
    if stripped_chars:
        alert(f"Stripped {len(stripped_chars)} suspicious Unicode chars from {file_path}")
    
    # Step 2: Run glassworm-hunter
    gw_result = glassworm_hunter.scan_content(cleaned_content)
    if gw_result.is_flagged:
        quarantine(file_path, cleaned_content, gw_result)
        alert(f"GlassWorm detected in {file_path}: {gw_result.details}")
        return ScanResult(allowed=False, reason=gw_result.details)
    
    # Step 3: Basic pattern checks
    pattern_result = check_suspicious_patterns(cleaned_content)
    if pattern_result.is_suspicious:
        alert(f"Suspicious pattern in {file_path}: {pattern_result.details}")
        # Don't block, but alert for human review
    
    return ScanResult(allowed=True, content=cleaned_content)
```

### What Gets Scanned

| Output Type | Scan Method |
|-------------|------------|
| Source code files (.py, .js, .ts) | Full scan (Unicode strip + glassworm-hunter + pattern check) |
| Configuration files (.yaml, .json, .toml) | Full scan |
| Lock files (package-lock.json, requirements.txt) | Full scan + lockfile-lint |
| Binary files | Hash verification only |
| Log output | Unicode strip only |

### Quarantine Behavior

When the scan flags a file:
1. File is NOT written to the workspace
2. File content is stored in a quarantine directory with scan results
3. Alert is sent to the security team (via Druppie notification system)
4. The agent session is paused pending human review
5. Human can approve (release from quarantine) or reject (destroy)

---

## Requirement 5: Unicode Stripping Filter

### Design: Automatic Filter on All Agent Output

See [04-unicode-attack-detection.md](04-unicode-attack-detection.md) for the full Unicode analysis.

### Implementation

```python
import unicodedata

class UnicodeSecurityFilter:
    """Strips suspicious Unicode characters from agent output."""
    
    # Characters to always allow
    ALLOWED_CONTROL_CHARS = {'\n', '\r', '\t'}
    
    # Unicode categories to strip
    STRIP_CATEGORIES = {'Cf', 'Cc'}  # Format and Control characters
    
    # Code point ranges to strip
    STRIP_RANGES = [
        (0xE000, 0xF8FF),      # Private Use Area
        (0xF0000, 0xFFFFD),    # Supplementary Private Use Area-A
        (0x100000, 0x10FFFD),  # Supplementary Private Use Area-B
        (0xFE00, 0xFE0F),     # Variation Selectors
        (0xE0100, 0xE01EF),   # Variation Selectors Supplement
        (0xE0001, 0xE007F),   # Unicode Tags
        (0x200B, 0x200F),     # Zero-width and directional characters
        (0x202A, 0x202E),     # Bidirectional formatting
        (0x2060, 0x2069),     # Invisible operators and isolates
    ]
    
    def strip(self, text: str) -> tuple[str, list[dict]]:
        """Strip suspicious Unicode and return (cleaned_text, stripped_chars_info)."""
        result = []
        stripped = []
        
        for i, char in enumerate(text):
            code_point = ord(char)
            category = unicodedata.category(char)
            
            # Allow standard whitespace
            if char in self.ALLOWED_CONTROL_CHARS:
                result.append(char)
                continue
            
            # Strip suspicious categories
            if category in self.STRIP_CATEGORIES:
                stripped.append({
                    'position': i,
                    'code_point': f'U+{code_point:04X}',
                    'category': category,
                    'name': unicodedata.name(char, 'UNKNOWN')
                })
                continue
            
            # Strip suspicious ranges
            if any(start <= code_point <= end for start, end in self.STRIP_RANGES):
                stripped.append({
                    'position': i,
                    'code_point': f'U+{code_point:04X}',
                    'category': category,
                    'name': unicodedata.name(char, 'UNKNOWN')
                })
                continue
            
            result.append(char)
        
        return ''.join(result), stripped
```

### Integration in Agent Pipeline

The filter runs at two points:

1. **On LLM response**: Before the orchestrator processes the agent's output
   - Location: `druppie/execution/orchestrator.py` (after receiving LLM response)
   - Purpose: Catch injected Unicode from compromised LLM responses

2. **On sandbox exit**: Before code leaves the sandbox (part of security gate)
   - Location: Control plane security gate
   - Purpose: Catch Unicode from any source (installed packages, generated code, etc.)

---

## Implementation Roadmap

### Phase 1: Immediate (Week 1)

1. Install glassworm-hunter and run full scan of current codebase
2. Add Unicode stripping filter to `druppie/core/` as a utility
3. Wire filter into orchestrator output path
4. Add glassworm-hunter to CI/CD pipeline

### Phase 2: Security Gate (Week 2-3)

1. Implement security gate in control plane
2. Add scan-before-exit logic for all sandbox output
3. Implement quarantine directory and alerting
4. Test with known GlassWorm samples

### Phase 3: Hardened Isolation (Week 3-4)

1. Switch sandbox runtime to gVisor
2. Restrict sandbox network to internal-only
3. Implement package installation controls
4. Add pre-approved package allowlist

### Phase 4: Monitoring & Iteration (Ongoing)

1. Monitor false positive rates and tune filters
2. Update glassworm-hunter IOC database regularly
3. Review quarantined items weekly
4. Adjust security gate rules based on findings
