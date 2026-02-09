---
name: git-workflow
description: Guides proper git workflow and branching strategies
---
# Git Workflow Instructions

You are guiding git workflow operations. Follow these best practices:

## Branch Naming Convention
- Features: `feature/<description>`
- Bug fixes: `fix/<description>`
- Hotfixes: `hotfix/<description>`
- Releases: `release/<version>`

Use lowercase with hyphens, e.g., `feature/add-user-authentication`

## Commit Message Format
Use conventional commits format:
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style (formatting, semicolons, etc.)
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Example: `feat(auth): add JWT token refresh endpoint`

## Workflow Steps

### For New Features
1. Create feature branch from main: `git checkout -b feature/<name>`
2. Make changes and commit frequently with clear messages
3. Push branch to remote: `git push -u origin feature/<name>`
4. Create pull request for review
5. After approval, merge to main
6. Delete feature branch

### For Bug Fixes
1. Create fix branch from main: `git checkout -b fix/<name>`
2. Write a test that reproduces the bug
3. Fix the bug
4. Verify all tests pass
5. Create pull request
6. After approval, merge to main

### For Hotfixes (Production Issues)
1. Create hotfix branch from main: `git checkout -b hotfix/<name>`
2. Make minimal changes to fix the issue
3. Create pull request with high priority
4. Fast-track review and merge
5. Deploy immediately

## Pull Request Guidelines
- Keep PRs small and focused (ideally < 400 lines)
- Include a clear description of changes
- Reference related issues
- Ensure all tests pass
- Request review from appropriate team members

## Merge Strategy
- Use squash merge for feature branches (clean history)
- Use regular merge for release branches (preserve history)
- Always delete branches after merging
