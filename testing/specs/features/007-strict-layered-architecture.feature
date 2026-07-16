# @status active
# @superseded_by
# @adr 007-strict-layered-architecture.md
@adr docs/adrs/007-strict-layered-architecture.md
Feature: Strict layered architecture
  # The "why" (problem, goal, user journey) lives in the linked ADR (@adr).
  # This spec holds only the acceptance Scenarios below.

  Scenario: API route delegates to a service and returns a domain model
    Given a request to an API route in druppie/api/routes/
    When the route handles the request
    Then the route performs request validation and auth
    And the route delegates the work to a service
    And the route returns a Pydantic domain model
    But the route does not access the database directly

  Scenario: Service contains business logic and does not touch the database
    Given a service in druppie/services/
    When the service enforces a business rule
    Then the service orchestrates one or more repository calls
    But the service does not issue database queries itself
    And the service is not aware of HTTP request or response objects

  Scenario: Repository queries the ORM and returns a domain model
    Given a repository in druppie/repositories/
    When the repository reads or writes data
    Then the repository queries SQLAlchemy ORM models
    And the repository returns a Pydantic domain model
    But the repository does not call a service or a route

  Scenario: Domain models are exported through the central init module
    Given a new domain model is added under druppie/domain/
    When the model is needed outside its module
    Then the model is importable from druppie/domain/__init__.py
    And list endpoints use Summary models while single-item endpoints use Detail models

  Scenario: Layers are not skipped (unidirectional dependency)
    Given an API route that needs data
    When the route must obtain that data
    Then the route calls a service and not a repository directly
    And dependency flows only as Repository -> Domain Model -> Service -> API Route

  Scenario: No business logic in API routes
    Given a business rule that must be enforced
    When the rule is implemented
    Then the rule lives in a service rather than a route handler
    And the route handler only validates, authorizes, and delegates
