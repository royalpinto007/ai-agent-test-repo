<?php
/**
 * AJAX endpoint — approve, create_invoice, pay.
 *
 * All POSTs to this file are JSON; all responses are JSON.
 * Per-order context (eBay lines, payout metadata) is read from $_SESSION,
 * stashed by reconcile.php on the most recent run.
 */

$res = 0;
if (!$res && file_exists("../main.inc.php"))       $res = @include "../main.inc.php";
if (!$res && file_exists("../../main.inc.php"))    $res = @include "../../main.inc.php";
if (!$res && file_exists("../../../main.inc.php")) $res = @include "../../../main.inc.php";
if (!$res) die("Include of main fails");

require_once DOL_DOCUMENT_ROOT.'/compta/facture/class/facture.class.php';
require_once DOL_DOCUMENT_ROOT.'/compta/paiement/class/paiement.class.php';
require_once DOL_DOCUMENT_ROOT.'/societe/class/societe.class.php';
require_once DOL_DOCUMENT_ROOT.'/custom/ebayreconcile/class/EbayReconciler.class.php';

global $db, $user, $conf, $langs;
$langs->loadLangs(array('ebayreconcile@ebayreconcile', 'errors'));

header('Content-Type: application/json');

if (empty($user->rights->ebayreconcile->use)) jsonError("Not authorized (need ebayreconcile.use)");
if (empty($user->rights->ebayreconcile->write)) jsonError("Not authorized to write (need ebayreconcile.write)");

$action = GETPOST('action', 'aZ09');
$rawBody = file_get_contents('php://input');
$body = json_decode($rawBody, true);
if (!is_array($body)) $body = array();

$lastRun  = isset($_SESSION['ebayreconcile_lastrun']) ? $_SESSION['ebayreconcile_lastrun'] : null;
$resultByOrder = array();
if ($lastRun && !empty($lastRun['results'])) {
    foreach ($lastRun['results'] as $r) $resultByOrder[$r['order_number']] = $r;
}

try {
    switch ($action) {
        case 'search_customer': echo json_encode(doSearchCustomer($body)); exit;
        case 'approve':         echo json_encode(doApprove($body, $resultByOrder)); exit;
        case 'create_invoice':  echo json_encode(doCreateInvoice($body, $resultByOrder)); exit;
        case 'pay':             echo json_encode(doPay($body, $resultByOrder)); exit;
        case 'save_payout':     echo json_encode(doSavePayout($body)); exit;
        case 'save_draft':      echo json_encode(doSaveDraft($body)); exit;
        case 'delete_draft':    echo json_encode(doDeleteDraft($body)); exit;
        case 'save_note':       echo json_encode(doSaveNote($body)); exit;
        default:
            jsonError("Unknown action: ".$action);
    }
} catch (Exception $e) {
    jsonError($e->getMessage());
}

// ---------------------------------------------------------------------------

function jsonError($msg, $code = 400)
{
    http_response_code($code);
    echo json_encode(array('ok' => false, 'error' => $msg));
    exit;
}

function customerPayload($socid)
{
    global $db;

    $socid = (int) $socid;
    if ($socid <= 0) return null;

    $soc = new Societe($db);
    if ($soc->fetch($socid) <= 0) return null;

    return array(
        'id' => (int) $soc->id,
        'name' => $soc->name,
        'code_client' => $soc->code_client,
        'email' => $soc->email,
        'label' => $soc->name.' (#'.((int) $soc->id).')',
    );
}

/**
 * Find all live invoices/credit notes for an eBay order, including return/RMA
 * credit notes linked to the source invoice instead of carrying ref_client.
 */
