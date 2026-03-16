---
name: git-workflow
description: Guides proper git workflow and branching strategies
allowed-tools:
  coding:
    - run_git
    - create_pull_request
    - merge_pull_request
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
1. Create feature branch: `run_git(command="checkout -b feature/<name>")`
2. Make changes and commit frequently with clear messages:
   - Stage changes: `run_git(command="add .")`
   - Commit: `run_git(command="commit -m 'feat: description'")`
3. Push branch to remote: `run_git(command="push -u origin feature/<name>")`
4. Create pull request for review
5. After approval, merge via pull request

### For Bug Fixes
1. Create fix branch: `run_git(command="checkout -b fix/<name>")`
2. Write a test that reproduces the bug
3. Fix the bug
4. Verify all tests pass
5. Commit and push: `run_git(command="add .")`, `run_git(command="commit -m 'fix: description'")`, `run_git(command="push")`
6. Create pull request
7. After approval, merge via pull request

### For Hotfixes (Production Issues)
1. Create hotfix branch: `run_git(command="checkout -b hotfix/<name>")`
2. Make minimal changes to fix the issue
3. Commit and push: `run_git(command="add .")`, `run_git(command="commit -m 'hotfix: description'")`, `run_git(command="push")`
4. Create pull request with high priority
5. Fast-track review and merge via pull request
6. Deploy immediately

## Pull Request Guidelines
- Keep PRs small and focused (ideally < 400 lines)
- Include a clear description of changes
- Reference related issues
- Ensure all tests pass
- Request review from appropriate team members

## Merge Strategy
- Merging is done through pull requests only (create_pull_request + merge_pull_request)
- Use squash merge for feature branches (clean history)
- Use regular merge for release branches (preserve history)
- Always delete branches after merging
