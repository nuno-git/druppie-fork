# Security Review

Review code for common security vulnerabilities before committing.

## When to use
After PHASE 3 (GREEN) and during PHASE 4 (REFACTOR), scan all new code for:

- Command injection (unsanitized shell exec)
- Path traversal (user input in file paths)
- SQL injection (string concatenation in queries)
- XSS (unescaped output in templates)
- Hardcoded secrets (API keys, passwords in source)
- Insecure dependencies (known CVEs)

## How to apply
1. Run a grep for common vulnerability patterns
2. Flag any issues found
3. Fix them before proceeding to PHASE 5
4. Add tests for the security fixes
