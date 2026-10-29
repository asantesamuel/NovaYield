# Backend Contracts and Module Ownership

This document records the initial backend boundaries and integration contracts for NY-1. It is a working engineering contract for the MVP; it does not replace the PRD or decide unresolved agronomic questions. The PRD and the approved authentication scope change remain authoritative.

## Contract status

- FastAPI serves a versioned JSON API under `/api/v1`.
- API request and response bodies are validated with Pydantic schemas. MongoDB documents are persistence models and are not returned directly from routes.
- Successful endpoints return their documented response DTO directly. Errors use FastAPI's JSON `detail` response, with a consistent status code and no stack traces or secrets exposed to clients.
- MongoDB document identifiers are represented as strings at the API boundary. Internal repositories may use native MongoDB identifiers.
- User-owned resources carry an `owner_user_id` reference. Every read or write of a farm or farm-specific decision result must authorize against the authenticated user; a client-supplied resource ID is never sufficient authorization.
- NASA observations are identified by their provider and query dimensions (area, date interval, and requested variables). The persistence design must allow observations to be reused by later analysis and decision runs rather than fetched again for every request. Whether a snapshot is shared or farm-scoped is an implementation detail to settle with NY-4/NY-6; it is not a user-owned resource by default.
- Authentication is an approved addition to MVP scope. Registration uses email and password; stored passwords are one-way hashes. Protected endpoints use a standard, expiring authenticated session/token mechanism. NY-5 owns the detailed token/session lifecycle and security implementation.

## Domain and API contracts

The following fields establish the integration boundary. They are not a mandate to invent agronomic inputs, decision thresholds, or scoring weights. Research outputs from NY-13 through NY-17 must settle those values before decision logic is implemented.

| Concept | API / service shape | Persistence boundary |
| --- | --- | --- |
| User | Registration and login accept JSON with email and password; login returns the agreed cookie-session response; a current-user endpoint returns only safe account fields. Passwords are never returned. | User document contains a normalized email with a uniqueness constraint, password hash, and timestamps. |
| Farm | A farm has a name, location, and the field information supported by the PRD (for example soil texture, irrigation access, previous crops, and farmer priorities). Farm create/read/update operations are scoped to the authenticated owner. | Farm document includes `owner_user_id`; farm identifiers are referenced by results. Field names and requiredness are validated against the final API schema and research findings. |
| Environmental snapshot | A normalized snapshot records the source, queried area, interval, requested variables, retrieval time, and available environmental values. Provider metadata and the original response may be retained where useful for provenance. | Snapshot records have a stable query identity and retrieval/refresh metadata so equivalent stored data can be reused. Retention, freshness windows, and refresh policy are NY-6 decisions. |
| Rotation result | A result identifies its farm, generation time, decision-engine version, input snapshot references, and the candidate rotation options with their explanations, comparisons, assumptions, and risks. It is a decision-support output, not a yield forecast or guaranteed advice. | Result document references the farm and authenticated owner and preserves enough input/provenance information to explain the result later. Reads are authorized through the owning farm/user relationship. |

The PRD workflow describes comparing three candidate rotations across three consecutive planting seasons and including a baseline when current practice is known. The result schema must support that workflow without fixing crop-specific rules or scores before the research tickets are complete.

### Initial route ownership

These paths are the proposed boundary for later feature tickets; NY-3 only establishes the application and router-registration hook.

| Route group | Initial route boundary | Owning module |
| --- | --- | --- |
| Authentication | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me` | `api/v1/auth` + `services/auth` |
| Farms | `POST /api/v1/farms`, `GET /api/v1/farms`, `GET /api/v1/farms/{farm_id}`, `PATCH /api/v1/farms/{farm_id}` | `api/v1/farms` + `services/farms` |
| Environmental data | Farm-scoped request/retrieval boundary to be confirmed after NASA variable and freshness research | `api/v1/environmental_data` + `integrations/nasa` + `services/environmental_data` |
| Decision support | Create and retrieve farm-specific rotation results after NY-13–NY-17 provide actionable decision requirements | `api/v1/decisions` + `services/decisions` |

Route names can be adjusted in the feature tickets before those APIs are implemented, provided the frontend and backend agree on the request/response schemas and authorization behavior first.

## Module ownership and integration boundaries

| Backend area | Ownership boundary |
| --- | --- |
| `app/api/` | HTTP routing, request/response schema binding, status codes, and dependency wiring. Routes remain thin and do not contain decision rules or MongoDB query logic. |
| `app/schemas/` | Public Pydantic request/response DTOs and validation. Feature owners coordinate changes to shared DTOs before editing them. |
| `app/models/` | MongoDB document shapes and serialization helpers; distinct from API DTOs. |
| `app/repositories/` | MongoDB reads/writes, indexes, and ownership-filtered queries. Repositories do not make external NASA calls or decide recommendations. |
| `app/services/` | Feature use cases: authentication, farm operations, environmental-data orchestration, and decision-result orchestration. Services use repositories and integrations through explicit interfaces. |
| `app/integrations/nasa/` | NASA client, provider-specific request/response handling, timeouts, and provider errors. It does not own application persistence. |
| `app/core/` | Shared settings, application lifecycle, security primitives, and cross-cutting error/readiness behavior. Changes here need coordination because all feature areas depend on it. |
| `tests/` | Unit tests next to the corresponding feature through clear test modules, plus API/integration tests for cross-module behavior. Tests must not require live NASA calls. |

Feature ownership should follow these boundaries: auth owns auth routes, schemas, service, and user repository; farms owns farm routes, schemas, service, and farm repository; external-data owns the NASA integration and snapshot lifecycle; decisions owns recommendation orchestration and result persistence. Each feature can be developed in parallel once NY-1 contracts and its prerequisite interfaces are agreed. Shared `core`, router registration, base document helpers, and common schemas require one agreed owner or a small coordinated change.

## Dependency and integration notes

- NY-1 is the contract prerequisite for feature implementation, not a runtime parent module.
- NY-3 provides the FastAPI factory, configuration, CORS, health/readiness, and router-registration point. Feature routes integrate through that registration point.
- MongoDB repository and document conventions must be agreed before auth, farms, snapshots, and result persistence are merged. Farm and result queries must include the authenticated owner in their filter.
- NASA API retrieval and snapshot persistence are separate responsibilities: the provider integration fetches data; the environmental-data service/repository identifies, reuses, and refreshes stored snapshots.
- Decision logic depends on the relevant research outputs from NY-13–NY-17 and on persisted farm/environmental inputs. It must not fetch NASA data itself or invent unresolved agronomic rules.
- The frontend consumes the API through versioned request/response DTOs. Changes to shared paths or DTOs require coordination with the frontend owner.

## Decisions still requiring validation

- Pilot geography, crop library, crop calendar, agronomic constraints, comparison criteria, and any scoring or ranking rules: research tickets NY-13–NY-17 and domain-expert validation.
- Exact NASA variables, spatial granularity, query identity, freshness window, and snapshot retention: data-source research and NY-6 implementation planning.
- Final auth token/session mechanism, secret handling, expiration and renewal policy, and password-hashing parameters: NY-5. The implementation must use established libraries and practices.
- Final MongoDB collection/index details and whether environmental snapshots are shared across farms: NY-4/NY-6, preserving the ownership rules above.
- Exact farm field requiredness and result DTO fields: confirm against the PRD and research findings before feature implementation.