function findOrderInvoicesAndCreditNotes($orderNumber)
{
    global $db;

    $docs = array();
    $seen = array();
    $sourceInvoiceIds = array();

    $addDoc = function($obj) use (&$docs, &$seen, &$sourceInvoiceIds, $db) {
        $rowid = (int) $obj->rowid;
        if ($rowid <= 0 || !empty($seen[$rowid])) return;
        $seen[$rowid] = true;

        if ((int) $obj->type === Facture::TYPE_STANDARD) $sourceInvoiceIds[] = $rowid;

        $f = new Facture($db);
        if ($f->fetch($rowid) <= 0) return;

        $remain = (float) (method_exists($f, 'getRemainToPay') ? $f->getRemainToPay() : ($f->total_ttc - $f->getSommePaiement()));
        $docs[] = array(
            'id' => $rowid,
            'ref' => $obj->ref,
            'type' => (int) $obj->type,
            'total_ht' => (float) $obj->total_ht,
            'total_ttc' => (float) $obj->total_ttc,
            'fk_statut' => (int) $obj->fk_statut,
            'paye' => (int) $f->paye,
            'remain_to_pay' => round($remain, 2),
            'source_invoice_id' => !empty($obj->fk_facture_source) ? (int) $obj->fk_facture_source : 0,
        );
    };

    $sql = "SELECT rowid, ref, type, total_ht, total_ttc, fk_statut, fk_facture_source FROM ".MAIN_DB_PREFIX."facture";
    $sql .= " WHERE ref_client = '".$db->escape($orderNumber)."'";
    $sql .= " AND entity IN (".getEntity('facture').")";
    $sql .= " AND type IN (0, 2)";
    // Only validated/closed documents are considered live for reconciliation.
    // Draft invoices/credit notes are unfinished and must not be reused, paid,
    // or counted as already solving a payout row.
    $sql .= " AND fk_statut > 0";
    $sql .= " AND fk_statut <> ".((int) Facture::STATUS_ABANDONED);
    $sql .= " ORDER BY rowid";
    $res = $db->query($sql);
    if (!$res) throw new Exception("Query failed: ".$db->lasterror());
    while ($obj = $db->fetch_object($res)) $addDoc($obj);

    $sourceInvoiceIds = array_values(array_unique(array_filter(array_map('intval', $sourceInvoiceIds))));
    if (!empty($sourceInvoiceIds)) {
        $sql = "SELECT rowid, ref, type, total_ht, total_ttc, fk_statut, fk_facture_source FROM ".MAIN_DB_PREFIX."facture";
        $sql .= " WHERE fk_facture_source IN (".implode(',', $sourceInvoiceIds).")";
        $sql .= " AND entity IN (".getEntity('facture').")";
        $sql .= " AND type = ".((int) Facture::TYPE_CREDIT_NOTE);
        $sql .= " AND fk_statut > 0";
        $sql .= " AND fk_statut <> ".((int) Facture::STATUS_ABANDONED);
        $sql .= " ORDER BY rowid";
        $res = $db->query($sql);
        if (!$res) throw new Exception("Query failed: ".$db->lasterror());
        while ($obj = $db->fetch_object($res)) $addDoc($obj);
    }

    return $docs;
}

function doSearchCustomer($body)
{
    global $db, $conf;

    $q = isset($body['q']) ? trim((string) $body['q']) : '';
    $currentSocid = isset($body['currentSocid']) ? (int) $body['currentSocid'] : 0;
    $out = array();
    $seen = array();

    $addCustomer = function ($socid) use (&$out, &$seen, $currentSocid) {
        $payload = customerPayload($socid);
        if (!$payload || isset($seen[$payload['id']])) return;
        $payload['selected'] = ((int) $payload['id'] === (int) $currentSocid);
        $seen[$payload['id']] = true;
        $out[] = $payload;
    };

    if ($currentSocid > 0) $addCustomer($currentSocid);
    if (!empty($conf->global->EBAYRECONCILE_DEFAULT_SOCID)) $addCustomer((int) $conf->global->EBAYRECONCILE_DEFAULT_SOCID);

    if (strlen($q) < 2) {
        if (count($out) < 12) {
            $sqlDefault = "SELECT rowid FROM ".MAIN_DB_PREFIX."societe";
            $sqlDefault .= " WHERE entity IN (".getEntity('societe').")";
            $sqlDefault .= " AND status = 1";
            $sqlDefault .= " AND client IN (1, 3)";
            $sqlDefault .= " ORDER BY nom ASC";
            $sqlDefault .= $db->plimit(12);
            $resDefault = $db->query($sqlDefault);
            if ($resDefault) {
                while (($obj = $db->fetch_object($resDefault)) && count($out) < 12) {
                    $addCustomer((int) $obj->rowid);
                }
            }
        }
        return array('ok' => true, 'customers' => $out);
    }

    $like = '%'.$db->escape($q).'%';
    $sql = "SELECT rowid, nom, name_alias, code_client, email";
    $sql .= " FROM ".MAIN_DB_PREFIX."societe";
    $sql .= " WHERE entity IN (".getEntity('societe').")";
    $sql .= " AND status = 1";
    $sql .= " AND client IN (1, 3)";
    $sql .= " AND (nom LIKE '".$like."' OR name_alias LIKE '".$like."' OR code_client LIKE '".$like."' OR email LIKE '".$like."' OR rowid = ".((int) $q).")";
    $sql .= " ORDER BY nom ASC";
    $sql .= $db->plimit(12);
    $res = $db->query($sql);
    if (!$res) throw new Exception('Customer search failed: '.$db->lasterror());
    while ($obj = $db->fetch_object($res)) {
        $label = $obj->nom.' (#'.((int) $obj->rowid).')';
        if (!empty($obj->code_client)) $label .= ' - '.$obj->code_client;
        if (isset($seen[(int) $obj->rowid])) continue;
        $seen[(int) $obj->rowid] = true;
        $out[] = array(
            'id' => (int) $obj->rowid,
            'name' => $obj->nom,
            'code_client' => $obj->code_client,
            'email' => $obj->email,
            'label' => $label,
            'selected' => ((int) $obj->rowid === (int) $currentSocid),
        );
    }
    return array('ok' => true, 'customers' => $out);
}

/**
 * Approve a MISMATCH row.
 * Body: { orderNumber, parentInvoiceId, amount, action: 'credit_note'|'invoice' }
 *
 * For credit_note: create CN draft → validate → mark as available → apply to source invoice.
 * For invoice:    create invoice draft → validate (NO link to a source).
 */
