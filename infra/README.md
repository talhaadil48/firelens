# Infrastructure readiness (later phases)

No resources have been provisioned or purchased. Phase 2 works without Azure.

- Azure region: **not selected or verified**. Phase 0.3 requires the owner to select
  a region with the chosen chat and embedding deployments available to the subscription.
- Azure subscription, offers, domain registration and team enrollment: not verified.
- Docker Desktop exists on the Windows host, but its WSL integration is not enabled
  in the execution environment. Dockerfiles are provided; local container builds
  cannot be claimed until Docker is available.
- Azure CLI is not available in this execution environment.
- Linux Git uses the existing Windows Git Credential Manager; credentials remain
  outside the repository. The repository-scoped Git identity uses the owner's config.

Phases 9–11 will add resources, deployment and DNS once the owner authorizes that work.
