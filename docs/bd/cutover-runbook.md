# BD cut-over copy: how to run it

> #812 builds and tests the command; it is **not run against any real database in that ticket**.
> It runs for real only in the rehearsal (#813) and on cut-over day (#814), and a rollback only
> through day 7 (#802 Q38), each on Hanz's go. Everything in angle brackets is a placeholder: the
> real names live in the agent memory and the ops notes, never in this public repo.

The command is `python -m bd.ops.cutover` (`backend/bd/ops/cutover.py`; its docstring is the full
rule book). It copies BD's data from the **old BD database** into **schema `bd`** of the tool's
database and proves the copy: per-table row counts and checksums on both sides, the source unchanged
from start to end (the freeze proof), and every id sequence past its highest id. It also copies back
for a rollback. CI runs it both ways on every PR (`backend/tests/test_bd_cutover_*.py`), against a
source built from BD's original four migrations.

| Subcommand | What it does | Writes |
|---|---|---|
| `check` | The forward preflight, then the old database's per-table counts and checksums, and the size of any `bd_carry` | Nothing |
| `forward --record <record-file>` | The preflight, the copy in one transaction, `bd_carry` put back if a rollback saved one, the proof, the cut-over record, then the one-time list of likely duplicate BD accounts | Schema `bd` and the record file only |
| `reverse --record <record-file>` | A rollback: the reverse preflight (the old database must still match the record), schema `bd` copied back into the old database's tables in one transaction, the proof, the sequences, and `bd_carry` saved | The old database only (its BD tables and `bd_carry`); schema `bd` is only read |

Every run is all or nothing: a refusal writes nothing, and a failed proof or a broken freeze rolls
back everything that run wrote, the id sequences it had already set included. The one exception is
exit 6 (below): the connection dropped during the forward copy's commit, so whether it landed is
unknown.

## The two databases

They come from the environment, never the command line, and the command never prints them:

| Variable | Value |
|---|---|
| `BD_CUTOVER_OLD_URL` | The old BD database as its **owner login**, by its service name on the old BD network: `postgresql://<old-db-owner>:<old-db-password>@<old-db-service>:5432/<old-db-name>`. `check` and `forward` only read it (their sessions on it are read only); only `reverse` writes there. The owner is the database container's superuser, which can see every other session; a login that cannot is refused. |
| `BD_CUTOVER_TOOL_URL` | The tool's database as **`bd_app`**: the same value as `BD_DATABASE_URL` in the tool's env file (the session pooler on prod). The command refuses a login that can change schema `bd`. `reverse` only reads it. |

`bd_app` already holds what the copy needs (#813 sets it up): it may read and write schema `bd`'s
tables and use and set their sequences, and nothing else. The copy needs no admin login on the
tool side.

## Where it runs

The old database publishes no port, so the command runs in a **one-off container from the tool's
image that joins the old BD network**. The tool's image already holds the command and its driver.
Nothing is installed on the server and nothing stays behind (`--rm`). The container needs the old
database by its service name on that network and the tool's database the way the tool's own
container reaches it.

1. Make a fresh temporary folder, root only: `<tmp-dir>`. Put the two variables in
   `<tmp-dir>/cutover.env` (mode 600), and make `<tmp-dir>/records/` for the record.
2. Every run has this shape (`<subcommand>` is one of the three above):

   ```sh
   docker run --rm --network <old-bd-network> --env-file <tmp-dir>/cutover.env \
     -v <tmp-dir>/records:/records \
     <tool-image> python -m bd.ops.cutover <subcommand>
   ```

3. Delete `cutover.env` as soon as the day's runs are over. Keep `records/` (below).

## The cut-over record

`forward --record /records/<record-file>.json` writes it, as a **new** file, only when the copy's
proof holds and just before it commits. It is a small JSON file:

```json
{
  "record": "bd cut-over",
  "direction": "forward",
  "at": "<UTC time of the copy>",
  "checksum": "<the checksum form's name>",
  "tables": {"contacts": {"count": 0, "checksum": "<32 hex digits>"}, "...": {}}
}
```

One entry per old BD table: the old database's row count and checksum at the moment of the copy.
No row data, no connection string. It is the only proof of what the old database held at cut-over,
and the reverse copy cannot run without it:

- Keep it root only (mode 600) on the server next to the encrypted cut-over dump, with a copy in
  the private Dropbox folder. Do not paste it into a GitHub issue or PR: the repo is public.
- Never edit it. The reverse copy refuses a record that is not a forward copy's, or that was made
  with another checksum form.
- A later re-cut-over writes a **new** record file; the command never overwrites one.
- It is deleted with the cut-over dump on day 30 (#815).

## Cut-over day: the order (#814)

#814 holds the full list. The copy's part, in order:

1. **Before the freeze**, run `check`. With the old app still running it exits 3 with one line,
   "other clients are connected to the old database". That is expected at this point. Every other
   refusal line is a real problem: stop and fix it before the freeze. Its counts and checksums are
   the old database as of now.
2. **Freeze** (#814 step 3): stop the old app container, its weekly batch off, its containers set
   not to restart. Leave the old database container running.
3. Take and encrypt the full dump (#814 step 4). Wait until it has finished: a `pg_dump` still
   running counts as another client. So does a scheduled backup job, so do not start the copy while
   one runs.
4. Run `check` again. It must exit 0.
5. Run `forward --record /records/<record-file>.json`. Exit 0 means every table matches, the
   freeze held, the sequences are set, the record is written and the copy is committed. It then
   prints the list of likely duplicate BD accounts (account ids, names and hints only): keep it for
   Hanz in the private ops notes, not in a GitHub issue (the repo is public, and these are
   customers' names). Nothing is merged: an assistant or BD admin merges a pair, or keeps it
   separate, in the BD CRM itself (#811).
6. Exit 6: the connection dropped during the commit, so it is unknown whether schema `bd` holds the
   copy. The record is kept. Do not restart the old app yet. Run `check`: if it refuses with
   `bd.<table> holds rows`, the copy landed, the record proves it, and the cut-over goes on (the
   likely duplicate pairs show under Possible duplicates on the BD Contacts page instead of the
   printed list). If schema `bd` is still empty, nothing was kept: move the record aside (it proves
   nothing) and treat it like the next point.
7. Any other exit code: nothing was kept in schema `bd`. Stop the cut-over and restart the old app
   (#814). Do not run `forward` again without finding the cause.
8. Keep the record file as above, then go on with #814 (read-only checks, the switch, the CSP
   check, the redirect).

## Rollback: the reverse copy (through day 7, on Hanz's go)

The order is #802's rollback (Q38):

1. In the tool's env file, turn `BD_ENABLED` and `BD_WEEKLY_ENABLED` off, then recreate the tool
   container so it reads them (the BD settings are read once, at start). From here nobody can write
   to schema `bd`.
2. Start the old database container only, not the old app.
3. Run `reverse --record /records/<record-file>.json` with the record the cut-over wrote.
   - It refuses (exit 3) unless the old database still matches the record, table by table, and names
     each table that differs. That means something wrote to the old database after the cut-over:
     stop and find out what before going on.
   - Then, in one transaction on the old database, it locks the old BD tables, replaces every old BD
     table's rows with schema `bd`'s (the columns the old app has), proves the counts and checksums
     match, sets every id sequence past its highest id and past the tool's own, and saves the BD-only
     state in the side schema `bd_carry`: merge marks of merged-away accounts, the people at them, and
     kept pairs. The old app never reads `bd_carry`.
   - Exit 0 prints "bd_carry saved" with the number of merge marks and kept pairs.
4. Restore the nginx backup for `<bd-host>`.
5. Start the old app with its weekly batch off, check it, then turn its batch back on.

During the rollback a merged-away account shows in the old app as an empty account. Keep the record
file: a re-cut-over needs a new one, but the old one stays the proof of the first cut-over.

## A later re-cut-over

On Hanz's go:

1. The freeze, as on cut-over day (the old app stopped, its database running, the dump).
2. The admin login empties schema `bd`'s tables. The migrations ledger stays.
3. `check`: exit 0, and it reports the `bd_carry` the rollback saved.
4. `forward` with a **new** record file. Once the rows are in it puts `bd_carry` back, each merge
   mark and kept pair as it was, and prints how many. A merged-away account that gained people in the
   old app during the rollback gets no mark back (marking it would hide them), and neither does one
   the old app deleted. Each is listed by account id and name for Hanz, with any kept pair whose
   account is gone. Hanz decides whether to merge them again. Their old merges drop off the Contacts
   page's Recently merged list, since there is no mark left for Undo to take back.

## What each refusal means

Each refusal is one plain line on stderr beginning `refusing:`, every problem is listed at once,
and the exit code is 3. Nothing was written anywhere.

| The line says | What it means | What to do |
|---|---|---|
| `set BD_CUTOVER_OLD_URL ... in the environment` (exit 2) | A variable is missing | Fix `cutover.env` |
| `the old login cannot see other sessions` | `BD_CUTOVER_OLD_URL` is a login that is neither a superuser nor in `pg_read_all_stats`, so Postgres hides the other sessions from it and the old app could still be connected unseen | Use the old database's owner login |
| `N other clients are connected to the old database` | Something still holds a session on the old database: the old app, a backup, a `psql` left open. A client that has only just disconnected is still listed for a moment, so the command waits up to 5 seconds for such sessions to leave before it refuses; this line means they were still connected after that | Stop it, then run again. Before the freeze this is expected |
| `the old database has no migrations ledger` / `... ledger is not BD's original four` | The old database is not BD's, or BD gained a migration the command does not know | Check `BD_CUTOVER_OLD_URL`. A newer BD migration needs a code change to the command's map first |
| `the old database has no table ...` / `... has a table (or column) the map does not know` / `... is not what the map says` | The old database's shape is not BD's four migrations | As above |
| `schema bd has no table ...` / `schema bd: bd.<table> has a column the map does not know ...`, and the like | Schema `bd` is not the shape the command's map expects | A BD migration after 005 changes the map: the command and its tests must be updated in the same PR, and CI's cut-over tests fail until they are |
| `the tool's database has no schema bd` | The runner never ran there | Run the runner (#813) |
| `schema bd is not migrated up to date (pending: ...)` | The tool's database is behind the code | Run the runner, on Hanz's go |
| `the tool side must connect as bd_app` | `BD_CUTOVER_TOOL_URL` is the admin or another login that can change schema `bd` | Use the `bd_app` value from the tool's env file |
| `bd.<table> holds rows` (forward) | Schema `bd` is not empty: a copy already ran, or test rows are there. The ledger and the settings row a migration inserts do not count | Never empty it on cut-over day without Hanz. On a re-cut-over the admin login empties it |
| `the cut-over record <file> already exists` (forward) | The file name is taken | Give a new file name. Never delete the old record |
| `the old database's bd_carry ...` | A `bd_carry` schema is there but is not the shape the reverse copy makes | Someone changed it by hand. Stop and ask Hanz |
| `the cut-over record <file> does not exist` / `is not a cut-over record from a forward copy` / `was made with another checksum form` (reverse) | The wrong file, an edited one, or one from another version of the command | Find the record the cut-over wrote |
| `schema bd holds no BD rows` (reverse) | The copy would empty the old database | Check `BD_CUTOVER_TOOL_URL` points at prod's tool database |
| `the old database no longer matches the cut-over record: <table> (...)` (reverse) | Something wrote to the old database after the cut-over | Stop. Find the writer before anything else |

If the old app holds a lock on its tables, the reverse copy waits up to 10 seconds for it, then
stops with an error and keeps nothing.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Done: every table matches, the freeze held, the sequences are set | Go on |
| 1 | An error: it could not connect, the record could not be written, a lock wait ran out, or a database error (its class and SQLSTATE and the table are named, never its message, which can quote a row) | Nothing was kept; stop and look |
| 2 | A variable is missing, or the command line is wrong | Fix it and run again |
| 3 | Refused by the preflight (above) | Fix what it names; nothing was written |
| 4 | The proof did not match: a table's count or checksum, a sequence, or the `bd_carry` read back | Nothing was kept. On cut-over day: stop and restart the old app |
| 5 | The freeze did not hold: the source changed during the copy (forward: the old database; reverse: schema `bd`) | Nothing was kept; find the writer, then run again |
| 6 | Forward only: the connection dropped during the commit, so whether schema `bd` holds the copy is unknown. The record is kept | Run `check` before anything else (cut-over day, step 6) |

The freeze is proven up to the proof. Between the source's second reading and the commit, the
command only sets the sequences, reads the duplicates list and writes the record, a moment in which
the freeze itself (the old app stopped, no other client) is what keeps the old database still.

## What it prints

Table names, row counts, checksums, account ids and names in the duplicates list with the kind of
hint (phone, email domain), the number of merge marks and kept pairs in `bd_carry`, the account ids
and names of merged-away accounts whose mark was not put back, and plain error lines. Never a
person's name, phone, email, note or any other row data, and never a connection string.
