# BD cut-over copy: how to run it

> #812 builds and tests the command; it is **not run against any real database in that ticket**.
> It runs for real only in the rehearsal (#813) and on cut-over day (#814), each on Hanz's go.
> Everything in angle brackets is a placeholder: the real names live in the agent memory and the
> ops notes, never in this public repo.

The command is `python -m bd.ops.cutover` (`backend/bd/ops/cutover.py`; its docstring is the full
rule book). It copies BD's data from the **old BD database** into **schema `bd`** of the tool's
database and proves the copy: per-table row counts and checksums on both sides, the old database
unchanged from start to end (the freeze proof), and every id sequence past its highest id.

| Subcommand | What it does | Writes |
|---|---|---|
| `check` | The preflight, then the old database's per-table counts and checksums | Nothing |
| `forward --record <record-file>` | The preflight, the copy in one transaction, the proof, the cut-over record, then the one-time list of likely duplicate BD accounts. After a rollback it also puts `bd_carry` back | Schema `bd` and the record file only |
| `reverse --record <record-file>` | A rollback: the reverse preflight (the old database must still match the record), schema `bd` copied back into the old database's tables in one transaction, the proof, the sequences, and `bd_carry` saved | The old database only (its BD tables and `bd_carry`); schema `bd` is only read |

## The two databases

They come from the environment, never the command line, and the command never prints them:

| Variable | Value |
|---|---|
| `BD_CUTOVER_OLD_URL` | The old BD database as its **owner login**, by its compose service name on the old BD network: `postgresql://<old-db-owner>:<old-db-password>@<old-db-service>:5432/<old-db-name>`. `check` and `forward` only read it (their sessions on it are read only); only `reverse` writes there. |
| `BD_CUTOVER_TOOL_URL` | The tool's database as **`bd_app`**: the same value as `BD_DATABASE_URL` in the tool's env file (the session pooler on prod). The command refuses a login that can change schema `bd`. `reverse` only reads it. |

## Where it runs

The old database publishes no port, so the command runs in a **one-off container from the tool's
image that joins the old BD network**. Nothing is installed on the server and nothing stays behind.

1. Put the two variables in a root-only file in a fresh temporary folder (mode 600), for example
   `<tmp-dir>/cutover.env`, with a folder for the record next to it, `<tmp-dir>/records/`.
2. Check first (writes nothing):

   ```sh
   docker run --rm --network <old-bd-network> --env-file <tmp-dir>/cutover.env \
     <tool-image> python -m bd.ops.cutover check
   ```

3. On cut-over day, after the freeze (the old app stopped, its database still running):

   ```sh
   docker run --rm --network <old-bd-network> --env-file <tmp-dir>/cutover.env \
     -v <tmp-dir>/records:/records \
     <tool-image> python -m bd.ops.cutover forward --record /records/<record-file>.json
   ```

4. Keep the record file (names, counts, checksums and the time only, no row data) with the cut-over
   ticket: the reverse copy needs it. Delete `cutover.env` as soon as the run is over.

## Rollback: the reverse copy (through day 7, on Hanz's go)

The order is #802's rollback (Q38): turn `BD_ENABLED` and `BD_WEEKLY_ENABLED` off in the tool first,
then start the old database container (not the old app), then:

```sh
docker run --rm --network <old-bd-network> --env-file <tmp-dir>/cutover.env   -v <tmp-dir>/records:/records   <tool-image> python -m bd.ops.cutover reverse --record /records/<record-file>.json
```

It refuses (exit 3) unless the old database still matches the cut-over record, table by table, and
names each table that differs: something wrote to the old database after the cut-over, so stop and
find out what. Then, in one transaction on the old database, it replaces every old BD table's rows
with schema `bd`'s (the columns the old app has), proves the counts and checksums match, sets every
id sequence past its highest id and past the tool's own, and saves the BD-only state in the side
schema `bd_carry` (merge marks of merged-away accounts, the people at them, and kept pairs). The
old app never reads `bd_carry`. During the rollback a merged-away account shows in the old app as
an empty account. Then restore the nginx backup and start the old app with its weekly batch off.

## A later re-cut-over

On Hanz's go: the admin login empties schema `bd`'s tables (the ledger stays), then `forward` runs as
on cut-over day with a **new** record file (an existing one is never overwritten). Once the rows are
in, it puts `bd_carry` back: each merge mark and kept pair as it was. A merged-away account that
gained people in the old app during the rollback gets no mark back (marking it would hide them),
and neither does one the old app deleted. Each is listed by account id and name for Hanz, with any
kept pair whose account is gone.

## What it refuses, before writing anything

Each refusal is one plain line, and the exit code is 3:

- schema `bd` holds rows (each table named). The ledger and a settings row a migration inserted by
  itself do not count;
- any other client is connected to the old database (stop the old app first);
- the old database's tables, columns or migrations ledger are not BD's original four migrations;
- schema `bd` is behind the code, or not the shape the command's map expects;
- the tool login can change schema `bd` (it must be `bd_app`);
- the record file already exists;
- a `bd_carry` in the old database that is not the shape the command makes.

The reverse copy refuses in the same way when: the record file is missing or is not a forward
copy's; another client is connected to the old database; either side is not BD's shape; the tool
login can change schema `bd`; schema `bd` holds no BD rows at all (the old database would be
emptied); or the old database no longer matches the record (each table named).

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Done: every table matches, the freeze held, the sequences are set | Go on with the cut-over |
| 1 | An error (the class and table are named, never the message, which can quote a row) | Nothing was kept; stop and look |
| 2 | A variable is missing | Set it and run again |
| 3 | Refused by the preflight | Fix what it names; nothing was written |
| 4 | The proof did not match | Nothing was kept; stop the cut-over, restart the old app |
| 5 | The freeze did not hold: the source changed during the copy (forward: the old database; reverse: schema `bd`) | Nothing was kept; find the writer, then run again |

## What it prints

Table names, row counts, checksums, account ids and names in the duplicates list with the kind of
hint (phone, email domain), the number of merge marks and kept pairs in `bd_carry`, the account ids
and names of merged-away accounts whose mark was not put back, and plain error lines. Never a person's name, phone, email, note or any
other row data, and never a connection string.
