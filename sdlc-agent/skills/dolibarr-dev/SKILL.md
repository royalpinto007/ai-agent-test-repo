---
name: dolibarr-dev
description: Develop custom Dolibarr modules end-to-end — scaffold/modify modules, fields, tables, pages, permissions, menus, hooks and triggers, admin/setup pages, config constants, and third-party API integrations (e.g. carrier/payment REST APIs) — by reading the existing Dolibarr core/custom code and DB first, then building by mirroring it. Use whenever the request is to create/build/extend a Dolibarr custom module, add a hook or trigger, add or change a field/table/page/menu/permission, integrate an external API, read or write a module config constant, or find the exact hook context / hook method / trigger action-code name from the codebase.
when_to_use: Triggers on Dolibarr module development, "create a module", "add a field/table/page/menu/permission", "add an extrafield / extra attribute on an order/invoice/product", "add or remove a field LATER / alter table / change the schema", "add a hook", "add a trigger", "which trigger fires when X", "what hook context does page Y use", "write some logic/business rule in Dolibarr", "plan this feature / design before building / what's the best approach in Dolibarr", "think through all the scenarios / what could break / what am I missing", "build a feature for sales/finance/warehouse/manufacturing/logistics users", "proposal/order/invoice/shipment/stock logic", "integrate FedEx/UPS/Stripe/<any> API", "store/read a module setting", "add an admin/setup page", "security review / is this module safe / fix SQL injection or XSS or CSRF", "reuse existing functions instead of rewriting", "find and remove dead/unused code", "test the business flow end-to-end before confirming", "what did we build in this module before / what was the requirement", "why isn't my change showing", "where are the logs", scaffolding under htdocs/custom, or any work involving amb_* (Advance Module Builder) tools, actions_*.class.php hook handlers, core/triggers/interface_*.class.php files, or lib/*.lib.php helpers.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, mcp__dolibarr_expert
---

# Dolibarr Custom-Module Development

**Core principle: read the existing code and DB first, then build by mirroring
it.** Dolibarr is a large, consistent codebase — almost everything you need to
write already exists somewhere in core or another module. Find a concrete,
working example and copy its structure, naming, and conventions. Don't
approximate from memory.

A module is addressed by its **name** (`module`, e.g. `DeliveryCarrier`); its
files live under `htdocs/custom/<module-lowercased>`. There is no `read_file`
tool — inspect or verify any file by reading it straight off disk with
`Read`/`Grep` under `htdocs/custom/<module>/` (or core under `htdocs/`).

## Two ways to build — pick the lighter one that fits

1. **Hand-write PHP/SQL that mirrors core** — the default for almost all real
   work: descriptor edits, object classes, hand-written `sql/llx_*.sql`, hook
   handlers, triggers, admin pages, lib helpers, API integrations. You have
   `Read`/`Edit`/`Write` and `Bash`; use them on the files directly. This is how
   the modules in `htdocs/custom/` are actually built.
2. **`amb_*` Module Builder MCP tools** (server `dolibarr_expert`) — an *optional
   scaffolder*. Best for generating a brand-new module skeleton or a standard
   object's boilerplate (class + SQL + card/list/menus). Each call edits the
   generated files on disk **directly** — no manifest, no regenerate/validate
   step. The structured tools (`amb_add_field` etc.) are convenient for the
   standard object pattern, but you are **not** required to route changes through
   them — editing the PHP/SQL by hand is equally valid and often clearer.

   ⚠️ `amb_*` can return **HTTP 501** (endpoint unavailable). Fallback: hand-scaffold
   by mirroring an existing custom module — the output is identical standard files.

Bundled helpers (call via `${CLAUDE_SKILL_DIR}/scripts/...`):
- `scan-code.sh` — extract hook contexts, hook method points, trigger action
  codes, locate API definitions/usages, and **inventory a module's own functions
  (`funcs`)** — all **from the actual code** (never guess a name; reuse before rewriting).
- `dol-db.sh` — read-only DB access (schema, enabled modules, consts) via `conf/conf.php`.
- `dol-log.sh` — read-only access to the syslog file (path/tail/follow/grep) — for **debugging runtime behavior**.
- `audit.sh` — pre-confirm audit of a module: `security` (risky patterns),
  `deadcode` (defined-but-uncalled functions), `files` (unreferenced files). Run before you say "done".
- `brain.sh` — the **per-module brain**: `path`/`show`/`init`/`list` a durable
  `htdocs/custom/<module>/.dolibarr-dev/BRAIN.md` recording each module's
  requirements, decisions, scenarios, and satisfaction. **Read at Step 0; update
  at plan time and before confirming.**

Set `DOL_HTDOCS` if the Dolibarr root is not `/var/www/html/dolibarr-20/htdocs`.

---

## Token economy — start lean, STAY lean (compact as you go)

This skill reads a lot (LEARNINGS, scans, schema, large class files). Keep the context small so tokens aren't wasted:

- **Compact first.** If the conversation is already long when a Dolibarr task starts, compact/summarize it (e.g. `/compact`) before diving in — don't carry unrelated history through a read-heavy task. Tell the user you're compacting so the heavy reading fits.
- **Compact again roughly every ~100k tokens of work.** These tasks are long and read-heavy, so context grows fast. About every ~100k tokens used — or whenever the context feels heavy — **checkpoint to the module brain first** (so the requirement, decisions, and status survive the compaction), tell the user, then `/compact`. Don't wait for the hard auto-compact limit; trimming earlier makes every later turn cheaper. (Claude Code also auto-compacts near the context limit — this is the earlier, deliberate pass.)
- **Prefer the helper scripts' compact output** (`scan-code.sh`, `dol-db.sh`, `audit.sh`) over dumping whole files — they return summaries, not full dumps.
- **Read only the slice you need** — `Grep`, or `Read` with `offset`/`limit`. Don't read a 1000-line class whole when you need one method. **Never `cat` big files** (the syslog is gigabytes — always tail/grep).
- **Offload broad searches to an `Explore` subagent** — let it sweep many files and return only the conclusion, so the file dumps never enter the main context.
- **Don't re-read** a file already in context, and don't re-derive facts already established.

---

## Step 0 — Understand before you build (ALWAYS)

0. Read accumulated lessons first: `cat ${CLAUDE_SKILL_DIR}/LEARNINGS.md`. Apply them.
0.5 **Read the module's brain** — `bash ${CLAUDE_SKILL_DIR}/scripts/brain.sh show <module>`.
   If it exists, it tells you WHAT was demanded before, WHY it was built that way,
   which scenarios were considered, and what's still open — so you don't re-derive
   intent or undo a deliberate choice. If it does NOT exist, `brain.sh init <module>`
   and reconstruct purpose from the code + `git log` (and ask the user). Treat the
   brain as intent, not truth: confirm any claim against the live code.
1. List what exists: `bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh modules` (or
   `amb_list_modules`). Read the target module's descriptor + classes on disk
   (`htdocs/custom/<module>/core/modules/mod*.class.php`, `class/`, `sql/`).
2. Read the DB schema you'll touch:
   - `bash ${CLAUDE_SKILL_DIR}/scripts/dol-db.sh modules`
   - `bash ${CLAUDE_SKILL_DIR}/scripts/dol-db.sh describe <table>`
   - `bash ${CLAUDE_SKILL_DIR}/scripts/dol-db.sh const '<MODULE>%'`
3. If hooks/triggers/an external API are involved, discover the real
   names/endpoints **before** writing code (see the sections below).
4. Find a working example of the thing you're about to build and read it.

---

## Know the business need FIRST — who uses this, and for what?

Dolibarr is an ERP. Before writing anything, decide **which business role** the
change serves and **which standard object/flow** it touches — then build on top of
that flow instead of inventing a parallel one. Ask the user the role + the step if
it's unclear. Map of the common roles → what to reuse:

| Business role / need | Core modules & objects to build on | Tables | Hook contexts | Trigger codes (discover exact with `scan-code.sh triggers`) |
|---|---|---|---|---|
| **Sales / commercial** — quote→order→invoice | `Propal`, `Commande`, `Facture`; thirdparty, contact, product | `llx_propal(det)`, `llx_commande(det)`, `llx_facture(det)` | `propalcard`, `ordercard`/`commandecard`, `invoicecard` | `PROPAL_*`, `ORDER_*`, `BILL_*` |
| **Manufacturer / logistics** | MRP `Mo`, BOM, Workstation; `Expedition`, `Livraison`, shipping methods (`deliverycarrier`) | `llx_mrp_mo`, `llx_bom_bom`, `llx_expedition`, `llx_c_shipment_mode` | `mocard`, `bomcard`, `expeditioncard`, `ordershipmentcard` | `MRP_MO_*`, `BOM_*`, `SHIPPING_*` |
| **Stock / warehouse manager** | `Entrepot` (warehouse), `MouvementStock`, `Inventory`, product lots/serials, reception | `llx_entrepot`, `llx_stock_mouvement`, `llx_product_stock`, `llx_product_lot` | `stockcard`, `warehousecard`, `receptioncard` | `STOCK_MOVEMENT`, `PRODUCT_*`, `RECEPTION_*` |
| **Finance / accounting** | `Facture`, `Paiement`, bank `Account`, accounting ledger, taxes, supplier invoices | `llx_facture`, `llx_paiement`, `llx_bank`, `llx_accounting_bookkeeping`, `llx_tva` | `invoicecard`, `bankcard`, `accountancycard` | `BILL_PAYED`, `PAYMENT_*`, `BILL_SUPPLIER_*` |

Use the table to **locate the real object/flow**, then read that core code
(`scan-code.sh find-api <Class>`) and mirror it. The right business logic almost
always means *extending the standard document at the right step* (a hook on
`ordercard`, a trigger on `BILL_VALIDATE`), not a from-scratch feature.

**Test the flow with real documents** via the `mcp__dolibarr_expert` tools, which
mirror these roles end-to-end: `create_proposal`→`convert_proposal_to_order`→
`convert_order_to_invoice`→`validate_invoice`→`add_payment_to_invoice`;
`get_product_stock`/`update_product_stock`; `get_financial_summary`. Drive the
actual business step your code hooks into and confirm it fired (see the
"prove it" section).

---

## PLAN FIRST — business-first, every-scenario (do this BEFORE writing code)

Most defects are not coding mistakes — they are **missed scenarios**. (In
`deliverycarrier` the first cut rated a shipment as one box and never asked "what
if there are multiple boxes?" — an obvious-in-hindsight case that should have been
listed up front.) The cost of finding a scenario at plan time is a sentence; at
code time it's a rewrite. So plan deliberately, in this order, and **write the
plan into the module brain** before building:

**1. Understand the business requirement — restate it, don't just read it.**
Say back, in business terms, the real-world outcome the user wants (not the
literal feature). Who is the persona (use the role map above)? Which real document
/ step / decision does this serve? If the outcome or persona is unclear, **ask** —
a wrong assumption here invalidates the whole plan.

**2. Map the demand onto Dolibarr — what already exists?** Which standard
object / table / status / flow does this belong to (`scan-code.sh find-api
<Class>`, the role map, the schema)? What does Dolibarr already do natively here?
Reuse-first applies to *design*, not just code: extend the standard document at
the right step instead of inventing a parallel flow.

**3. Enumerate EVERY scenario — the anti-"multiple-boxes" pass.** Walk these
dimensions explicitly and write down what each means for this feature:
   - **Multiplicity / cardinality:** one vs many (one box vs many; one line, one
     carrier, one warehouse, one currency vs many). *This is the box lesson — check it first.*
   - **Document lifecycle / state:** draft → validated → cancelled → reopened →
     set-back-to-draft → closed → deleted. What must happen to YOUR data on each
     transition? (e.g. clear cached rate-state on `ORDER_CANCEL`/`REOPEN`.)
   - **Persona & permissions:** who may see/do it; `hasRight` gating; multi-entity
     leakage (every query scoped by `entity`).
   - **Boundaries & types:** zero / empty / negative / huge values; unit
     conversions (kg↔lb, in↔cm); domestic vs international; rounding & currency.
   - **Failure & retry:** external API down / 401 / timeout / partial success;
     **regeneration leaving stale data** behind (delete-then-write); idempotency.
   - **Concurrency & backward-compatibility:** two users at once; existing rows /
     saved sessions / stored JSON written by the OLD shape must still load.
   - **Integration ripple:** does this value need to flow to the NEXT document
     (propal → order → shipment → invoice)? Does a hook on one card need a sibling
     on another? Does it need a trigger to react when the event actually fires?

   For **each** scenario decide: **Handle now / Defer (record in brain) / Out of
   scope (state why).** Never silently skip one.

**4. Choose the Dolibarr mechanism for each piece — consciously, with a reason.**

   | Need | Use | Not |
   |---|---|---|
   | Extend a page's UI / intercept a page action | **Hook** (context + method point) | a forked core page |
   | React to a business event (validate, pay, cancel…) | **Trigger** (action code) | polling / a hook in the wrong place |
   | A few extra attributes ON a standard object (order, product…) editable in its card | **Extrafield** | a custom table you have to join + render yourself |
   | Your own records / 1-to-many / cross-object state (rates, logs, mappings) | **Custom table** (+ entity col) | cramming JSON into one extrafield |
   | A setting / secret / toggle | **Config const** (`llx_const`) | hard-coding |
   | Scheduled / batch work | **Cron job** (descriptor `cronjobs`) | a hook that hopes someone loads a page |
   | Admin configuration UI | **Setup page** + consts | editing the DB by hand |

**5. Re-think — challenge your own plan before you touch code.** Ask out loud:
   - "What is the **'multiple boxes' of THIS task** — the obvious case I haven't listed?"
   - "**Why is each piece necessary?** Can the user's outcome be reached with less?"
   - "What breaks on the **unhappy path**, on **existing data**, on the **next document**?"
   Revise the scenario list until you can't find a new gap. If the design is
   non-trivial or has real trade-offs, surface the options to the user.

**6. Record it in the module brain, then build.** Write a Requirements-log entry
(`brain.sh` — see "The module brain"): the demand in the user's words, the persona/
flow, the mechanism decisions **and why**, the scenarios (handled / deferred / out
of scope), and the open questions. THEN implement, smallest correct increment first.

**Match the plan's length to the task — nothing unwanted, nothing unconsidered.**
The rule is NOT "always short"; it's **"every line earns its place."** A simple
change gets a few lines; a genuinely complex one can be as long as it needs to be
to stay clear — length is fine *when it's needed*. The scenario-enumeration above is
your *internal* thinking: don't dump all of it, but include whatever the user
actually needs to understand and decide. Cut padding, restating the obvious, and
jargon-for-its-own-sake — **never pad to look thorough, never truncate real
complexity to look brief, and never add anything you didn't think through.** Default
shape: plain prose/list of **what** you'll build, **which** Dolibarr mechanism, and
the **scenarios that matter**. Full detail lives in the brain. If a real decision or
trade-off needs their input, ask it plainly.

---

## Module descriptor anatomy (`core/modules/mod<Module>.class.php`)

The descriptor `extends DolibarrModules` and declares everything Dolibarr needs to
register the module. Key properties (mirror an existing one):
- `$this->numero` — unique module id; `$this->rights_class` — permission prefix;
  `$this->family`, `$this->module_position`, `$this->picto`.
- `$this->module_parts` — enable subsystems, e.g.
  `array('triggers' => 1, 'hooks' => array('data' => array('ordercard','propalcard'), 'entity' => '0'))`.
- `$this->const` — module config constants seeded on activation, each
  `array(NAME, type, default, description, visible, 'current'|'allentities', deleteonunactive)`.
- `$this->config_page_url = array('setup.php@<module>')` — the admin Setup link.
- `$this->langfiles = array('<module>@<module>')`, `$this->dirs`, `$this->phpmin`,
  `$this->need_dolibarr_version`, `$this->dictionaries`, `$this->cronjobs`,
  `$this->rights`, `$this->menu`.
- `init($options)` — runs on (re)activation: `$this->_load_tables('/<module>/sql/')`
  installs every `sql/*.sql`, then run any seeding, then `return $this->_init($sql, $options)`.

---

## Schema — two paths, and the live-DB caveat

**Path A — hand-written SQL (lightweight, common):** add `sql/llx_<table>.sql`
(plain `CREATE TABLE`) and let the descriptor `init()` install it via
`_load_tables('/<module>/sql/')`. For tables that must exist even mid-session,
add a self-healing `ensureSchema()` that `SHOW TABLES LIKE` checks then `CREATE
TABLE` once (guard with a `static $done`).

**Path B — `amb_*` structured tools:** `amb_add_object` (creates class + SQL +
card/list/menus), then `amb_add_field` / `amb_edit_field` / `amb_delete_field`
(each takes a `field` object: name, label, type required + optional visible,
enabled, position, notnull, index, default, arrayofkeyval, searchall, css…).
These rewrite the object class `$fields` array **and** `sql/llx_<table>.sql`.

**Live-DB caveat (BOTH paths):** editing the `.sql`/`$fields` only changes what a
**fresh install** gets. The live table is **NOT** auto-altered — it changes on
module **deactivate → reactivate** (or upgrade). After a schema change: read the
artifacts on disk to confirm, then verify the live column with
`dol-db.sh describe <table>`; if it hasn't changed, tell the user to
reactivate/upgrade the module (or apply the `ALTER` manually). Deleting a field
**drops data** — confirm first.

---

## Extrafields — extra attributes ON a standard object (no custom table)

When the need is "store a few more fields on an existing object" (an order, invoice,
product, thirdparty, shipment…), the Dolibarr-native answer is an **extrafield**,
not a new table. Extrafields are user-defined columns stored in
`llx_<element>_extrafields` (e.g. `llx_commande_extrafields`) and defined as
dictionary rows in `llx_extrafields`; core renders them automatically on the
object's card/list and includes them in search, with **zero custom UI**.

- **When to use vs a custom table:** extrafield = a handful of attributes that
  belong to ONE object instance and should appear on its card. Custom table = your
  own records, a 1-to-many relationship, or cross-object state (rate caches, logs,
  mappings). Don't stuff structured/repeating data into one extrafield — that's the
  signal you actually need a table (the multi-box packages are per-shipment repeating
  data → a JSON request field / table, not 4 extrafields).
- **Declare them** in the descriptor (so activation seeds them) or via the
  structured tool `amb_add_extrafields` (writes the definition); each has
  `name`, `label`, `type` (varchar/int/double/date/datetime/boolean/text/price/
  select/sellist/link/…), `size`, `pos`, `list`, `totalizable`, and for select/
  sellist an `param`/`arrayofkeyval`. Mirror an existing module's extrafield seeding.
- **Read** on a fetched object: `$object->array_options['options_<name>']` (call
  `$object->fetch_optionals()` if they aren't loaded).
- **Write:** set `$object->array_options['options_<name>'] = $val;` then
  `$object->insertExtraFields()` (create) / `$object->updateExtraField('<name>')`
  (update). In a card hook, the standard form posts `options_<name>` and core saves
  it for you — usually you only add an extrafield, no code.
- **Live-DB caveat applies** (same as schema): the column appears on
  reactivation/upgrade. Verify with `dol-db.sh describe <element>_extrafields`.

---

## Config & constants

Every module setting lives in `llx_const`. This is central — most code reads config.
- **Declare** defaults in the descriptor `$this->const` array (seeded on activation).
- **Read** anywhere with `getDolGlobalString('NAME')` / `getDolGlobalInt('NAME')` /
  `getDolGlobalBool('NAME')` — never `$conf->global->NAME` in new code.
- **Write** from an admin page or hook with
  `dolibarr_set_const($db, 'NAME', $value, 'chaine', 0, '', $conf->entity)`.
- Inspect live values: `dol-db.sh const '<MODULE>%'`.
- Keep secrets (API keys/tokens) in consts, **never hard-coded**.

## Entity / multi-company scoping (don't skip this)

Dolibarr is multi-company. Almost every custom table has an `entity` column and
every query must respect it, or rows leak across companies:
- **SELECT**: `WHERE entity IN (0, ".((int) $conf->entity).")` (0 = shared/all-entities).
- **INSERT**: write `entity = ".((int) $conf->entity)`.
- For core elements, use the helper: `WHERE entity IN (".getEntity('product').")`.
- In a hook context, restrict visibility to all entities with `'entity' => '0'` in
  the `module_parts['hooks']` registration.

---

## Hooks

How Dolibarr hooks work:
- A **hook handler class** `class/actions_<module>.class.php` `extends CommonHookActions`
  and implements methods named after **hook method points** (e.g. `doActions`,
  `addMoreActionsButtons`, `formObjectOptions`, `printCommonFooter`, `getNomUrl`,
  `printFieldListValue`…), each `($parameters, &$object, &$action, $hookmanager)`.
- The descriptor registers **hook contexts** in `module_parts['hooks']`. Two forms,
  both valid — prefer the **structured** form, which controls entity visibility:
  `'hooks' => array('data' => array('ordercard','propalcard','expeditioncard'), 'entity' => '0')`
  (the flat `array('ordercard', 'propalcard')` shorthand also works). A page only
  runs your handler if it called `initHooks(array('contextname'))` with a matching context.
- Core calls `$hookmanager->executeHooks('methodPoint', $parameters, $object, $action)`.
- Read the live context inside a method via `$parameters['currentcontext']`.

**Returning output / values from a method:**
- Return `0` to let other handlers and core continue.
- Append HTML to `$this->resprints` (printed by core where the hook fires).
- Set `$this->results` / `$this->errors` per the method's convention.
- To render a chunk of UI, use the **template pattern**: `ob_start(); include
  __DIR__.'/../tpl/<name>.tpl.php'; $this->resprints .= ob_get_clean();`. Keep
  presentation in `tpl/*.tpl.php`, logic in the handler.
- Inside an action branch use `GETPOST()/GETPOSTINT()` for input, `newToken()` for
  CSRF, `setEventMessages($msg, null, 'warnings'|'mesgs'|'errors')` for flash
  messages, and `header('Location: '.$_SERVER['PHP_SELF'].'?id='.$id); exit;` to redirect.

Discover the EXACT names from the code (do this, don't guess):
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh hooks            # contexts + method points (ranked)
bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh find ordercard   # where a context/method is used (file:line)
```
Then read the page that fires the context (e.g. `commande/card.php`) to see the
exact `initHooks(array(...))` context, which `executeHooks(...)` points it exposes,
and what `$object`/`$parameters` you get.

To add a hook: scaffold the handler (`amb_init_part` part `hook`, or hand-create
`actions_<module>.class.php` mirroring an existing one) → register the context(s)
in the descriptor `module_parts['hooks']` → implement the chosen method point(s) →
re-read on disk → load the page to confirm it fires.

---

## Triggers

How Dolibarr triggers work:
- A **trigger class** `core/triggers/interface_NN_mod<Module>_<Name>.class.php`
  `extends DolibarrTriggers` and implements
  `runTrigger($action, $object, User $user, Translate $langs, Conf $conf)`. `NN` is
  a load order (e.g. 50, 99). The loader derives the class as
  `"Interface".ucfirst(<Name>)` and qualifies the module via the `mod<Module>`
  segment — so **`mod<Module>` must contain NO underscores**.
- Core fires business events via `$object->call_trigger('ACTION_CODE', $user)`,
  e.g. `BILL_VALIDATE`, `ORDER_REOPEN`, `COMPANY_CREATE`. There are 350+ codes —
  **never guess; extract the real code from source.**
- `runTrigger` should `switch`/`in_array` on the codes you handle, act on
  `$object` (scope DB writes by `$conf->entity`), and return `0` (ignored/ok),
  `1` (handled), or `-1` (error, set `$this->errors`).

Discover the action code(s):
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh triggers              # all distinct codes
bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh triggers '' BILL      # filter, e.g. all invoice events
bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh find ORDER_REOPEN     # where it is fired (file:line)
```
Reading the firing site also tells you what `$object` is at trigger time.

To add a trigger: scaffold (`amb_init_part` part `trigger`, or hand-create the
`interface_NN_mod<Module>_*.class.php`) → implement the `switch ($action)` →
re-read on disk → fire the event in the app and check the log.

---

## Integrating an external API (REST / OAuth / carriers / payments)

A large share of real custom-module work is calling a third-party API. Build it
the Dolibarr way, in layers:

1. **Shared HTTP helper in `lib/<module>api.lib.php`.** First check for the native
   helper — `find-api getURLContent` (`core/lib/geturl.lib.php`) handles GET/POST
   with proxy/SSL config. If you need full control (custom verbs, raw body, fine
   error mapping), write a thin `curl` wrapper that:
   - reads timeouts from consts (`getDolGlobalInt('<MODULE>_API_TIMEOUT')`),
   - **logs via `dol_syslog()` with the `Authorization` header REDACTED**,
   - decodes JSON and **throws a typed exception** (`class FooApiException extends
     RuntimeException`) on curl error or HTTP ≥ 400, surfacing the API's error message.
2. **Secrets in consts**, read with `getDolGlobalString()`, set from the setup page
   with `dolibarr_set_const()`. Never hard-code keys.
3. **OAuth tokens — cache and self-heal.** Cache the token in `$_SESSION` and
   **bind the cache key to the environment** (sandbox-vs-live base URL + a hash of
   the API key): env-specific JWTs reused after a toggle yield `HTTP 401 Invalid
   ... JWT`. Refresh ~60s before `expires_in`. On a `401`, clear the cached token
   and **retry once** with a fresh one (`dol_syslog(..., LOG_WARNING)` the retry).
4. **Multiple providers → abstract base + factory.** An `abstract class Foo extends
   CommonObject` defines the contract (`abstract public function rate(...)`); each
   provider subclass implements it; a `FooFactory::create($db, $type)` returns the
   right one via `match`. Auto-discover per-provider assets (e.g. a logo by
   `img/<type>.svg`) so adding a provider is just a new subclass + file.
5. **Errors are user-visible.** Catch the typed exception at the boundary, push to
   `$this->errors`/`setEventMessages`, and degrade gracefully (return `array()`/`-1`).

---

## Admin / setup pages (`admin/setup.php`, `admin/setup_<provider>.php`)

Standard structure (mirror an existing one):
- Bootstrap by locating `main.inc.php` upward
  (`$res = @include '../../../main.inc.php'; ... die('Cannot find main.inc.php')`).
- `require_once DOL_DOCUMENT_ROOT.'/core/lib/admin.lib.php'` and gate with
  `if (!$user->admin) accessforbidden();`. Load langs with `$langs->loadLangs(...)`.
- On save: read with `GETPOST/GETPOSTINT`, persist with `dolibarr_set_const()`,
  `setEventMessages('Saved', null, 'mesgs')`, then `header('Location: '.$_SERVER['PHP_SELF']); exit;`.
- Render between `llxHeader()` / `llxFooter()`; title via `load_fiche_titre()`;
  every form needs `<input type="hidden" name="token" value="'.newToken().'">`;
  escape output with `dol_escape_htmltag()`.
- `config_page_url` points to the main page; link out to per-provider
  `setup_<ref>.php` pages for provider-specific config.

---

## Writing logic — Dolibarr-native FIRST, invent only as a last resort

Whenever you write business logic (a hook body, a trigger, a page action, a helper,
SQL), do NOT write from scratch first. **Reuse-first is mandatory:**

0. **Scan & record what's already written** — inventory the module's own functions
   before adding one: `bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh funcs <module>`.
   If a function (or one close enough) already exists, **call it, or copy/modify it**
   — don't write a second near-duplicate. Record in your report which existing
   function you reused or extended.
1. **SEARCH** the whole codebase for a core/module API that already does it:
   `bash ${CLAUDE_SKILL_DIR}/scripts/scan-code.sh find-api <function_or_class>`
   (definition + real usages). Grep for a similar feature and read one that matches.
2. **Reuse the core helpers** instead of reinventing — the common ones:
   `GETPOST()/GETPOSTINT()` (input), `price()/price2num()` (money),
   `dol_now()/dol_print_date()` (time), `getDolGlobalString()/getDolGlobalInt()`
   and `dolibarr_set_const()` (config), `$db->query()/fetch_object()/escape()/idate()`
   and `MAIN_DB_PREFIX` (DB), `getEntity()` (multi-company), `dol_syslog()` (logs),
   `newToken()` (CSRF), `setEventMessages()` (flash), `dol_buildpath()`/`dol_escape_htmltag()`,
   `CommonObject::fetch()` (base class).
3. **WRITE it the way working Dolibarr code writes it** — same class patterns,
   naming, return conventions, escaping idioms. Mirror a concrete example you found.
4. **ONLY if nothing comparable exists**, write from your own knowledge — and say
   explicitly that no native pattern was found, so the user knows it's bespoke.

---

## Security — non-negotiable checklist

Every piece of code that touches input, output, the DB, or a privileged action
must pass these. Mirror how core does it; never hand-roll around it.

- **Input — never trust superglobals.** Use `GETPOST($key, $filter)` /
  `GETPOSTINT($key)`, never `$_GET`/`$_POST`/`$_REQUEST` directly. Pick the right
  filter: `'int'`, `'alpha'`, `'aZ09'`, `'alphanohtml'`, `'restricthtml'` (allow
  safe HTML), `'nohtml'`, `'array'`. Default to the strictest that works.
- **SQL — no injection.** `(int)`/`(float)`-cast every numeric, wrap every string in
  `$db->escape()` (or `$db->sanitize()` for identifiers), prefix tables with
  `MAIN_DB_PREFIX`, and scope by `entity`. Never concatenate a raw GETPOST/superglobal
  into a query.
- **Output — no XSS.** Escape anything dynamic before printing:
  `dol_escape_htmltag()` (HTML attrs/text), `dol_htmlentities()`,
  `dol_string_nohtmltag()`. Don't echo request data raw.
- **CSRF — every POST form / state-changing action** carries
  `<input type="hidden" name="token" value="'.newToken().'">`; Dolibarr validates it
  (`MAIN_SECURITY_CSRF_WITH_TOKEN`). Append `&token='.newToken()` on action links too.
- **Access control — gate every page/action.** `if (!$user->admin) accessforbidden();`
  for admin pages; `$user->hasRight('module','level','crud')` (or `restrictedArea($user,
  'module', $id, 'table')`) before reading/mutating an object the user may not own.
- **Files / external calls.** Sanitize filenames with `dol_sanitizeFileName()`,
  restrict `modulepart` in `document.php` links, keep `CURLOPT_SSL_VERIFYPEER` ON,
  and never log secrets (redact `Authorization`/keys in `dol_syslog`). No
  `eval`/`exec`/`system`/`shell_exec` on anything user-influenced.

**Scan before confirming:**
```bash
bash ${CLAUDE_SKILL_DIR}/scripts/audit.sh security <module>
```
It flags raw superglobals, unsafe SQL/output, missing CSRF tokens, ungated admin
pages, and dangerous sinks. Hits are advisory — review and fix or justify each.

## Dev / verify / debug loop — "I edited files, how do I see it work?"

- **PHP & templates are live immediately** — just refresh the page. No build step.
- **Schema, descriptor `const`/`menu`/`permission`, and `module_parts` changes need
  a module deactivate → reactivate** (Home > Setup > Modules) to apply to the live
  DB. Verify with `dol-db.sh describe <table>` / `dol-db.sh const '<MODULE>%'`.
- **Caches:** if a CSS/menu/translation change doesn't show, force-refresh with
  `?dol_resetcache=1`, or bump `MAIN_IHM_PARAMS_REV` per-entity (custom theme
  `style.css.php` carries `&revision=<that const>`; `MAIN_OPTIMIZE_SPEED` does
  **not** cache CSS).
- **Logs are your debugger.** `dol_syslog($msg, LOG_DEBUG|LOG_WARNING|LOG_ERR)`
  writes to the syslog file. Use the helper:
  ```bash
  bash ${CLAUDE_SKILL_DIR}/scripts/dol-log.sh path                  # resolved path + level (warns if too low)
  bash ${CLAUDE_SKILL_DIR}/scripts/dol-log.sh follow DeliveryFedex  # live-tail, filtered
  bash ${CLAUDE_SKILL_DIR}/scripts/dol-log.sh grep "HTTP 401" 50000 # search recent lines
  ```
  ⚠️ **Level gotcha:** if `SYSLOG_LEVEL < 7`, your `LOG_DEBUG` lines are **never
  written**. To see API/debug traces, raise the level to 7 (Setup > Modules >
  Logs). The log file can be **gigabytes** — always tail/grep, never `cat`.
- **Verify behavior, not just files.** After a hook/trigger/API change, actually
  load the page that fires the context (or fire the event) and confirm in the UI +
  the log — re-reading the file on disk only proves you wrote it, not that it runs.

---

## Destructive operations — confirm with the user FIRST

`amb_delete_module`, `amb_delete_object`, `amb_delete_field`, `amb_drop_table`,
`amb_delete_dictionary`, `amb_delete_permission`, `amb_delete_menu`,
`amb_delete_file`, and any hand-written `DROP`/`DELETE`/`ALTER ... DROP`. Deleting a
field or table **drops live data**. Use `amb_save_file` for edits the structured
tools can't express (it keeps a `.back` copy).

---

## The module brain — record every module's intent, decisions & satisfaction

Each module gets its own persistent memory at
`htdocs/custom/<module>/.dolibarr-dev/BRAIN.md`, managed by `brain.sh`. It exists
so that **a later session never has to guess what this module was for or why it
was built this way** — and so a deliberately-considered scenario isn't quietly
undone by a future change. Two distinct memories, don't confuse them:
- **`BRAIN.md` (per module, lives with the code)** — *intent*: what users
  demanded, why each decision was made, which scenarios were handled/deferred,
  whether the user was satisfied, what's still open.
- **`LEARNINGS.md` (global to the skill)** — *reusable facts*: Dolibarr
  conventions, API names, pitfalls that apply across all modules.

**Workflow (already wired into the steps above):**
1. **Read at Step 0** — `brain.sh show <module>`. If present, it's your starting
   context (the requirement history + decisions). If absent, `brain.sh init
   <module>` and reconstruct purpose from code + `git log`, then ask the user to
   confirm intent. Always verify a brain claim against the live code before acting.
2. **Write at plan time** (PLAN step 6) — add a Requirements-log entry: the demand
   in the user's words, persona/flow, mechanism decisions **and why**, scenarios
   (handled / deferred / out of scope), files, status, open questions.
3. **Update before confirming** — set the entry's **Status** (built → verified →
   user-confirmed-satisfied), move any newly-discovered scenario into "Known gaps",
   and record what you tested.

**Satisfaction is part of the record.** "Built" ≠ "the user is happy." When the
user confirms it does what they wanted, mark `user-confirmed-satisfied`; if they
ask for a change, that's a NEW dated entry, not an edit that erases the history —
the trail is what stops a future session from re-litigating settled choices.

If you find **no brain and no recoverable source** for a module, don't stall:
think from the code with this skill, build, and **start the brain** so the next
session is better off than you were.

## Keep this skill improving (self-build)

This skill is meant to get better with use:
- At the START you already read `LEARNINGS.md` (Step 0). Apply those lessons.
- At the END, if you learned something reusable — a Dolibarr convention, a
  non-obvious API, a pitfall, a corrected assumption, a confirmed trigger/hook
  name/API endpoint — append ONE concise dated bullet:
  ```bash
  printf -- '- %s — %s\n' "$(date +%F)" "your one-line lesson" >> ${CLAUDE_SKILL_DIR}/LEARNINGS.md
  ```
  Only record VERIFIED, reusable facts; dedupe first; keep it to one or two lines.
  If a lesson contradicts an instruction in THIS file, fix the SKILL.md body directly.

## Before you confirm "done" — prove it (no dead code, test the flow)

Do NOT tell the user it's finished until ALL of these pass. The bar: **every
function and file you wrote is wired up and exercised — not a single unused piece
remains.**

1. **No dead code.** Run `bash ${CLAUDE_SKILL_DIR}/scripts/audit.sh deadcode <module>`
   and `audit.sh files <module>`. For every `[UNUSED?]` function and unexpected
   unreferenced file: either **wire it into a caller** or **delete it**. The only
   acceptable "uncalled" items are the documented core-dispatch ones (hook method
   points, `runTrigger`, REST methods, descriptor/trigger files loaded by
   convention) — confirm each is actually reached, don't assume.
2. **Security clean.** `audit.sh security <module>` — every hit fixed or justified.
3. **Behavior tested, not just written.** Exercise the real business step the code
   hooks into and confirm the effect:
   - Drive the flow with the `mcp__dolibarr_expert` tools that match the role
     (`create_proposal`/`convert_proposal_to_order`/`validate_order`/
     `convert_order_to_invoice`/`validate_invoice`/`add_payment_to_invoice`,
     `update_product_stock`, …), or load the page that fires the hook/trigger.
   - Watch it happen: `bash ${CLAUDE_SKILL_DIR}/scripts/dol-log.sh follow <module>`
     (raise `SYSLOG_LEVEL` to 7 first) and check the DB result with `dol-db.sh`.
   - Confirm the schema actually applied (reactivate the module if needed) before
     claiming a field/table works.
4. Report what you tested and the observed result — not "this should work."
5. **Update the module brain.** Set the Requirements-log entry's Status
   (built → verified → user-confirmed-satisfied), move any scenario you found-but-
   deferred into "Known gaps", and note what you tested. The brain must reflect
   reality before you call it done.

## Output

State the plan briefly, make the edits/calls in order, then report: file paths
created/modified (relative to `htdocs/custom/<module>`); each schema/config/section
change; the hook contexts / trigger codes / API endpoints you used (with where you
found them); **which existing functions you reused or extended**; whether a
reactivation is needed to apply schema changes; the **security-scan result**; the
**dead-code/files result** (and that nothing unused remains); **how you tested
the behavior** (the flow you drove + the observed result, not "should work"); and
that the **module brain is updated** (requirement, decisions, scenarios, status).
Be concrete, no fluff.