function doApprove($body, $resultByOrder)
{
    global $db, $user, $conf;

    $orderNumber     = isset($body['orderNumber']) ? $body['orderNumber'] : '';
    $parentInvoiceId = isset($body['parentInvoiceId']) ? (int) $body['parentInvoiceId'] : 0;
    $amount          = isset($body['amount']) ? (float) $body['amount'] : 0.0;
    $kind            = isset($body['action']) ? $body['action'] : 'credit_note';
    $userNote        = isset($body['note']) ? trim((string) $body['note']) : '';
    if (!$orderNumber)     throw new Exception('orderNumber is required');
    if (!$parentInvoiceId) throw new Exception('parentInvoiceId is required');
    if ($amount <= 0)      throw new Exception('amount must be positive');
    if ($kind !== 'credit_note' && $kind !== 'invoice') throw new Exception("Bad action: $kind");

    $parent = new Facture($db);
    if ($parent->fetch($parentInvoiceId) <= 0) throw new Exception("Parent invoice $parentInvoiceId not found");
    if ((int) $parent->statut <= 0 || (int) $parent->statut === (int) Facture::STATUS_ABANDONED) {
        throw new Exception("Parent invoice ".$parent->ref." is not validated; draft/abandoned invoices cannot be used for eBay reconciliation adjustments.");
    }

    // Idempotency guard (same rationale as doCreateInvoice): if a document for
    // this eBay order with the same amount/type already exists, reuse it rather
    // than minting a duplicate on a repeated approve. Safe here because this path
    // creates standalone CNs (no discount application - see note below).
    $wantType = ($kind === 'credit_note') ? Facture::TYPE_CREDIT_NOTE : Facture::TYPE_STANDARD;
    $expectedAbs = round(abs($amount), 2);
    $dupSql = "SELECT rowid, ref, total_ht, fk_statut, fk_facture_source FROM ".MAIN_DB_PREFIX."facture";
    if ($wantType === Facture::TYPE_CREDIT_NOTE) {
        $dupSql .= " WHERE (ref_client = '".$db->escape($orderNumber)."'";
        $dupSql .= " OR fk_facture_source = ".((int) $parentInvoiceId).")";
    } else {
        $dupSql .= " WHERE ref_client = '".$db->escape($orderNumber)."'";
    }
    $dupSql .= " AND entity IN (".getEntity('facture').")";
    $dupSql .= " AND type = ".((int) $wantType);
    $dupSql .= " AND fk_statut > 0";
    $dupSql .= " AND fk_statut <> ".((int) Facture::STATUS_ABANDONED);
    $dupRes = $db->query($dupSql);
    if ($dupRes) {
        while ($dup = $db->fetch_object($dupRes)) {
            if (abs(abs((float) $dup->total_ht) - $expectedAbs) <= 0.01) {
                return array(
                    'ok'              => true,
                    'action'          => $kind,
                    'reused'          => true,
                    'newInvoiceId'    => (string) $dup->rowid,
                    'newInvoiceRef'   => $dup->ref,
                    'validated'       => ((int) $dup->fk_statut) > 0,
                    'applied'         => false,
                    'parent'          => array('id' => (int) $parent->id, 'ref' => $parent->ref, 'socid' => (int) $parent->socid),
                    'orderNumber'     => $orderNumber,
                    'amount'          => $amount,
                    'status'          => 'reused',
                    'dolibarrEditUrl' => DOL_URL_ROOT.'/compta/facture/card.php?id='.(int) $dup->rowid,
                    'message'         => "Reused existing ".($kind === 'credit_note' ? 'credit note' : 'invoice')." ".$dup->ref." for ".number_format($expectedAbs, 2)." (no duplicate created).",
                );
            }
        }
    }

    // Build draft
    $cn = new Facture($db);
    $cn->socid              = $parent->socid;
    $cn->type               = ($kind === 'credit_note') ? Facture::TYPE_CREDIT_NOTE : Facture::TYPE_STANDARD;
    $cn->ref_client         = $orderNumber;
    $cn->date               = dol_now();
    $cn->note_private       = "Auto-created via eBay reconciliation. eBay order: $orderNumber. Source invoice: ".$parent->ref." (id $parentInvoiceId).";
    if ($userNote !== '') $cn->note_private .= "\nUser note: ".$userNote;
    if ($kind === 'credit_note') $cn->fk_facture_source = $parentInvoiceId;

    $cn->lines = array();
    $cn->lines[] = makeLine("eBay reconciliation - $orderNumber", 1, $amount);

    $newId = $cn->create($user);
    if ($newId <= 0) throw new Exception('Create failed: '.$cn->error);

    if ($cn->validate($user) <= 0) throw new Exception('Validate failed: '.$cn->error);

    // Re-fetch the validated CN — its in-memory state after validate() is unreliable
    // across Dolibarr versions (some fields get reset).
    $cn = new Facture($db);
    if ($cn->fetch($newId) <= 0) throw new Exception('Refetch after validate failed');

    // NOTE: We deliberately do NOT apply the CN as a discount via Dolibarr's
    // discount mechanism (DiscountAbsolute::link_to_invoice). The reconciler
    // sums BOTH invoices and CNs by ref_client, so a standalone CN already
    // makes the math work without touching the source invoice's total_ht.
    // This also sidesteps the foreign-key constraint on
    // llx_societe_remise_except when the parent invoice's socid is stale.

    return array(
        'ok'              => true,
        'action'          => $kind,
        'newInvoiceId'    => (string) $newId,
        'newInvoiceRef'   => $cn->ref,
        'validated'       => true,
        'applied'         => false,
        'parent'          => array('id' => (int) $parent->id, 'ref' => $parent->ref, 'socid' => (int) $parent->socid),
        'orderNumber'     => $orderNumber,
        'amount'          => $amount,
        'status'          => 'validated',
        'dolibarrEditUrl' => DOL_URL_ROOT.'/compta/facture/card.php?id='.(int)$newId,
        'message'         => $kind === 'credit_note'
            ? "Created and validated credit note ".$cn->ref." for ".number_format($amount, 2).". Sums with ".$parent->ref." in the reconciler."
            : "Created and validated invoice ".$cn->ref." for ".number_format($amount, 2).".",
    );
}

