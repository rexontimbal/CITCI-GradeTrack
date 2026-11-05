# Accessibility Audit — Phase 8 part B

## Method

`tools/accessibility_audit.py` (Playwright, vendored `axe-core` 4.14.0 — `npm pack axe-core`,
unpacked into `tools/axe/axe.min.js`, dev-tooling only, never served to the app) logs in as each of
the four demo accounts and runs `axe.run()` on every page in that role's sidebar menu
(`accounts/menu.py`): **33 page visits total** — 18 admin pages, 6 program-head pages, 5 instructor
pages, 4 student pages.

```
python manage.py seed_demo_users && python manage.py seed_citci_academics
python manage.py runserver 127.0.0.1:8000 --noreload
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role admin --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role program_head --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role instructor --append
python tools/accessibility_audit.py --base-url http://127.0.0.1:8000 --role student --append
```

(Run one `--role` at a time, each appending to the same `--out` file — see "Environment note"
below for why.)

## Result

**0 critical, 0 serious, 0 moderate, 0 minor violations** across all 33 pages, after one fix (see
below). Full machine-readable output: `tools/axe/results.json` (currently an empty list).

## The one finding, and the fix

Every single page flagged the same **serious** `color-contrast` violation, always on the exact same
element: `.mb-5 > .mt-1.text-gray-500` — the page subtitle rendered by the one shared
`templates/partials/_page_header.html` every page includes. Tailwind's `text-gray-500` (`#6b7280`)
on a white background is roughly 4.0:1, under WCAG 2 AA's 4.5:1 minimum for normal-size text.

**Fixed**: `text-gray-500` → `text-gray-600` (`#4b5563`, ~7.2:1 on white, comfortably passes AA) in
`_page_header.html` — a one-line, one-file fix that resolved the finding on all 33 pages at once,
since they all share the partial. Re-running the audit after the fix confirmed zero violations
anywhere.

No other issues were found. This likely reflects pre-existing care rather than luck: shared chrome
already had `aria-live` on the toast stack, `aria-label` on icon-only buttons (sidebar toggle,
mobile menu, notification bell), and `Escape`-to-close on the shared modal and sidebar drawer (see
CLAUDE.md section 9, Phase 8 part A's accessibility pass) — this phase's audit is evidence that pass
actually worked, not a replacement for it.

## What wasn't covered

- **Admin "Add" modals** (the part-B spec's "modals open" item): the audit script supports an
  `admin_modals` role that opens the Add Program / Add User modals and audits them too, but it
  could not complete reliably in this sandboxed execution environment — Chromium crashed
  intermittently on the click/navigation step specifically for the modal flow (the 33 plain page
  visits above were completely reliable; only the interactive modal-open step was flaky). This is
  recorded as a tooling/environment limitation, not a finding about the app: re-run
  `python tools/accessibility_audit.py --role admin_modals --append` on a non-sandboxed machine to
  complete this check — the shared modal partial (`partials/_entity_form_modal.html`) already labels
  every field (`<label for=...>`) and the modal close button, so a clean result is expected but not
  yet machine-verified.
- **Pages requiring specific object state** not reachable from a fresh demo-data seed (e.g. a
  grade-sheet review page mid-approval, the forecast drawer) weren't individually re-added to the
  page list this pass — they reuse the same shared chrome/CRUD/modal templates already covered.
- This is an **automated** audit (axe-core catches roughly 30-40% of WCAG issues by its own
  documentation) — it does not replace manual checks like actual screen-reader navigation or
  keyboard-only task completion, neither of which was performed this pass.

## Environment note (for anyone re-running this)

Running Chromium under Playwright in this particular sandboxed environment was unreliable when
driving more than one role's worth of logins/navigations in a single browser process — it would
crash non-deterministically partway through. The script works around this by auditing **one role
per process** (`--role`, appending to the same output file) rather than looping over every role in
one browser lifetime; on a normal (non-sandboxed) machine, `--role all` in one run should work fine.
