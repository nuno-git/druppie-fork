# Unicode-Based Attack Detection and Prevention

## The Threat

Invisible Unicode characters are the primary mechanism used by GlassWorm to hide malicious code within seemingly legitimate source files. This is not a theoretical attack - it has already compromised 400+ repositories and was the exact technique used in the opencode-ai infection that affected our project.

## How Invisible Unicode Attacks Work

### Encoding Techniques

1. **Private Use Area (PUA) Code Points**: Unicode code points in ranges U+E000-U+F8FF and U+F0000-U+FFFFD are "private use" - they have no standard display. Attackers map these to alphabet letters, encoding executable code as invisible characters.

2. **Variation Selectors**: Unicode variation selectors (U+FE00-U+FE0F, U+E0100-U+E01EF) are formatting characters that modify the preceding character. They're invisible and can encode data.

3. **Zero-Width Characters**: Zero-width space (U+200B), zero-width joiner (U+200D), zero-width non-joiner (U+200C) are invisible and can encode binary data.

4. **Bidirectional Control Characters**: Right-to-left override (U+202E) and similar characters can reorder how code is displayed without changing execution order (Trojan Source attack).

5. **Unicode Tag Characters**: U+E0001-U+E007F are invisible tag characters that can encode full ASCII payloads.

### Why Standard Tools Miss Them

- **Text editors**: Most editors do not display invisible Unicode characters
- **Git diffs**: GitHub/GitLab diff views don't show invisible characters
- **Linters**: ESLint, Ruff, etc. focus on code structure, not character encoding
- **Code review**: Human reviewers physically cannot see the malicious payload
- **grep/search**: Standard text search doesn't match invisible characters

### Real-World Example (GlassWorm)

```
// This looks like an empty comment in any editor:
//                                                    
// But it actually contains thousands of invisible Unicode variation selectors
// that decode to a full credential-stealing payload when processed by the
// GlassWorm decoder
```

---

## Detection Approach 1: glassworm-hunter

### How It Works
Purpose-built Python scanner that detects GlassWorm-specific patterns: invisible Unicode payloads, decoder patterns, C2 infrastructure markers, and credential harvesting code.

### Pros
- **GlassWorm-specific**: Tuned for the exact threat we're facing
- **Zero network requests**: All scanning is local (privacy-preserving)
- **IOC database**: Maintains and updates indicators of compromise
- **Multi-target**: Scans VS Code extensions, npm packages, PyPI packages, git repos
- **Free and open-source**: MIT license

### Cons
- **Narrow scope**: Only detects GlassWorm and closely related payloads
- **New tool**: Less community vetting than established scanners
- **Python dependency**: Requires Python to run
- **IOC-based**: New GlassWorm variants with different IOCs may be missed initially

### Verdict
**Must-have for immediate threat response.** Deploy now to scan our codebase and integrate into CI/CD. But don't rely on it as sole Unicode defense.

---

## Detection Approach 2: anti-trojan-source

### How It Works
Detects problematic Unicode characters in source files using a category-based approach. Identifies 277+ explicit confusable characters plus entire Unicode categories (Format/Cf and Control/Cc).

```bash
# npm package
npx anti-trojan-source --files "src/**/*.{js,ts,py}"

# ESLint plugin
npm install eslint-plugin-anti-trojan-source

# Docker
docker run lirantal/anti-trojan-source --files "**/*.py"
```

### Pros
- **Future-proof**: Category-based detection catches NEW invisible character techniques, not just known ones
- **Comprehensive**: 277 explicit confusables + all Cf/Cc Unicode categories
- **Multiple integration paths**: CLI, ESLint plugin, Docker image, npm package
- **Bidirectional detection**: Also catches Trojan Source attacks (bidi override)
- **Fast**: Can run as pre-commit hook
- **Well-maintained**: Active development, good community adoption

### Cons
- **False positives possible**: Some legitimate files may contain Unicode formatting (e.g., internationalized content, emoji)
- **JavaScript-focused**: Primary tooling is npm-based (but Docker image works for any language)
- **Source files only**: Doesn't scan compiled/bundled output

