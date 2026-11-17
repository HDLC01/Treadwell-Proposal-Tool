---
status: accepted
---

# The Project Calendar reads Google as Hanz, and only the Treadwell Projects calendar

The Project Calendar reads the "Treadwell Projects" Google calendar through an OAuth sign-in as Hanz,
the calendar's owner, not through a service account. Treadwell's Google Workspace caps sharing with
accounts outside the company at free/busy, so a service account only ever saw untitled, uncoloured
blocks, and the Work type and Deadline both live in those titles and colours. A dedicated bot mailbox
would have worked inside that cap, but Hanz chose not to involve another account. Because Google
offers no OAuth permission limited to one calendar, the limit is enforced in the tool instead: the
narrowest read-only scope (`calendar.events.readonly`), only the one shared calendar id in
`PROJECT_CALENDAR_ID` is ever requested (never `primary`, an address, or a calendar list), and the
server refuses any id that is not a shared calendar's.

## Considered Options

- **Service account shared the calendar.** Rejected: the Workspace policy keeps it at free/busy.
- **A dedicated bot Workspace mailbox.** Workable and narrower, but costs a seat and another account.
- **The calendar's secret iCal link.** Rejected: iCal drops Google's colours, which carry the Work type.

## Consequences

- If Hanz's sign-in is revoked, his password changes, or he leaves, the page says the sign-in must be
  reconnected; whoever reconnects should be the calendar's owner.
- The stored refresh token could read Hanz's other calendars if it leaked, so it lives only in the
  server's environment file, never in git or chat.
