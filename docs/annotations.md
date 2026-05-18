# Annotations

shikoko supports a small set of annotations in SQL files that control
how the generated Python code behaves.

See also: [Type mapping](type-mapping.md) | [Usage guide](usage.md) | [Troubleshooting](troubleshooting.md)

## Nullability overrides (`!` and `?`)

By default, shikoko infers nullability from three sources in priority
order: (1) explicit overrides via column aliases, (2) the Postgres
`EXPLAIN` plan for outer-join nullability, and (3) the
`pg_attribute.attnotnull` catalog. When you need to override the
inferred decision, append a marker to the column alias in your `SELECT`
list.

### `!` — force non-null

Appending `!` to a column alias tells shikoko to emit it as a
non-nullable Python field, regardless of what the plan or catalog says.
This is useful when you know a left-join column is always populated
(e.g. a foreign key that is guaranteed to be satisfied in your domain).

**Example:**

```sql
-- name: get_orders
select
    o.id,
    u.email!   -- override: we know every order has a user
from orders o
left join users u on u.id = o.user_id;
```

Generated field:

```python
class GetOrdersRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

    id: int
    email: str
```

Without the `!`, `email` would be `email: str | None = None` because
the left join makes the plan walker consider it nullable.

### `?` — force nullable

Appending `?` to a column alias forces the field to be nullable, even
when the catalog reports a `NOT NULL` constraint. This is useful for
computed columns or expressions where Postgres reports the constraint
but the value can still be null at runtime (e.g. a `COALESCE` that
might not cover every case, or a view column backed by a function).

**Example:**

```sql
-- name: list_users
select
    id,
    display_name,
    avatar_url?   -- override: might be null despite catalog
from users;
```

Generated field:

```python
class ListUsersRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

    id: int
    display_name: str
    avatar_url: str | None = None
```

### Notes

- Exactly one trailing character is stripped: `foo!!` becomes the alias
  `foo!` with a non-null override. The remaining `!` will then fail
  Python identifier validation downstream — that's intentional.
- Overrides take the **highest priority** in the nullability pipeline.
  They win over both the plan walker and the catalog.
- The cleaned alias (marker stripped) is used as the Python field name.
