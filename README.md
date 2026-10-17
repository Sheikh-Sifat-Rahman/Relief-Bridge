# Community Donation Management System

A Django prototype for disaster relief in Bangladesh. One account supports donor, volunteer and aid seeker roles simultaneously. Bootstrap templates provide public campaigns, private role dashboards and aggregate transparency charts. Admin email/password sign-in and a review centre live at `/management/`. Advanced Django admin operations live at `/management/operations/`.

## Quick start (local SQLite demo)

Python 3.10+ is required. Run these commands inside the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(50))'
```

Edit `.env`: paste the generated value into `SECRET_KEY`, set `DB_ENGINE=sqlite`, set `DEBUG=True`, and choose a `DEMO_PASSWORD`. Then:

```sh
python manage.py migrate
python manage.py seed_demo_data
python manage.py check
python manage.py test
python manage.py runserver
```

Open http://127.0.0.1:8000/. Bootstrap, Chart.js and optional web fonts load from public CDNs. Internet access is needed for those assets; core server workflows still run without them.

## MySQL setup

MySQL 8+ with InnoDB is the intended deployment database. Install and run MySQL locally, then use an administrator session to create an application database and account:

```sql
CREATE DATABASE community_donation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'community_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON community_donation.* TO 'community_app'@'localhost';
```

Set `DB_ENGINE=mysql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and `DB_PORT` in `.env`. Run `python manage.py migrate`. PyMySQL is the MySQL driver. Tests create a separate database: use a dedicated test account with permission for `test_community_donation`, never a production database. SQLite is a convenience for demonstrations; it does not provide MySQL's row-lock concurrency guarantees.

## Configuration

| Variable | Purpose |
| --- | --- |
| SECRET_KEY | Required random Django signing secret; no built-in fallback |
| DEBUG | Local development only; defaults to false |
| ALLOWED_HOSTS | Comma-separated hostnames, no schemes |
| DB_ENGINE | `mysql` by default; `sqlite` for local demo |
| DB_NAME / DB_USER / DB_PASSWORD | MySQL connection credentials |
| DB_HOST / DB_PORT | MySQL server; defaults 127.0.0.1:3306 |
| DEMO_PASSWORD | Required only when seeding fictional users |

The `.env` file and database are ignored by Git. Do not deploy demo accounts. With `DEBUG=False`, cookies require HTTPS. Configure HTTPS, a production WSGI server, reverse proxy, logging, backups and static file serving before deployment. Run `python manage.py collectstatic` and `python manage.py check --deploy` during deployment preparation. `manage.py runserver` is a development server.

## Architecture and database models

| App | Models and responsibility |
| --- | --- |
| accounts | Custom User (unique email), Role, unique UserRole, DonorProfile; registration and authorization |
| volunteers | VolunteerProfile, approved status and assigned warehouse |
| aidseekers | AidSeekerProfile and AidRequest, household vulnerability, verification, advisory priority |
| campaigns | DisasterCampaign, location, disaster type and simulated monetary progress |
| donations | Donation, DonationItem, MoneyDonation; goods inspection and simulated contributions |
| inventory | Warehouse, InventoryItem, immutable administrative InventoryTransaction ledger |
| distributions | DistributionEvent, unique DistributionAssignment, Distribution and DistributionItem |
| audit | AuditLog and concurrency-safe annual CodeSequence |
| dashboard | Role dashboard, public metrics, research reporting and demo commands |

Models reference role profiles instead of creating separate user accounts. Financial and operational records use protected foreign keys. Codes use locked per-year sequences, e.g. `DON-2026-000001`. Migrations are included. Business operations are service functions; views provide forms and filtered queries. Monetary values use decimal fields. Inventory has database constraints against negative stock and duplicate stock identities.

## Roles and permissions

Registration can request any combination of roles. Every public role, including donor, stays pending until admin approval. Users cannot submit donations or relief applications before their corresponding role is approved. Pending aid seekers can complete household details at `/accounts/household/`; staff separately verify the household and individual requests. Edits to household facts reset profile verification to pending.

Only `ACTIVE` UserRole records grant module access. Authentication and role checks run on every private role view. Detail queries include the current user's ownership or assignment; another user's object returns 404. An authenticated user without the required active role receives 403. Warehouse summaries are read-only and limited to the volunteer's assigned warehouse. Delivery views expose only operational beneficiary contact/location, never vulnerability scores or donor information.

