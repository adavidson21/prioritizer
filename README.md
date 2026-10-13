# Prioritizer

A calm, keyboard-first task app for deciding what to work on. Add a task once and it shows up everywhere.

## How it decides

Each task gets three inputs, usually set in Triage in a few seconds:

- **Value:** Trivial, Low, Medium, High (1 to 4).
- **Effort:** XS, S, M, L, XL, worth 1, 2, 3, 5 and 8 points.
- **Due date:** optional. Without one, a task gets an implied due date from its age: 2 days for High value, 4 for Medium, 7 for Low, 14 for Trivial.

Everything else is derived, so the views can't disagree:

- **Eisenhower:** important means Medium or High value; urgent means due within 3 days, overdue, or flagged urgent.
- **Value / Effort:** high value means Medium or High; low effort means XS or S.
- **Score:** (value + urgency) / effort points, shown next to each task. The bar on the left of a row is its priority tier.

Your manual rank always has the final say. **Suggest order** previews a score-based order before you accept it.

## Views

- **Today:** your short list for the day (3 to 5 works best), plus Up next by score and everything you're waiting on, with follow-up nudges.
- **Triage:** one unsorted or stale task at a time. A task is stale at twice its implied window (4, 8, 14 or 28 days).
- **Prioritize:** List (stack rank with a weekly capacity line), Eisenhower, and Value / Effort. Dragging into a quadrant sets the fields it needs.
- **People:** one card per person, split into "Waiting on them" and "To discuss or do". Handy as a 1:1 agenda.
- **Archive:** a weekly recap you can copy into a status update, with how your work split across quadrants, plus finished and won't-do tasks.

The **Scope** in the sidebar (All lists, a list, or a section) filters every view.

## Adding tasks

Press `N` or `Ctrl+K` (`Cmd+K` on a Mac) anywhere. Optional inline tags:

| Tag | Sets | Example |
| --- | --- | --- |
| `@name` | Person | `@Brandon` |
| `!1` to `!4` | Value | `!4` |
| `!!` | Urgent | `!!` |
| `~xs` to `~xl` | Effort | `~m` |
| `^date` | Due: `today`, `tomorrow`, a weekday, `+3d`, or `YYYY-MM-DD` | `^fri` |
| `#name` | List or section (prefix match) | `#eng` |

Example: `Review promo doc @Brandon !3 ~s ^fri #eng`

## Keyboard

`1` to `5` switch views, `J`/`K` move through tasks, `Enter` opens details, `X` completes, `T` toggles Today, `Alt+Up`/`Alt+Down` reorder, `Esc` closes. In Triage: `1` to `4` value, `Q W E R T` effort, `D` due, `U` urgent, `Space` Today, `Enter` save and next, `S` skip, `0` won't do. Press `?` for the full list.

## Themes

Slate (light) and Graphite (dark) follow your system setting by default. Also available: Ivory (warm light), Solarized Light, Nord and Dracula, all tuned so text meets WCAG AA contrast. Pick one from the theme button at the bottom of the sidebar; the choice is saved per device.

## Saving and syncing

- Everything saves automatically in your browser, so it works offline.
- **Sign in** (person icon, bottom of the sidebar) with any email and password to sync your board across devices. Changes from each device are merged, not overwritten. Sign-in is powered by Supabase (setup in `supabase-setup.sql`; project URL and publishable key live in `CLOUD` in `index.html`).
- The folder icon can keep `prioritizer.xlsx` in a folder you choose (Chrome or Edge), and has Download a copy and Import a file. The Excel file has one sheet per list. Files from the previous version still import.

## Install it as a desktop app

On the hosted GitHub Pages link in Chrome or Edge, use the Install button in the address bar. It opens in its own window with a dock or taskbar icon and works offline. It installs per user from the browser, with no admin rights or executable. If Install never appears on a work laptop, your company's browser policy may block web app installs.

On a phone, use your browser's "Add to Home Screen".

## Running it

No build step. `index.html` holds the whole app (inline CSS and JavaScript). The only other files are for the installable app: `manifest.webmanifest`, `sw.js` and `icons/`. Open `index.html` directly, or serve the folder. When you ship a change, bump `CACHE` in `sw.js` so open windows offer a "New version" reload.

### Upgrading from the previous version

Boards migrate automatically on first load: High/Low value becomes High (4) or Low (2), Important becomes Medium or Low when no value was set, High/Low effort becomes L or S, and Urgent becomes the urgent flag. Existing tasks keep their created dates, so expect a one-time batch of stale tasks in Triage. Reload each device once after deploying, before editing.