/**
 * Create the missing invoice for MISSING / NO_LINKED_INVOICES rows.
 * Body: { orderNumber, parentSoId?, defaultSocid?, lines: [{date, type, net, description}] }
 *
 * If parentSoId given → invoice gets origin_type='commande' linked to that SO.
 * Else → invoice goes under defaultSocid (or EBAYRECONCILE_DEFAULT_SOCID).
 */
function doCreateInvoice($body, $resultByOrder)
{
    global $db, $user, $conf;

    $orderNumber = isset($body['orderNumber']) ? $body['orderNumber'] : '';
    $parentSoId  = isset($body['parentSoId']) ? (int) $body['parentSoId'] : 0;
    $lines       = isset($body['lines']) ? $body['lines'] : array();
    $userNote    = isset($body['note']) ? trim((string) $body['note']) : '';
    // Refund-type rows create a credit note (positive amount), not a negative
    // invoice. Everything else stays a standard invoice.
    $kind        = (isset($body['action']) && $body['action'] === 'credit_note') ? 'credit_note' : 'invoice';
    $isCN        = ($kind === 'credit_note');
    if (!$orderNumber) throw new Exception('orderNumber is required');
    if (empty($lines) || !is_array($lines)) {
        // Fallback: pull from session lastRun
        if (isset($resultByOrder[$orderNumber]['ebay_lines'])) {
            $lines = $resultByOrder[$orderNumber]['ebay_lines'];
        }
    }
    if (empty($lines)) throw new Exception('No lines provided and none in session for '.$orderNumber);

    $socid = 0;
    $parentSoRef = null;
    if ($parentSoId > 0) {
        require_once DOL_DOCUMENT_ROOT.'/commande/class/commande.class.php';
        $so = new Commande($db);
        if ($so->fetch($parentSoId) <= 0) throw new Exception('Parent SO fetch failed: '.$so->error);
        $socid = (int) $so->socid;
        $parentSoRef = $so->ref;
    } else {
        $socid = isset($body['defaultSocid']) ? (int) $body['defaultSocid'] : 0;
        if (!$socid) $socid = (int) $conf->global->EBAYRECONCILE_DEFAULT_SOCID;
    }
    if (!$socid) throw new Exception('No customer (socid) available for this order');
    $thirdparty = new Societe($db);
    if ($thirdparty->fetch($socid) <= 0) {
        throw new Exception('Default customer socid '.$socid.' was not found');
    }

    $docWord = $isCN ? 'credit note' : 'invoice';

    // Idempotency guard: if a document for this eBay order with the same amount
    // already exists (e.g. auto-created on an earlier reconcile run, or a real
    // invoice already in Dolibarr), reuse it instead of minting a second one.
    // Without this, re-running "Create documents" piles up duplicate UNPAID
    // invoices that the report then has to collapse out. We match on
    // ref_client + type + |total_ht|, ignoring drafts/cancelled docs.
    $expectedAbs = 0.0;
    foreach ($lines as $l) { $expectedAbs += (float) ($l['net'] ?? 0); }
    $expectedAbs = round(abs($expectedAbs), 2);
    $wantType = $isCN ? Facture::TYPE_CREDIT_NOTE : Facture::TYPE_STANDARD;
    $dupSql = "SELECT rowid, ref, total_ht, fk_statut FROM ".MAIN_DB_PREFIX."facture";
    $dupSql .= " WHERE ref_client = '".$db->escape($orderNumber)."'";
    $dupSql .= " AND entity IN (".getEntity('facture').")";
    $dupSql .= " AND type = ".((int) $wantType);
    $dupSql .= " AND fk_statut > 0";
    $dupSql .= " AND fk_statut <> ".((int) Facture::STATUS_ABANDONED);
    $dupRes = $db->query($dupSql);
    if ($dupRes) {
        while ($dup = $db->fetch_object($dupRes)) {
            if (abs(abs((float) $dup->total_ht) - $expectedAbs) <= 0.01) {
                return array(
                    'ok'              => true,
                    'action'          => $kind,
                    'mode'            => 'reused',
                    'reused'          => true,
                    'orderNumber'     => $orderNumber,
                    'newInvoiceId'    => (string) $dup->rowid,
                    'newInvoiceRef'   => $dup->ref,
                    'totalHt'         => (float) $dup->total_ht,
                    'socid'           => (string) $socid,
                    'validated'       => ((int) $dup->fk_statut) > 0,
                    'dolibarrEditUrl' => DOL_URL_ROOT.'/compta/facture/card.php?id='.(int) $dup->rowid,
                    'message'         => "Reused existing $docWord ".$dup->ref." for ".number_format($expectedAbs, 2)." (no duplicate created).",
                );
            }
        }
    }

    $inv = new Facture($db);
    $inv->socid           = $socid;
    $inv->type            = $isCN ? Facture::TYPE_CREDIT_NOTE : Facture::TYPE_STANDARD;
    $inv->ref_client      = $orderNumber;
    $inv->date            = dol_now();
    $inv->note_private    = "Auto-created via eBay reconciliation ($docWord). eBay order: $orderNumber.".($parentSoRef ? " Linked to SO $parentSoRef (id $parentSoId)." : ' No SO existed; using default eBay customer.');
    if ($userNote !== '') $inv->note_private .= "\nUser note: ".$userNote;
    // Only standard invoices carry the SO origin link; a standalone credit note
    // is issued to eBay without being applied to a source invoice.
    if ($parentSoId > 0 && !$isCN) {
        $inv->origin       = 'commande';
        $inv->origin_id    = $parentSoId;
    }
    // Tie-out rule: the created document's total_ht must equal the net of the lines
    // it covers — even when lines offset each other (e.g. a +6 / -6 pair).
    $inv->lines = array();
    if ($isCN) {
        // Dolibarr stores each credit-note line as -abs(subprice), so itemising
        // offsetting lines would INFLATE the total: a (+6, -6, -74.95) bucket would
        // post as -(6+6+74.95) = -86.95 instead of -74.95. To guarantee the credit
        // note ties out to the net, post a SINGLE line equal to the net magnitude;
        // the per-line breakdown is preserved in the description and the reconcile UI.
        $netSum = 0.0;
        $parts  = array();
        foreach ($lines as $l) {
            $netSum  += (float) ($l['net'] ?? 0);
            $parts[]  = trim(($l['type'] ?? 'eBay').' '.number_format((float) ($l['net'] ?? 0), 2));
        }
        $netSum = round($netSum, 2);
        $desc = 'eBay reconciliation - '.$orderNumber;
        if (count($parts) > 1) $desc .= ' (net of: '.implode('; ', $parts).')';
        $inv->lines[] = makeLine($desc, 1, abs($netSum));
    } else {
        // Standard invoice: total_ht is the signed sum of the lines, so offsetting
        // lines cancel correctly. Keep one line per CSV row for full itemisation.
        foreach ($lines as $l) {
            $desc = '['.($l['type'] ?? 'eBay').'] '.($l['description'] ?? '').' ('.($l['date'] ?? '').')';
            $desc = trim(preg_replace('/\s+\(\)/', '', $desc));
            $inv->lines[] = makeLine($desc, 1, (float) ($l['net'] ?? 0));
        }
    }

    $newId = $inv->create($user);
    if ($newId <= 0) throw new Exception('Create failed: '.$inv->error);
    if ($inv->validate($user) <= 0) throw new Exception('Validate failed: '.$inv->error);

    return array(
        'ok'              => true,
        'action'          => $kind,
        'mode'            => $parentSoId ? 'from_so' : 'standalone',
        'orderNumber'     => $orderNumber,
        'newInvoiceId'    => (string) $newId,
        'newInvoiceRef'   => $inv->ref,
        'totalHt'         => (float) $inv->total_ht,
        'socid'           => (string) $socid,
        'so'              => $parentSoId ? array('id' => $parentSoId, 'ref' => $parentSoRef, 'socid' => $socid) : null,
        'validated'       => true,
        'dolibarrEditUrl' => DOL_URL_ROOT.'/compta/facture/card.php?id='.(int)$newId,
        'message'         => $isCN
            ? "Created and validated credit note ".$inv->ref." for ".number_format($inv->total_ht, 2).($parentSoRef ? " (order $orderNumber, SO $parentSoRef)." : " (order $orderNumber, no SO).")
            : ($parentSoId
                ? "Created and validated invoice ".$inv->ref." linked to SO $parentSoRef."
                : "Created and validated invoice ".$inv->ref." under customer $socid (no SO)."),
    );
}

