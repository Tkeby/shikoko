"""Demo FastAPI app using pysquirrel-generated query functions."""

from __future__ import annotations

import os

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, status

# Import the generated query functions.
# Run `pysquirrel generate` to create this module first.
from sql_generated import (
    CreateUserRow,
    FindUserByEmailRow,
    ListPostsByUserRow,
    ListUsersRow,
    create_user,
    delete_user,
    find_user_by_email,
    list_posts_by_user,
    list_users,
)

app = FastAPI(title="pysquirrel Demo", version="0.1.0")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://squirrel:squirrel@localhost:54323/squirrel",
)

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


@app.on_event("shutdown")
async def shutdown() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/users", response_model=list[ListUsersRow])
async def get_users() -> list[ListUsersRow]:
    """List all users with their org name."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await list_users(conn)


@app.get("/users/{email}", response_model=FindUserByEmailRow)
async def get_user(email: str) -> FindUserByEmailRow:
    """Find a single user by email."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await find_user_by_email(conn, email)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        return row


@app.post("/users", response_model=CreateUserRow, status_code=status.HTTP_201_CREATED)
async def post_user(
    email: str, name: str | None = None, org_id: int | None = None
) -> CreateUserRow:
    """Create a new user and return the generated row."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await create_user(conn, email, name, org_id)
        if row is None:
            raise HTTPException(status_code=500, detail="Failed to create user")
        return row


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(user_id: int) -> None:
    """Delete a user by id."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await delete_user(conn, user_id)


@app.get("/users/{user_id}/posts", response_model=list[ListPostsByUserRow])
async def get_user_posts(user_id: int) -> list[ListPostsByUserRow]:
    """List all posts by a given user."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await list_posts_by_user(conn, user_id)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("select 1")
    return {"status": "ok" if val == 1 else "error"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