### Verdict
**Strongly recommended as primary Unicode defense.** Category-based detection is future-proof against new invisible character techniques. Complements glassworm-hunter's IOC-based approach.

---

## Detection Approach 3: Custom Unicode Stripping Filter

### How It Works
Build a filter that strips all non-essential Unicode characters from AI agent output before it can be committed or deployed. This is specifically relevant for Druppie because AI agents (builder, reviewer, etc.) generate code that could contain injected Unicode.

```python
import unicodedata

ALLOWED_CATEGORIES = {'L', 'N', 'P', 'S', 'Z'}  # Letters, Numbers, Punctuation, Symbols, Separators

def strip_suspicious_unicode(text: str) -> str:
    """Remove all Unicode characters in Format (Cf) and Control (Cc) categories,
    except for standard whitespace (\\n, \\r, \\t)."""
    result = []
    for char in text:
        category = unicodedata.category(char)
        if category in ('Cf', 'Cc') and char not in ('\n', '\r', '\t'):
            continue  # Strip invisible formatting and control characters
        if ord(char) >= 0xE000 and ord(char) <= 0xF8FF:
            continue  # Strip Private Use Area
        if ord(char) >= 0xF0000 and ord(char) <= 0xFFFFD:
            continue  # Strip Supplementary Private Use Area-A
        if ord(char) >= 0x100000 and ord(char) <= 0x10FFFD:
            continue  # Strip Supplementary Private Use Area-B
        result.append(char)
    return ''.join(result)
```

### Pros
- **Proactive defense**: Strips malicious characters before they can do harm
- **AI agent specific**: Addresses Jeremy's requirement for filtering agent output
- **No false negatives**: All invisible characters are removed regardless of technique
- **Custom to our architecture**: Can be integrated directly into our agent pipeline

### Cons
- **False positives**: May strip legitimate Unicode in multilingual content
- **Maintenance**: Need to keep category list up to date
- **Not a scanner**: Doesn't detect or report - just strips silently
- **Could mask attacks**: Stripping without alerting means we don't learn about attempted attacks

### Verdict
**Recommended as agent output filter** combined with alerting. Strip AND log when suspicious characters are found. This directly addresses Jeremy's requirement for "a filter that strips Unicode characters from agent output."

---

## Detection Approach 4: Git Pre-receive Hook (Server-side)

### How It Works
Install a server-side Git hook on Gitea that scans all incoming pushes for suspicious Unicode characters. Rejects pushes that contain invisible characters.

### Pros
- **Enforcement at the gate**: Cannot be bypassed by developers
- **Covers all code paths**: Whether code comes from humans or AI agents
- **Server-side**: Doesn't depend on developer machine configuration

### Cons
- **Gitea complexity**: Requires custom Gitea configuration
- **Performance impact**: Scanning large pushes takes time
- **Emergency override needed**: Must have a bypass for legitimate Unicode (with approval)

### Verdict
**Recommended for medium-term.** Powerful enforcement mechanism, but requires Gitea configuration work.

---

## Comparison Matrix

| Approach | Scope | Speed | False Positives | Future-Proof | Effort |
|----------|-------|-------|-----------------|--------------|--------|
| glassworm-hunter | GlassWorm only | Fast | Very low | No (IOC-based) | Low |
| anti-trojan-source | All invisible Unicode | Fast | Low-Medium | **Yes** (category-based) | Low |
| Custom strip filter | Agent output | Instant | Medium | **Yes** | Medium |
| Git pre-receive hook | All pushes | Medium | Low | **Yes** | High |

## Recommended Layered Approach

1. **Immediate**: Run glassworm-hunter on entire codebase (one-time scan)
2. **Pre-commit hook**: anti-trojan-source (catches invisible chars before commit)
3. **Agent pipeline**: Custom Unicode stripping filter on all agent output
4. **CI/CD gate**: Both glassworm-hunter AND anti-trojan-source
5. **Medium-term**: Gitea pre-receive hook (server-side enforcement)

This provides defense-in-depth: the agent filter catches it at generation, pre-commit catches it at developer machines, CI catches it in the pipeline, and the Gitea hook is the final gate.
