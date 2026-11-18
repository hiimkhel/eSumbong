# Sumbong Database (SQLite: sumbong.db)

Only store.py runs SQL. status.py may read the database read-only. Timestamps are REAL seconds from time.time(). Delete sumbong.db with the broker stopped to reset; tables are recreated on start.

## reports

| Column | Type | Notes |
| --- | --- | --- |
| report_id | TEXT | primary key (8-char uuid) |
| topic | TEXT | |
| barangay | TEXT | |
| priority | TEXT | URGENT/NORMAL |
| description | TEXT | |
| reporter_id | TEXT | never sent to subscribers if anonymous |
| anonymous | INTEGER | 0/1 |
| status | TEXT | RECEIVED/RESPONDING/RESOLVED/WITHDRAWN |
| assigned_to | TEXT | first responder to send RESPONDING |
| escalated | INTEGER | 0/1 |
| created_at | REAL | |

## messages

| Column | Type | Notes |
| --- | --- | --- |
| msg_id | TEXT | primary key |
| report_id | TEXT | |
| topic | TEXT | |
| priority | TEXT | |
| body | TEXT | JSON |
| created_at | REAL | |

## subscriptions

| Column | Type | Notes |
| --- | --- | --- |
| client_id | TEXT | |
| pattern | TEXT | |

UNIQUE (client_id, pattern)

## deliveries

| Column | Type | Notes |
| --- | --- | --- |
| msg_id | TEXT | |
| client_id | TEXT | |
| status | TEXT | PENDING/DELIVERED |
| attempts | INTEGER | default 0 |
| last_sent_at | REAL | null until first send |

PRIMARY KEY (msg_id, client_id)

## status_log

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER | primary key autoincrement |
| report_id | TEXT | |
| status | TEXT | RESPONDING/RESOLVED/WITHDRAWN, or ESCALATED for an escalation |
| responder_id | TEXT | null for an escalation |
| note | TEXT | |
| time | REAL | |

## users

Responder and city desk accounts (auth.py, managed with users.py). Residents have none.

| Column | Type | Notes |
| --- | --- | --- |
| client_id | TEXT | primary key; the desk is config.DESK_ID (`city`) |
| role | TEXT | responder/desk |
| barangay | TEXT | null: all of Jaro; otherwise the one barangay this responder may cover |
| secret_hash | TEXT | `pbkdf2_sha256$<iterations>$<salt>$<hash>`; the PIN or password itself is never stored |
| created_at | REAL | |

## Recommended indexes

- `deliveries(client_id, status)`
- `reports(status, escalated)`
