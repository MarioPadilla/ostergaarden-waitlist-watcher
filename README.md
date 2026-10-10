# ostergaarden-waitlist-watcher

Watches the [Østergården external waiting list page](https://findbolig.nu/da-dk/udlejere/oestergaarden/ekstern-venteliste) on findbolig.nu and sends a phone push notification the moment the text **"Lukket for opskrivning"** disappears, meaning the list has opened. Every status change is logged to `history.csv`.

## How it works

- A GitHub Actions workflow (`.github/workflows/check.yml`) runs every 5 minutes.
- `check.py` loads the page in headless Chromium (Playwright), because the site is JavaScript-rendered, and reads the visible text.
- **Sanity check:** if the text "ekstern venteliste" is missing, the page did not render properly (or the layout changed). The script saves a screenshot and the page text to `debug/` (uploaded as a workflow artifact) and exits non-zero, so you get a failed-run email from GitHub instead of a false alert.
- If "lukket for opskrivning" is present the status is `closed`, otherwise `open`.
- The previous status is stored in `state.txt`. On a change the script:
  1. sends the [ntfy.sh](https://ntfy.sh) notification first,
  2. then writes `state.txt` (so a failed notification is retried on the next run),
  3. then appends a row to `history.csv`.
- The first-ever run does not notify if the status is `closed`; it does if it is `open`.
- The workflow commits `state.txt` and `history.csv` back to the repo when they change.

## Setup (if you fork this)

1. Pick a long, random ntfy topic name (it works like a password, so anyone who knows it can read and post to it), e.g. `ostergaarden-` plus 12 random characters.
2. Add it as a repo secret: `gh secret set NTFY_TOPIC` (or Settings → Secrets and variables → Actions). Never put it in code or commits.
3. Subscribe to the same topic in the phone app (below).

## Subscribe on your phone

1. Install the **ntfy** app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347)).
2. Tap **+**, enter the topic name, and keep the default server (`ntfy.sh`).
3. For the urgent "open" alert, allow notifications and consider letting ntfy override Do Not Disturb.

## Testing

From the **Actions** tab, choose *Check waiting list* → *Run workflow* and set **force_status** to `open` (or `closed`). The script sends a `[TEST]` notification and exits. It does **not** read the page or touch `state.txt` / `history.csv`, so tests never pollute the log.

To run locally:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
NTFY_TOPIC=your-topic python check.py
# or write state/history to a scratch directory instead of the repo:
STATE_DIR=/tmp/test NTFY_TOPIC=your-topic python check.py
```

## Known limitations

- **GitHub cron is not punctual.** Scheduled runs are often delayed by 5–30 minutes or more, and some are skipped under load. If the list is open for only a few hours, you may be notified late.
- If that delay is a problem, run the same `check.py` on a Raspberry Pi (or any always-on machine) with a cron job every minute:
  ```
  * * * * * cd /path/to/repo && NTFY_TOPIC=your-topic .venv/bin/python check.py
  ```
- Only the two text markers are checked. If the site rewords them, the sanity check or the status logic may stop matching; the former fails loudly, but a reworded "closed" message would look like `open`. Treat an unexpected "open" alert with a quick look at the page.

## Keeping the schedule alive

GitHub disables scheduled workflows in public repos after 60 days without repo activity. Status-change commits count as activity, but the list may stay closed for months, so `.github/workflows/keepalive.yml` runs monthly and makes an empty `keepalive` commit only if the latest commit is older than 30 days.

## Reading `history.csv`

Columns: `timestamp_utc,timestamp_copenhagen,status`. A row is added only when the status **changes**, so each row marks the *start* of that status. For example:

```
timestamp_utc,timestamp_copenhagen,status
2026-10-10T16:01:56Z,2026-10-10T18:01:56+0200,closed
2026-11-03T08:12:40Z,2026-11-03T09:12:40+0100,open
2026-11-03T11:47:05Z,2026-11-03T12:47:05+0100,closed
```

The list was open from 09:12 to 12:47 Copenhagen time that day, about 3.5 hours. Timestamps are when a check *noticed* the change, so they can lag the real event by the cron delay.

## Terms of use

Please check the findbolig.nu terms of use. This script reads one public page every 5 minutes; keep it that way and do not make it more aggressive.
