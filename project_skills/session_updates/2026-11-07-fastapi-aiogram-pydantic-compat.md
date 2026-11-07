# Pending Skill Proposal: FastAPI / aiogram / Pydantic Version Compatibility

Status: pending

## What Changed

The project pins `aiogram==3.4.1`, whose package metadata requires `pydantic>=2.4.1,<2.6`. The unconstrained FastAPI requirement had allowed FastAPI 0.125.0 to be installed alongside Pydantic 2.5.3. App creation then emitted 405 `PydanticDeprecatedSince20` warnings because this FastAPI line passes `deprecated=` into Pydantic `Field`, a parameter supported starting with Pydantic 2.7.

Pinned FastAPI to `>=0.110.1,<0.110.2`, the last compatible line before FastAPI 0.110.2 added support for Pydantic 2.7's deprecated Field parameter. The resolved set is FastAPI 0.110.1, Starlette 0.37.2, Pydantic 2.5.3, aiogram 3.4.1. `pip check` reports no broken requirements.

## Verification

- Isolated compatibility install: app creation emitted 0 Pydantic deprecation warnings.
- Full suite under the compatible package set: 946 passed.
- After applying the same FastAPI/Starlette versions to `.venv`: health/CORS tests 6 passed; `pip check` clean.

## Why It Is Reusable

This is a concrete example of transitive dependency constraints interacting across framework and bot libraries. Future dependency updates should inspect package metadata, test a compatible resolution in isolation, and run the suite before changing the working environment.

## Candidate Skill

- ID: `python-framework-dependency-compatibility`
- Category: `testing` or `deploy`
- Source paths: `requirements.txt`, `.venv` package metadata, `tests/test_web_health.py`
- Dependencies: none
- Maturity: pending; gather another real dependency-conflict case before promoting to a full skill.