The shared navbar and ordinary dashboard contain no administrative controls, including for staff. Authorized staff open `/management/` directly and sign in using their email and password. Django's normal model permissions still apply to management screens. Audit records, payments, donation master records and stock ledger rows are read-only in management. Inventory quantities and completed deliveries cannot be changed through ordinary admin forms. Database administrators and custom scripts remain trusted; ORM writes outside services can bypass application-level workflows.

## Main routes

| Routes | Purpose |
| --- | --- |
| `/`, `/campaigns/`, `/campaigns/<id>/` | Public overview and active campaigns only |
| `/transparency/` | Anonymous aggregate charts and research indicators |
| `/accounts/register/`, `/accounts/login/`, `/accounts/logout/` | Authentication; logout uses POST with CSRF |
| `/accounts/profile/`, `/accounts/password/`, `/accounts/household/` | Account, password and household updates |
| `/dashboard/` | Separate cards for every active role |
| `/donor/`, `/donor/profile/` | Donor dashboard and profile |
| `/donor/donate-goods/`, `/donor/donate-money/` | Goods pledge and explicit payment simulation |
| `/donor/donations/`, `/donor/history/`, `/donor/donation/<id>/` | Own history and tracking |
| `/volunteer/`, `/volunteer/profile/`, `/volunteer/assignments/` | Own operational overview and assignments |
| `/volunteer/distribution/<id>/`, `/volunteer/deliveries/` | Assigned delivery detail and confirmation |
| `/volunteer/warehouse-summary/` | Assigned warehouse stock, read-only |
| `/seeker/`, `/seeker/profile/`, `/seeker/request-aid/` | Household dashboard, profile and request creation |
| `/seeker/requests/`, `/seeker/request/<id>/` | Own requests and status |
| `/seeker/received-aid/`, `/seeker/distribution-history/` | Own approved/scheduled/completed aid |
| `/management/` | Separate Django admin for staff operations |

Named namespaces: accounts, campaigns, dashboard, donor, volunteer, seeker and admin. History, requests, received aid, assignments and delivery routes render distinct role-specific sections.

## Demo users

Run `python manage.py seed_demo_data` with `DEMO_PASSWORD` set. Every seeded account uses **the password you choose in that variable**; there is no hard-coded password.

| Username | Access |
| --- | --- |
| demo_admin | Superuser, management |
| demo_donor | Donor |
| demo_volunteer | Approved volunteer |
| demo_seeker | Approved aid seeker |
| demo_multi | Donor and volunteer |
| demo_all | All three active roles |

The command creates fictional Sylhet, Khulna and Dhaka campaigns, role profiles, two stock items, inspected goods, simulated donations, approved aid requests, an event, assignments, a completed distribution and an upcoming delivery. All contact data uses `example.invalid` or explicit DEMO labels. Rerunning the command does nothing if demo_admin already exists. It is not a fixture reset tool. Create your own administrator with `python manage.py createsuperuser`.

## Donation workflow

1. A donor selects an active campaign and submits one goods line per pledge.
2. Admins accept or reject the donation in the review centre. Approved goods still require inspection before any inventory receipt. Staff then open **Donation items**, select an item and choose **Inspect & receive goods** in the object tools.
3. Staff enter accepted quantity, destination warehouse and a rejection reason for any rejected quantity.
4. The service locks the item, prevents a second inspection, records accepted/rejected totals, creates a stock-in movement, updates stock and writes an audit entry atomically.
5. Donors see their pledge and inspection outcome in donation tracking.

Money donations are simulations only: the form accepts an amount and campaign, creates a `SIM` reference and remains pending. Admin acceptance records success and increments the campaign's simulated total atomically; rejection marks the simulation failed and leaves campaign totals unchanged. No payment credentials, card details, PINs, OTPs or banking secrets are requested or stored.

## Inventory and distribution workflow

