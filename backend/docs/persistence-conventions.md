# MongoDB Persistence Conventions (NY-4)

This document explains how the FastAPI app connects to MongoDB and how feature teams should add independently owned document models. It establishes shared conventions; it does not implement the User, Farm, RotationResult, or EnvironmentalSnapshot collections. Those remain owned by NY-11, NY-19, NY-20, and NY-6 respectively.

## What happens when the API starts

1. FastAPI enters its lifespan and creates one `MongoConnection` for that app process and event loop.
2. `MongoConnection` creates one `AsyncMongoClient`. A client is a connection-pool manager; it is reused for the app's lifetime rather than recreated per request or repository.
3. The app sends a small MongoDB `ping`. If it succeeds, the central registry imports feature model modules and Beanie initializes their collections and declared indexes once.
4. The readiness check sends a ping. If MongoDB was offline at startup, readiness retries the connection and Beanie initialization. The API process can stay alive while `/health/ready` returns HTTP 503.
5. FastAPI closes the shared client as the app shuts down.

Beanie's `init_beanie` creates collections when needed and creates indexes declared by the registered document models. Index dropping remains disabled; a schema/index change that needs data migration must be planned explicitly. See [Beanie's initialization guide](https://beanie-odm.dev/tutorial/initialization/).

`app.state.mongo` is the shared connection boundary. Feature routes should request `get_mongo_connection` or `get_mongo_database` from `app.database.dependencies`; they should not construct a new Mongo client. Beanie repositories can operate through their feature document classes after initialization.

## Configuration and secret handling

Settings use the existing `NOVAYIELD_` environment prefix:

| Variable | Purpose | Development default |
| --- | --- | --- |
| `NOVAYIELD_MONGODB_URI` | MongoDB connection URI | `mongodb://localhost:27017` |
| `NOVAYIELD_MONGODB_DATABASE_NAME` | Database selected by the app | `nova_yield` |
| `NOVAYIELD_MONGODB_SERVER_SELECTION_TIMEOUT_MS` | Maximum wait to find a server | `2000` |

Put local values in the ignored `backend/.env` file or inject them through the deployment environment. The URI uses Pydantic `SecretStr`, and the connection code never logs driver exception text because errors can include connection details. Readiness only reports `ok` or `unavailable`; it never returns the URI. Do not log passwords, complete URIs, raw NASA responses containing sensitive inputs, or precise farm coordinates.

## Registering a feature document

Each feature owns one or more modules under `app/models/` and registers its Beanie models with the decorator:

```python
from beanie import Document

from app.database.registry import register_document_model


@register_document_model
class Farm(Document):
    # Feature-owned fields and Settings go here.
    pass
```

The registry imports non-private modules under `app.models` before calling Beanie. Adding `app/models/farms.py` and registering its class is enough; feature teams do not edit the database bootstrap or a shared hand-maintained model list. Keep model-module imports declarative and avoid network calls or other startup side effects.

The central database task owns connection/configuration/registry code. Each domain owner defines its model fields, collection name, repository, and collection-specific indexes in its own module. This limits shared-file conflicts and leaves the model owner responsible for the meaning of its data.

## IDs, references, ownership, and indexes

- Use MongoDB `ObjectId` values for document IDs and references. Convert IDs to strings only at the public API boundary; do not serialize Beanie documents directly as API responses.
- Store references such as `Farm.owner_user_id`, `RotationResult.owner_user_id`, and `RotationResult.farm_id` as ObjectId-valued fields. These are document references, not SQL foreign keys. NY-4 does not require Beanie `Link` fields or cross-collection joins.
- Authorization is enforced by application queries. Farm reads/updates include both the requested farm `_id` and authenticated `owner_user_id`. Result queries include the authenticated owner and the relevant farm reference, and verify that the farm belongs to that owner. Never authorize from a caller-supplied user ID alone.
- Normalize a user's email (trim and lowercase) before storing it; NY-11 defines the unique index on that normalized field.
- NY-19 defines an index on Farm `owner_user_id` for listing a user's farms.
- NY-20 defines a compound index beginning with `owner_user_id` and `farm_id` for farm-specific result retrieval (then a result timestamp if the query sorts by recency).
- NY-6 defines a unique index on a stable environmental request key so equivalent requests can reuse a stored snapshot. The key should be deterministic and opaque; its exact dimensions and refresh window belong to NY-6 research and implementation.

The feature-owned document classes declare these indexes in Beanie `Settings`. Beanie creates them during central initialization. The tests include a fake-backed initialization check and an opt-in MongoDB integration check that inspects a real unique index.

## Driver and auth integration note

This code uses Beanie's documented current Async PyMongo client (`pymongo.AsyncMongoClient`), which is native to `asyncio` and must stay within one event loop. MongoDB recommends it for asynchronous frameworks such as FastAPI; Motor is deprecated as of May 14, 2026. Sources: [Beanie initialization](https://beanie-odm.dev/tutorial/initialization/) and [MongoDB's PyMongo Async migration guide](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/).

The FastAPI Users Beanie tutorial still shows Motor, and its repository marks the adapter as maintenance mode. NY-11 should confirm the selected FastAPI Users Beanie adapter works with Beanie 2 and the current PyMongo async client, rather than copying the older Motor example verbatim. This is an integration verification item, not a change to the agreed Beanie persistence choice.
