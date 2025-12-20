# Runtime Overview

De **Runtime** is de operationele omgeving waarin de applicaties en agents van Druppie draaien. Het is gebaseerd op cloud-native principes en Kubernetes.

Dit overzicht beschrijft de infrastructuur- en integratiecomponenten.

## 🏗️ Core Infrastructure

- **[Kubernetes Runtime](./runtime.md)**
  - Beschrijft de conceptuele architectuur van de Kubernetes runtime: Nodes, Pods, Services, en Control Loops.
  - Legt uit hoe Scaling, Failover en Self-healing werken.

- **[Dynamic Slot](./dynamic_slot.md)**
  - Het mechanisme waarmee de `Builder Agent` dynamisch nieuwe workloads kan deployen in gereserveerde namespaces.

## 🔐 Security & Access

- **[RBAC (Role Based Access Control)](./rbac.md)**
  - Definieert hoe rechten worden beheerd binnen de runtime en API's.
  - Koppeling tussen identiteiten, rollen en permissies.

## 🔌 Integration & Protocols

- **[MCP Interface](./mcp_interface.md)**
  - Beschrijft het **Model Context Protocol** (MCP), de standaard waarmee AI-agents praten met tools en externe systemen.
  
- **[Git Operations](./git.md)**
  - Hoe de runtime integreert met versiebeheer voor GitOps-style deployments en source code retrieval.