/**
 * Record payment(s) for the net amount still due for this order.
 *
 * Important: eBay reconciliation can create credit notes/adjustments for the
 * same ref_client. Paying every open invoice in full would over-clear the
 * customer and leave the credit notes as a negative outstanding balance. We
 * therefore pay only the net positive due across invoices + credit notes.
 *
 * Body: { orderNumber, payoutId, payoutDateUnix, paymentTypeId?, bankAccountId? }
 */
function doPay($body, $resultByOrder)
{
    global $db, $user, $conf;

    $orderNumber    = isset($body['orderNumber']) ? $body['orderNumber'] : '';
    $payoutId       = isset($body['payoutId']) ? $body['payoutId'] : '';
    $payoutDateUnix = isset($body['payoutDateUnix']) ? (int) $body['payoutDateUnix'] : 0;
    $paymentTypeId  = isset($body['paymentTypeId']) ? (int) $body['paymentTypeId'] : (int) $conf->global->EBAYRECONCILE_PAYMENT_TYPE_ID;
    $bankAccountId  = isset($body['bankAccountId']) ? (int) $body['bankAccountId'] : (int) $conf->global->EBAYRECONCILE_BANK_ACCOUNT_ID;
    $userNote       = isset($body['note']) ? trim((string) $body['note']) : '';

    if (!$orderNumber) throw new Exception('orderNumber is required');
    if (!$payoutId) throw new Exception('payoutId is required');
    if (!$payoutDateUnix) throw new Exception('payoutDateUnix is required');

    $invoiceCandidates = array();
    $netDue = 0.0;
    $docs = findOrderInvoicesAndCreditNotes($orderNumber);
    foreach ($docs as $doc) {
        $remain = round((float) $doc['remain_to_pay'], 2);
        $netDue += $remain;

        if ((int) $doc['type'] === Facture::TYPE_STANDARD && (int) $doc['paye'] === 0 && $remain > 0.00001) {
            $invoiceCandidates[] = array(
                'id' => (int) $doc['id'],
                'ref' => $doc['ref'],
                'remain_to_pay' => $remain,
            );
        }
    }
    $netDue = round($netDue, 2);

    $payments = array();
    $skipped  = array();
    $failed   = array();
    $totalPaid = 0.0;
    $remainingToAllocate = max(0, $netDue);

    if ($remainingToAllocate <= 0.00001) {
        foreach ($invoiceCandidates as $c) {
            $skipped[] = array(
                'invoiceId' => $c['id'],
                'invoiceRef' => $c['ref'],
                'reason' => 'net_due<=0',
                'remaintopay' => $c['remain_to_pay'],
                'net_due' => $netDue,
            );
        }
    }

    foreach ($invoiceCandidates as $c) {
        if ($remainingToAllocate <= 0.00001) {
            break;
        }

        // Refetch live to read current remaintopay accurately
        $f = new Facture($db);
        if ($f->fetch($c['id']) <= 0) {
            $failed[] = array('invoiceId' => $c['id'], 'invoiceRef' => $c['ref'], 'error' => 'fetch failed: '.$f->error);
            continue;
        }
        $remain = (float) (method_exists($f, 'getRemainToPay') ? $f->getRemainToPay() : ($f->total_ttc - $f->getSommePaiement()));
        if ($remain <= 0) {
            $skipped[] = array('invoiceId' => $c['id'], 'invoiceRef' => $c['ref'], 'reason' => 'remaintopay<=0', 'remaintopay' => $remain);
            continue;
        }
        $payAmount = min($remain, $remainingToAllocate);
        $payAmount = round($payAmount, 2);
        if ($payAmount <= 0) {
            $skipped[] = array('invoiceId' => $c['id'], 'invoiceRef' => $c['ref'], 'reason' => 'allocated<=0', 'remaintopay' => $remain, 'net_due' => $netDue);
            continue;
        }

        $p = new Paiement($db);
        $p->datepaye    = $payoutDateUnix;
        $p->paiementid  = $paymentTypeId;
        $p->num_payment = $payoutId;
        $p->note_private= "eBay payout $payoutId - order $orderNumber (invoice ".$f->ref.")";
        if ($userNote !== '') $p->note_private .= "\nUser note: ".$userNote;
        $p->amounts     = array($f->id => $payAmount);
        $paymentId = $p->create($user, 1); // 1 = closepaidinvoices yes
        if ($paymentId <= 0) {
            $failed[] = array('invoiceId' => $c['id'], 'invoiceRef' => $c['ref'], 'error' => $p->error);
            continue;
        }
        if ($bankAccountId > 0) {
            $bankRet = $p->addPaymentToBank($user, 'payment', '(eBay payout '.$payoutId.')', $bankAccountId, '', '');
            if ($bankRet < 0) {
                // Not fatal — payment recorded, but bank line not linked
                $failed[] = array('invoiceId' => $c['id'], 'invoiceRef' => $c['ref'], 'error' => 'addPaymentToBank: '.$p->error);
            }
        }
        $totalPaid += $payAmount;
        $remainingToAllocate = round($remainingToAllocate - $payAmount, 2);
        $payments[] = array(
            'invoiceId' => (string) $f->id,
            'invoiceRef'=> $f->ref,
            'amount'    => $payAmount,
            'paymentId' => (string) $paymentId,
        );
    }

    $ok = count($failed) === 0;
    return array(
        'ok'           => $ok,
        'orderNumber'  => $orderNumber,
        'payoutId'     => $payoutId,
        'summary'      => array(
            'paid'      => count($payments),
            'skipped'   => count($skipped),
            'failed'    => count($failed),
            'totalPaid' => round($totalPaid, 2),
            'netDue'    => $netDue,
        ),
        'payments'     => $payments,
        'skipped'      => $skipped,
        'errors'       => $failed,
        'message'      => (count($payments) === 0 && count($skipped) > 0)
            ? "Nothing to pay (skipped ".count($skipped).")."
            : "Created ".count($payments)." payment(s)".(count($skipped) ? ", skipped ".count($skipped) : '').(count($failed) ? ", failed ".count($failed) : '').".",
    );
}

