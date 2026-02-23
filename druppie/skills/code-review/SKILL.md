---
name: code-review
description: Reviews code for quality, security, and best practices
allowed-tools:
  coding:
    - read_file
    - list_dir
  bestand-zoeker:
    - read_file
    - search_files
    - list_directory
---
# Code Review Instructions

You are performing a code review. Follow these steps carefully:

## 1. Understand the Context
- Read the files to be reviewed
- Understand the purpose of the code
- Check if there are existing tests or documentation

## 2. Check for Security Issues
- Look for hardcoded secrets or credentials
- Check for SQL injection vulnerabilities
- Verify input validation and sanitization
- Look for XSS vulnerabilities in web code
- Check for insecure deserialization
- Verify proper authentication and authorization

## 3. Check for Code Quality
- Verify proper error handling
- Check for code duplication
- Look for overly complex functions (high cyclomatic complexity)
- Verify naming conventions are followed
- Check for proper logging
- Verify edge cases are handled

## 4. Check for Best Practices
- Verify SOLID principles are followed where applicable
- Check for proper dependency injection
- Look for magic numbers or strings
- Verify proper use of async/await
- Check for proper resource cleanup

## 5. Provide Actionable Feedback
For each issue found, provide:
- The file and line number
- A clear description of the issue
- The severity (critical, major, minor, suggestion)
- A suggested fix or improvement

## Output Format
Structure your review as:
```
## Summary
[Brief overview of the review]

## Critical Issues
[List of critical issues that must be fixed]

## Major Issues
[List of major issues that should be fixed]

## Minor Issues
[List of minor issues and suggestions]

## Positive Observations
[What was done well]
```
