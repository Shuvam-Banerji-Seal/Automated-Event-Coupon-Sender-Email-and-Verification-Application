# Event Coupon System

Issue a scannable entry pass to every guest, email it to them, and check them in
at the door from a phone.

Built for events at IISER Kolkata — a farewell for ~460 people, a freshers'
welcome for ~480 — where the practical problems are always the same ones:
the guest list arrives as somebody's spreadsheet with unpredictable columns, a
few hundred emails have to go out without tripping Gmail's limits, and on the
night a volunteer needs to know in under a second whether this person gets in
and whether they eat meat.

---

## What it does

**Reads your guest list as it actually is.** Upload the CSV and the system
proposes which column is the email, the name, the meal preference, and who gets
a pass, judging by both the column headings and the values inside them. You
confirm or correct the guesses. Columns it does not recognise are kept and
become variables you can use in the email, so a "Roll No" column nobody mapped
is still available as `{{ roll_no }}`.

**Lets you write the email in the browser.** A variable palette lists everything
available — system fields plus whatever your CSV contained — and clicking one
inserts it. Live preview at desktop and phone widths, for vegetarian and
non-vegetarian. A checker flags the things that break in real mail clients
before you send to three hundred people.

**Sends without falling over.** Several sending accounts with automatic
rotation when one hits its daily limit, one connection held open across the
whole run, live progress with a rate and an ETA, and a stop button. Re-running
a send never issues a second coupon to someone who already has one, so codes
already sitting in inboxes stay valid.

**Checks people in from a phone.** Full-screen camera, one-handed layout, and
the meal preference shown as the largest thing on the screen, because that is
what the volunteer acts on. A coupon can be redeemed exactly once — enforced by
the database, not by application logic — with an undo for mis-scans and typed
codes as a fallback when a camera will not cooperate.

---

## Getting started

```bash
git clone <this repo> && cd Automated-Event-Coupon-Sender-Email-and-Verification-Application
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('COUPON_SECRET_KEY=' + secrets.token_hex(32))"
# paste both into .env, then:

./start_server.sh
```

The console opens at `https://127.0.0.1:5000/` and the scanner at
`https://<your-lan-ip>:5000/scan`.

### Running an event