1. Staff create warehouses and stock identities. All stock identities start with zero quantity.
2. Goods inspections create stock-in entries. For manual receipts, signed corrections or withdrawals, open an inventory item and choose **Record stock movement**. A reference and notes are required.
3. Staff verify a household, review a request, set verification status and explicitly approve or partially approve it. Priority never changes approval automatically.
4. Create a distribution event, assign an approved volunteer, then create a distribution matching its request, beneficiary and campaign. Add inventory lines from the event warehouse using the stock item's unit.
5. The assigned volunteer opens their delivery and confirms receipt, or staff use **Confirm delivery / review duplicates** on the distribution.
6. Confirmation locks the distribution, beneficiary and inventory rows. It validates assignment, approved request, warehouse, units, positive quantities and available stock. All stock-out entries, balances, delivery status, request status and audit entries commit together. A failure rolls everything back.
7. Already completed deliveries cannot be confirmed twice. Staff mark event assignments completed when their work is finished.

Possible duplicates match the same beneficiary, campaign and at least one goods category. The review shows prior dates, events and delivered items. Volunteers can flag the warning but cannot override it. Staff can proceed with a written reason after review. The warning does not reject an aid request. Warnings and overrides are audited. A beneficiary lock serializes same-beneficiary confirmations on MySQL.

## Advisory priority algorithm

`aidseekers/services.py:calculate_priority_score` assigns: destroyed house 30, severe damage 20, partial damage 10; lost income 20; displaced 15; no safe water 15; each child 3 (maximum 15); each elderly person 5 (maximum 15). The sum is capped at 100.

Levels are LOW 0–29, MEDIUM 30–49, HIGH 50–69, CRITICAL 70–100. Requests store both score and level. Verified request pages label the result **System Recommended Priority**. This is a transparent weighted formula, not AI, and it never automatically approves or rejects assistance.

## Research support

```sh
python manage.py research_report
```

This prints aggregate JSON with donation and beneficiary counts, accepted/distributed goods, stock balance, simulated money, requests, priority-level counts, average priority, critical beneficiaries served, duplicate warnings/overrides and completed distributions. Traceability percentage measures the share of inventory rows whose balance reconciles exactly to stock-in minus stock-out plus signed adjustments. It measures ledger reconciliation, not donor-to-beneficiary lot provenance. Goods quantities sum different units; use individual categories and units for research comparisons. This prototype does not establish causal effectiveness or validate scoring weights against real outcomes.

## Validation

```sh
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py check
python manage.py test
```

Tests cover registration/login, role uniqueness and activation, role isolation, multi-role dashboards, donation/request ownership, assigned deliveries and warehouses, negative-stock prevention, direct volunteer stock-edit denial, atomic rollback, delivery stock deduction and replay prevention, duplicate warning and staff override, advisory score weights/caps/thresholds, goods inspection, simulated payments, template rendering, public identity protection, research reconciliation and staff pages. The initial local verification used SQLite; MySQL integration and concurrent-load tests require a running MySQL server.

## Current limitations and future work

- Research/development prototype, not a production emergency response deployment.
- No real payment gateway, refunds, notifications, password reset email or identity-document verification.
- Staff manually review and approve roles and requests; no public medicine donations (future work requires specialized handling).
- Inventory is pooled by warehouse/category/item/unit; there is no lot-level expiry control, reservation system or direct lineage from individual donation to individual beneficiary. Donation tracking records pledge/inspection state, not a complete item custody timeline.
- One goods item per public pledge. Manual stock references are not automatically matched to external documents.
- Duplicate matching is category-based within a campaign and account; it does not detect multiple accounts belonging to one household or similar packages across campaigns.
- No geospatial optimization, delivery proof attachment, Bangla translation, accessibility audit or offline synchronization.
- Add MySQL concurrency/load testing, independent security review, authentication throttling, HTTPS deployment hardening, operational backups and validated research consent procedures before a real pilot.
- Bundle/version third-party front-end assets locally for offline use and a stricter content security policy.


## Admin review centre and email login

