@prd docs/prds/005-dev-prod-infrastructure.md
@adr docs/adrs/005-dev-prod-infrastructure.md
Feature: Dev and Prod Infrastructure
  # Acceptance criteria for the dual-layer infrastructure.

  Scenario: Dev environment starts with docker compose profiles
    Given a developer has Docker installed and the repository checked out
    When the developer starts the stack with the dev and init compose profiles
    Then the full dev stack becomes ready within 60 seconds
    And Keycloak, Gitea, PostgreSQL, and MCP servers are reachable

  Scenario: Hot reload works for backend and frontend in dev profile
    Given the dev stack is running with the dev profile
    When a developer edits a backend Python file
    Then the backend reloads the changed module without a manual restart
    When a developer edits a frontend source file
    Then the browser reflects the change through Vite hot module replacement

  Scenario: Production cluster provisioned with hetzner-k3s
    Given a valid Hetzner Cloud token and iac/cluster.yaml
    When the operator provisions the cluster with the hetzner-k3s CLI
    Then 3 CPX32 master nodes form an etcd quorum
    And 1 CPX42 infra node is present
    And between 1 and 10 autoscaled CPX32 app nodes are present

  Scenario: Helm chart deploys all module services
    Given the production cluster is reachable and kubeconfig is configured
    When the operator renders the chart and applies it with kubectl
    Then every module service defined in the chart reports ready
    And CNPG, PgBouncer, KEDA, Traefik, and cert-manager resources are installed

  Scenario: Sandbox network isolation separates internal and internet traffic
    Given the sandbox infrastructure is running
    Then the sandbox-net network is internal with no internet egress
    And the sandbox-inet network is internet-enabled for agents that need egress
    And the sandbox-modules network is internal for MCP server traffic

  Scenario: CNPG database cluster provides PostgreSQL with automated failover
    Given a CNPG PostgreSQL cluster is deployed with replicas
    When the primary instance fails
    Then CNPG promotes a replica to primary automatically
    And client connections recover through PgBouncer without manual intervention

  Scenario: KEDA scales backend based on queue depth
    Given the backend is deployed with a KEDA ScaledObject watching queue depth
    When the pending work queue depth rises above the scale threshold
    Then KEDA increases the backend replica count up to the configured maximum
    When the queue depth falls back below the threshold
    Then KEDA scales the backend back down to the minimum replica count

  Scenario: ARC runners build and deploy images on push
    Given Actions Runner Controller is installed and runner pods are ready
    When a developer pushes a commit to the repository
    Then an ARC runner picks up the workflow job
    And the runner builds the container image and deploys it to the cluster

  Scenario: Traefik ingress terminates TLS with cert-manager
    Given Traefik ingress and cert-manager are deployed with a valid issuer
    When a request arrives at druppie.rijnland.dev over HTTPS
    Then Traefik terminates TLS using a cert-manager issued certificate
    And the request is routed to the appropriate backend service