/**
 * Append a settled payout into llx_ebayreconcile_payout for the History page.
 * Body: { payoutId, payoutDate, payoutMethod, ordersCount, paymentsCount, totalPaid, sourceFile, items: [...] }
 */
function doSavePayout($body)
{
    global $db, $user;

    $payoutId = isset($body['payoutId']) ? (string) $body['payoutId'] : '';
    if (!$payoutId) throw new Exception('payoutId is required');

    $reportSummary = isset($body['report']['summary']) && is_array($body['report']['summary'])
        ? $body['report']['summary']
        : null;
    if ($reportSummary === null) throw new Exception('Cannot settle payout without a reconciliation report.');
    $unresolved = (int) ($reportSummary['unresolved_rows'] ?? 0);
    $outstanding = (float) ($reportSummary['dolibarr_outstanding'] ?? 0);
    $reconciled = !empty($reportSummary['workflow_reconciled']);
    if (!$reconciled || $unresolved > 0 || abs($outstanding) > 0.01) {
        throw new Exception('Cannot settle payout: reconciliation work remains.');
    }

    $now = dol_now();
    $payoutDate = isset($body['payoutDate']) ? $body['payoutDate'] : null;
    $payoutDateSql = $payoutDate ? "'".$db->escape(date('Y-m-d', strtotime($payoutDate)))."'" : 'NULL';

    // Upsert by (entity, payout_id): one settled row per payout. Re-settling the same
    // payout replaces the prior record instead of appending a duplicate. (Drafts for
    // this payout are dropped further below.)
    $delPrev = "DELETE FROM ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $delPrev .= " WHERE entity = 1 AND status = 'settled' AND payout_id = '".$db->escape($payoutId)."'";
    if (!$db->query($delPrev)) throw new Exception('Cleanup of prior settled row failed: '.$db->lasterror());

    // Full reconciled state for replay when re-opening a settled payout (read-only),
    // so it shows the state it was settled in rather than re-matching now-paid invoices.
    $stateJsonSql = (isset($body['state']) && $body['state'] !== null)
        ? "'".$db->escape(json_encode($body['state']))."'"
        : 'NULL';

    $sql = "INSERT INTO ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $sql .= " (entity, status, payout_id, payout_date, payout_method, csv_filename, orders_count, payments_count, total_paid, settled_at, settled_by, summary_json, state_json, date_creation)";
    $sql .= " VALUES (";
    $sql .= " 1,";
    $sql .= " 'settled',";
    $sql .= " '".$db->escape($payoutId)."',";
    $sql .= " ".$payoutDateSql.",";
    $sql .= " '".$db->escape($body['payoutMethod'] ?? '')."',";
    $sql .= " '".$db->escape($body['sourceFile'] ?? '')."',";
    $sql .= " ".(int)($body['ordersCount'] ?? 0).",";
    $sql .= " ".(int)($body['paymentsCount'] ?? 0).",";
    $sql .= " ".(float)($body['totalPaid'] ?? 0).",";
    $sql .= " '".$db->idate($now)."',";
    $sql .= " ".(int)$user->id.",";
    $sql .= " '".$db->escape(json_encode(array(
        'items'  => $body['items'] ?? array(),
        'totals' => array(
            'grossSales'  => isset($body['grossSales'])  ? (float)$body['grossSales']  : null,
            'totalDebits' => isset($body['totalDebits']) ? (float)$body['totalDebits'] : null,
            'totalCredits'=> isset($body['totalCredits'])? (float)$body['totalCredits']: null,
            'netPayout'   => isset($body['netPayout'])   ? (float)$body['netPayout']   : null,
            'statedPayout'=> isset($body['statedPayout'])? (float)$body['statedPayout']: null,
            'ebayPayout'  => isset($body['ebayPayout'])  ? (float)$body['ebayPayout']  : null,
            'dolibarrNet' => isset($body['dolibarrNet']) ? (float)$body['dolibarrNet'] : null,
            'diff'        => 0.0,
        ),
        // Full audit report (summary + orders + documents) so History can re-download
        // the exact CSV later without re-uploading the payout.
        'report' => $body['report'] ?? null,
    )))."',";
    $sql .= " ".$stateJsonSql.",";
    $sql .= " '".$db->idate($now)."'";
    $sql .= ")";

    if (!$db->query($sql)) throw new Exception('Insert failed: '.$db->lasterror());
    $newid = $db->last_insert_id(MAIN_DB_PREFIX.'ebayreconcile_payout');

    // The reconciliation is now settled — drop any in-progress draft for this payout
    // so the List Reconciliations screen shows a single settled row.
    $del = "DELETE FROM ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $del .= " WHERE entity = 1 AND status = 'draft' AND payout_id = '".$db->escape($payoutId)."'";
    $db->query($del);

    return array('ok' => true, 'id' => $newid);
}