- Open `/management/` or `/management/login/`.
- Existing local demo admin: `admin@example.invalid`; password is the configured `DEMO_PASSWORD` (`CommunityDemo2026!` in the prepared local demo).
- `/management/profile/` provides the administrator profile and editable contact details.
- The review centre lists all pending role-access requests, goods/money donation requests, and relief applications. Open a request, inspect its details, then choose Accept or Reject. Rejection requires a reason. Decisions are recorded with timestamps and audit logs and displayed to applicants.
- New donor, volunteer and aid seeker roles are PENDING. Only explicit admin approval grants role access. A pending aid seeker may complete their household profile but cannot submit a relief application.
- Pending or rejected donations never enter inventory. Accepted goods require a separate inspection and receipt. Money simulations only contribute to campaign totals after acceptance. Repeated review cannot double count money.
- Relief applications remain submitted until a human administrator accepts or rejects them; scoring never decides the outcome.
- Existing historical accepted donations retain their prior state. Previously auto-active donor roles without an administrative approval audit entry are moved back to PENDING during migration. Previously explicitly approved demo accounts remain active.
- Advanced management routes moved to `/management/operations/`. Normal user dashboards contain no admin controls.
- Run `python manage.py seed_review_demo_data` after seeding to add fictional pending examples for every review queue. The `demo_pending` account is a review example with an unusable password.

Review validation includes admin email authentication, nonstaff rejection, approval gates on GET and POST, required rejection reasons, immutable decisions, pending payment totals, approved-only inventory receipts, decision visibility and CSRF protection.


## Login separation and profile navigation

Administrator accounts (by email or username) are rejected by the regular `/accounts/login/` form. Use **Log in as administration** at `/management/login/`; successful administrator login stays within management routes. Regular users may still sign in with their username or email.

Approved role cards link to donor, volunteer and aid seeker dashboards. Each role dashboard includes explicit navigation to its own records/history and a link back to My dashboard. Profile editing is available at the bottom of `/accounts/profile/`, below the profile summary and roles. Role dashboards no longer contain donor/household profile editing buttons. Pending household profiles can still be completed before review, while submission and role-module access remain approval protected.

The test suite now has 66 tests, including following every role-dashboard navigation link and checking login separation and editor placement.


## Optional goods photos

The goods donation form accepts an optional JPEG, PNG or WebP photo (maximum 5 MB and 20 megapixels). Pillow validates the image; it is resized to fit 1600×1600, re-encoded as JPEG and stored under a random filename without original EXIF metadata. Photos appear on the donor's donation detail, the administrator review page and the staff inspection record. Existing donations and donations without a photo continue to work.

Photos are stored in `MEDIA_ROOT` and served through the authenticated `/donor/item/<id>/photo/` view, available only to the owning donor and staff. Do not expose the goods upload directory via a public media URL in production. Photo responses use private, no-store caching. Back up the private media directory alongside the database.

After pulling this change, install requirements and run migrations. The test suite has 72 tests, including optional uploads, valid uploads, normalization, admin previews, private image access and invalid/oversized/unsupported images.


## Persistent administrator navigation

Admin login now opens **Review center** at `/management/review/`. The separate admin dashboard page has been removed; `/management/` displays Review center too. For staff, **My dashboard** is a persistent menu with **Review center** and **Operations**, available on the public site and every Django admin operations page. **Profile** is a separate navigation link; the duplicate Admin profile shortcut was removed. Staff visits to the normal `/dashboard/` and `/accounts/profile/` redirect to the appropriate management pages. Regular users keep their role dashboard and profile navigation. The suite now includes 79 passing tests.


## Operations changes and website visibility

Operations writes to the same database used by website pages. Active campaigns appear in the campaign list and donation/relief forms; the homepage shows the three newest active campaigns. Draft, paused and closed campaigns remain hidden. Campaign Operations provides Publish/Unpublish actions and visibility messages after saving. A new draft needs publication before it appears publicly. Refresh an already-open page after saving changes in another tab.

Unused records can be deleted through Operations. Records referenced by donations, distributions or ledger transactions retain their protected relationships; unpublish a campaign to remove it from public pages while preserving its history. Financial and inventory ledger rows remain read-only; stock changes use recorded stock movements. Integration tests submit real Operations add/edit/delete requests and verify public pages and donation choices update, and that removing a role immediately revokes its dashboard/module access.


## Operations appearance

Operations uses a shared green-and-white theme matching the public website. The module index uses permission-aware cards; record tables, filters, navigation, form fields and action buttons share the same palette. Styling lives in `static/css/operations.css`, with template overrides under `templates/admin/`. Django admin continues to handle authorization, forms, validation, add/change/delete operations and bulk actions. The Operations theme uses a consistent light palette.