1. **Settings** — event name, date, time, venue, and at least one mail account.
   Gmail needs an [App Password](https://myaccount.google.com/apppasswords), not
   your normal password.
2. **Recipients** — upload the guest CSV, check the detected columns, import.
3. **Compose** — write the invitation, preview it, send yourself a test.
4. **Send** — pick the template and start. Watch it go.
5. **Scanner** — open the QR on the overview page from each volunteer's phone.

> **Try it with `MAIL_DRY_RUN=true` in `.env` first.** Everything works
> normally — coupons are issued, templates render, progress reports — but no
> message is delivered. Turn it off when you are ready for the real run.

---

## Deploying

`./start_server.sh` runs `serve.py`, which starts the app with the debugger and
the auto-reloader off.

**It must stay a single process.** Send-job progress, parsed uploads awaiting a
column mapping, the tunnel handle and the outbox worker all live in memory and
are shared across requests. Under `gunicorn -w 4` each worker would hold its
own copy: polling a send would hit a worker that never heard of it, and every
worker would run its own outbox. Use waitress (single process, thread pool) or
the built-in server — never a multi-worker one.

### As a service

A systemd user unit keeps it running across logout and restarts it on failure:

```bash
systemctl --user enable --now coupon-system
systemctl --user status coupon-system
journalctl --user -u coupon-system -f
```

### TLS, and why the server choice depends on it

Phone cameras need https, and there are two ways to get it:

| | server | local network | public |
|---|---|---|---|
| `SSL_ENABLED=true` (default) | built-in, threaded | https, self-signed warning | via the share |
| `SSL_ENABLED=false` | waitress | http, **no camera** | via the share |

The default keeps TLS on. waitress cannot terminate TLS, and without it a
venue with no internet leaves you with no camera at all — the built-in server
with debug off sustained ~350 scans/sec with ten concurrent scanners, which is
far past what a door produces. If you have a reverse proxy, run waitress behind
it and get both.

---

## Things worth knowing

### The scanner needs HTTPS

Browsers refuse camera access on a plain-http origin that is not `localhost`.
A phone opening `http://192.168.1.5:5000/scan` gets no camera, and no amount of
permission-granting changes that. `start_server.sh` generates a self-signed
certificate when `SSL_ENABLED=true`; each phone shows a warning once, which the
volunteer accepts, and the camera then works. The scanner detects the problem
and explains it rather than silently failing, and typed codes work either way.

### The QR code is deliberately tiny

It encodes `EC1:` plus a twelve-character token — sixteen bytes, QR version 1,
21×21 modules. Nothing else. Not the email address, not the name, not the meal.

This is the difference between a code that scans and one that does not. QR
version is driven entirely by payload length, and more modules in the same
printed area means smaller modules. At 300 px wide, this payload gives 10.3
pixels per module. The previous format embedded the email address, which cost
45–69 bytes and forced version 4–5 — around 7 px per module, and weaker error
correction. That margin is what lets a cracked phone screen, held at an angle
in a dim hall, still decode.

Verified: the generated codes decode with the scanner's own library down to
90×90 px.

**Do not add fields to the QR payload.** Look them up server-side from the
token instead. `make_qr_png()` refuses anything past QR version 2, so an
accidental change fails loudly during development rather than quietly at the
door.

### Publishing the scanner (zrok)

The scanner can be put on a public address instead of the local network. In
Settings, **Go live** starts a zrok share and gives you a `*.shares.zrok.io`
URL with a real, publicly trusted certificate. That solves the https problem
outright — no certificate warning on any phone — and volunteers no longer need
to be on the venue wifi.

One-time setup on the machine:

```bash
zrok enable <your-account-token>
```

**Only scanner routes are served publicly.** Every console path is refused over
that address, including the recipient list and the send controls, and the PIN
is mandatory there with no IP-based bypass. This matters more than it looks:
zrok connects to the application from localhost, so every visitor from the
internet arrives looking like `127.0.0.1`.

Two things to tell volunteers:

* zrok shows a warning page the first time — they tap **Visit Share**, once
  per phone.
* Then they enter the PIN, also once per phone.

Scans take roughly half a second over the internet against about ten
milliseconds on the local network. Both are fine for a door; pick the public
address when getting everyone onto one wifi is the harder problem.

### Keep the address fixed

By default zrok issues a **new random subdomain every time the share starts**,
so a link handed to volunteers dies at the next restart. Reserve a name once,
in Settings under "Fixed address", and the same URL comes back every time:

```
https://<your-name>.shares.zrok.io/scan
```

Set `ZROK_RESERVED_NAME` in `.env` so it survives a fresh database too. The
name is reserved on your zrok account, so it is yours until you release it, and
it can be printed or circulated before the event.

Two things the code has to handle, both learned the hard way:

* A share keeps its name for a couple of seconds after stopping, so a restart
  lands inside that window. Starting retries through it rather than failing.
* A share is a record on the zrok account, not just a local process. Killing
  the process leaves the record behind, and enough of them make the controller
  reject new shares with `invalid session` — which looks nothing like the real
  cause. Stale records for this port are pruned on start and stop; shares
  belonging to other machines or other uses are left alone.

If the application is killed while a share is open, the next start closes the
orphan automatically.

Set `ZROK_AUTOSTART=true` to reopen the share whenever the application starts.
It is off by default — publishing to the internet should be a deliberate click
— but worth enabling for an event, because a reboot otherwise leaves every
volunteer holding a dead link with nobody watching the console to notice. It
refuses to publish unless `SCANNER_PIN` is set.

`logs/server.log` and `logs/zrok.log` are appended across restarts; both are
rotated once at startup past `LOG_MAX_BYTES` (8MB by default). A week of idle
running produced 1.3MB and 10MB respectively.

### Running several scanners at once

Measured with six scanners against 400 guests, with 12% of guests presented
twice to exercise the race:

| | local network | public tunnel |
|---|---|---|
| p50 latency | 5 ms | 417 ms |
| p95 latency | 9 ms | 556 ms |
| sustained | 349 scans/sec | — |

Every guest was admitted exactly once and every repeat presentation refused.

Rate limiting counts only lookups that match *nothing*, so a volunteer working
a long queue is never throttled while someone guessing codes is stopped within
about twenty attempts. The first version limited requests per IP, which was
actively wrong: behind the tunnel every scanner shares one source address, and
a burst test had 296 of 448 legitimate scans rejected.

### Thank-you emails

When a guest checks in, a thank-you is queued and sent by a background worker —
never in the scan request, which would put one to three seconds of SMTP latency
in front of a volunteer at a door. The queue is a database table, so a crash
mid-event loses nothing, and it retries transient failures with backoff while
giving up immediately on bad addresses.

Exactly one thank-you is queued per coupon, enforced by a unique index rather
than a check-then-insert that several scanners could race through.

**Budget for two messages per guest.** An invitation plus a thank-you means 400
guests need about 800 sends, and a single Gmail account tops out near 500 a day.
The overview warns when capacity looks short; add a second account in Settings.

### Set a scanner PIN

Without `SCANNER_PIN`, anyone who can reach the machine on the network can open
the scanner and start redeeming coupons. With it, volunteers type it once per
phone. The console itself is restricted to the host machine regardless.

### Data lives in SQLite

`data/coupons.db`. CSV is import and export only. Redemption is a single
conditional `UPDATE`, so two volunteers scanning the same code at the same
instant cannot both admit the person — the database decides, and the loser is
told it is already used.

Every scan attempt, successful or not, is recorded. Export both from the
overview page.

---

## Project layout

```
app.py                    Flask routes, access control, send jobs
src/
  store.py                SQLite: coupons, recipients, scans, templates
  issuer.py               Coupon creation and QR rendering
  csv_mapper.py           Column-role detection
  templating.py           Sandboxed rendering, variables, email linting
  mailer.py               SMTP pool, connection reuse, rotation
  outbox.py               Background queue for thank-you mail
  tunnel.py               zrok public share, port checks
  encryption.py           Coupon payload encryption
templates/
  console/                Operator pages
  scanner.html            Check-in interface
  seed/                   Starter email templates
static/                   Styles, scripts, icons, vendored jsQR
tests/                    343 tests
archive/                  Past events and superseded code (gitignored)
```

---

## Development

```bash
python -m pytest tests/ -q
```

Tests never send email and never touch anything outside a temp directory.
This matters: the previous suite did both — running it delivered mail and wiped
the production database, because the data layer hardcoded its filename. Keep
paths injectable.

---

## Configuration

Everything is in `.env`; see `.env.example` for the full annotated list. The
ones that matter most:

| Variable | Why it matters |
|---|---|
| `SECRET_KEY` | Signs sessions. Required. |
| `COUPON_SECRET_KEY` | Encrypts coupon payloads. Changing it after issuing breaks them. |
| `SCANNER_PIN` | Without it the scanner is open to the network. |
| `SSL_ENABLED` | Without it phone cameras do not work. |
| `MAIL_DRY_RUN` | Suppresses delivery. Use while testing. |
| `THANK_YOU_TEMPLATE` | Template sent on check-in. Blank disables it. |
| `SCAN_FAIL_MAX` | Failed lookups per device before it is blocked (default 20). |
| `DATABASE_PATH` | Defaults to `data/coupons.db`. |

**Never commit** `.env`, `smtp_configs.json` (plaintext app passwords),
`*.pem`, or anything under `data/`, `archive/`, `exports/` or `uploads/` — they
hold credentials and attendee personal data. All are gitignored.

---

## Licence

MIT — see [LICENSE](LICENSE).