/**
 * Create or update an in-progress reconciliation draft so the user can leave and
 * resume later. One draft per (entity, payout_id): re-saving updates it.
 * Body: { payoutId, payoutDate, payoutMethod, sourceFile, ordersCount, paymentsCount,
 *         totals: {...tie-out summary...}, state: {...full results+payout+totals...} }
 */
function doSaveDraft($body)
{
    global $db, $user;

    $payoutId = isset($body['payoutId']) ? (string) $body['payoutId'] : '';
    if (!$payoutId) throw new Exception('payoutId is required');

    $now        = dol_now();
    $payoutDate = !empty($body['payoutDate']) ? "'".$db->escape(date('Y-m-d', strtotime($body['payoutDate'])))."'" : 'NULL';
    $summary    = $db->escape(json_encode(array(
        'totals' => isset($body['totals']) && is_array($body['totals']) ? $body['totals'] : array(),
    )));
    $state      = $db->escape(json_encode(isset($body['state']) ? $body['state'] : array()));

    // Find an existing draft for this payout.
    $existing = 0;
    $q = "SELECT rowid FROM ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $q .= " WHERE entity = 1 AND status = 'draft' AND payout_id = '".$db->escape($payoutId)."'";
    $res = $db->query($q);
    if ($res && ($o = $db->fetch_object($res))) $existing = (int) $o->rowid;

    if ($existing) {
        $sql = "UPDATE ".MAIN_DB_PREFIX."ebayreconcile_payout SET";
        $sql .= " payout_date = ".$payoutDate.",";
        $sql .= " payout_method = '".$db->escape($body['payoutMethod'] ?? '')."',";
        $sql .= " csv_filename = '".$db->escape($body['sourceFile'] ?? '')."',";
        $sql .= " orders_count = ".(int)($body['ordersCount'] ?? 0).",";
        $sql .= " payments_count = ".(int)($body['paymentsCount'] ?? 0).",";
        $sql .= " total_paid = ".(float)($body['totalPaid'] ?? 0).",";
        $sql .= " settled_by = ".(int)$user->id.",";
        $sql .= " summary_json = '".$summary."',";
        $sql .= " state_json = '".$state."'";
        $sql .= " WHERE rowid = ".$existing;
        if (!$db->query($sql)) throw new Exception('Draft update failed: '.$db->lasterror());
        return array('ok' => true, 'id' => $existing, 'updated' => true);
    }

    $sql = "INSERT INTO ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $sql .= " (entity, status, payout_id, payout_date, payout_method, csv_filename, orders_count, payments_count, total_paid, settled_at, settled_by, summary_json, state_json, date_creation)";
    $sql .= " VALUES (1, 'draft',";
    $sql .= " '".$db->escape($payoutId)."',";
    $sql .= " ".$payoutDate.",";
    $sql .= " '".$db->escape($body['payoutMethod'] ?? '')."',";
    $sql .= " '".$db->escape($body['sourceFile'] ?? '')."',";
    $sql .= " ".(int)($body['ordersCount'] ?? 0).",";
    $sql .= " ".(int)($body['paymentsCount'] ?? 0).",";
    $sql .= " ".(float)($body['totalPaid'] ?? 0).",";
    $sql .= " NULL,";
    $sql .= " ".(int)$user->id.",";
    $sql .= " '".$summary."',";
    $sql .= " '".$state."',";
    $sql .= " '".$db->idate($now)."'";
    $sql .= ")";
    if (!$db->query($sql)) throw new Exception('Draft insert failed: '.$db->lasterror());
    return array('ok' => true, 'id' => $db->last_insert_id(MAIN_DB_PREFIX.'ebayreconcile_payout'), 'updated' => false);
}

