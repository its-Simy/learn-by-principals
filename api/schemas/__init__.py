"""Pydantic models for the API, one module per router.

Core stays dataclasses; each model's ``from_core`` is the only glue, and FastAPI needs pydantic to
publish the OpenAPI document the web app's TypeScript types are generated from.
"""
