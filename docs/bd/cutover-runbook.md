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
| `forward --record <record-file>` | The preflight, the copy in one transaction, the proof, the cut-over record, then the one-time list of likely duplicate BD accounts | Schema `bd` and the record file only |

The reverse copy (rollback) and the `bd_carry` side schema are later parts of #812; this page
gains their steps when they land.

## The two databases

They come from the environment, never the command line, and the command never prints them:

| Variable | Value |
|---|---|
| `BD_CUTOVER_OLD_URL` | The old BD database as its **owner login**, by its compose service name on the old BD network: `postgresql://<old-db-owner>:<old-db-password>@<old-db-service>:5432/<old-db-name>`. The command only ever reads it: every session on it is read only. |
| `BD_CUTOVER_TOOL_URL` | The tool's database as **`bd_app`**: the same value as `BD_DATABASE_URL` in the tool's env file (the session pooler on prod). The command refuses a login that can change schema `bd`. |

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

## What it refuses, before writing anything

Each refusal is one plain line, and the exit code is 3:

- schema `bd` holds rows (each table named). The ledger and a settings row a migration inserted by
  itself do not count;
- any other client is connected to the old database (stop the old app first);
- the old database's tables, columns or migrations ledger are not BD's original four migrations;
- schema `bd` is behind the code, or not the shape the command's map expects;
- the tool login can change schema `bd` (it must be `bd_app`);
- the record file already exists.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Done: every table matches, the freeze held, the sequences are set | Go on with the cut-over |
| 1 | An error (the class and table are named, never the message, which can quote a row) | Nothing was kept; stop and look |
| 2 | A variable is missing | Set it and run again |
| 3 | Refused by the preflight | Fix what it names; nothing was written |
| 4 | The proof did not match | Nothing was kept; stop the cut-over, restart the old app |
| 5 | The freeze did not hold: the old database changed during the copy | Nothing was kept; find the writer, then run again |

## What it prints

Table names, row counts, checksums, account ids and names in the duplicates list with the kind of
hint (phone, email domain), and plain error lines. Never a person's name, phone, email, note or any
other row data, and never a connection string.