/**
 * Delete a draft reconciliation (only drafts can be deleted, never settled rows).
 * Body: { id }
 */
function doDeleteDraft($body)
{
    global $db;
    $id = isset($body['id']) ? (int) $body['id'] : 0;
    if (!$id) throw new Exception('id is required');
    $sql = "DELETE FROM ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $sql .= " WHERE rowid = ".$id." AND entity = 1 AND status = 'draft'";
    $res = $db->query($sql);
    if (!$res) throw new Exception('Delete failed: '.$db->lasterror());
    return array('ok' => true, 'id' => $id);
}

function doSaveNote($body)
{
    $orderNumber = isset($body['orderNumber']) ? trim((string) $body['orderNumber']) : '';
    $note = isset($body['note']) ? trim((string) $body['note']) : '';
    if ($orderNumber === '') throw new Exception('orderNumber is required');
    if (empty($_SESSION['ebayreconcile_lastrun']['results']) || !is_array($_SESSION['ebayreconcile_lastrun']['results'])) {
        throw new Exception('No reconcile session found');
    }

    foreach ($_SESSION['ebayreconcile_lastrun']['results'] as &$row) {
        if (!isset($row['order_number']) || $row['order_number'] !== $orderNumber) continue;
        $row['notes'] = $note;
        return array('ok' => true, 'orderNumber' => $orderNumber, 'note' => $note);
    }
    unset($row);

    throw new Exception('Order not found in last reconcile session');
}

/**
 * Build a FactureLigne-like array (Dolibarr's Facture::create() accepts these in $lines).
 */
function makeLine($desc, $qty, $subprice)
{
    return array(
        'desc'           => $desc,
        'qty'            => $qty,
        'subprice'       => $subprice,
        'price'          => $subprice,
        'pu_ht'          => $subprice,
        'tva_tx'         => 0,
        'remise_percent' => 0,
        'product_type'   => 1, // 0=product, 1=service
        'info_bits'      => 0,
    );
}
