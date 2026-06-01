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
        case 'approve':         echo json_encode(doApprove($body, $resultByOrder)); exit;
        case 'create_invoice':  echo json_encode(doCreateInvoice($body, $resultByOrder)); exit;
        case 'pay':             echo json_encode(doPay($body, $resultByOrder)); exit;
        case 'save_payout':     echo json_encode(doSavePayout($body)); exit;
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

    $inv = new Facture($db);
    $inv->socid           = $socid;
    $inv->type            = Facture::TYPE_STANDARD;
    $inv->ref_client      = $orderNumber;
    $inv->date            = dol_now();
    $inv->note_private    = "Auto-created via eBay reconciliation. eBay order: $orderNumber.".($parentSoRef ? " Linked to SO $parentSoRef (id $parentSoId)." : ' No SO existed; using default eBay customer.');
    if ($userNote !== '') $inv->note_private .= "\nUser note: ".$userNote;
    if ($parentSoId > 0) {
        $inv->origin       = 'commande';
        $inv->origin_id    = $parentSoId;
    }
    $inv->lines = array();
    foreach ($lines as $l) {
        $desc = '['.($l['type'] ?? 'eBay').'] '.($l['description'] ?? '').' ('.($l['date'] ?? '').')';
        $desc = trim(preg_replace('/\s+\(\)/', '', $desc));
        $inv->lines[] = makeLine($desc, 1, (float) ($l['net'] ?? 0));
    }

    $newId = $inv->create($user);
    if ($newId <= 0) throw new Exception('Create failed: '.$inv->error);
    if ($inv->validate($user) <= 0) throw new Exception('Validate failed: '.$inv->error);

    return array(
        'ok'              => true,
        'mode'            => $parentSoId ? 'from_so' : 'standalone',
        'orderNumber'     => $orderNumber,
        'newInvoiceId'    => (string) $newId,
        'newInvoiceRef'   => $inv->ref,
        'totalHt'         => (float) $inv->total_ht,
        'socid'           => (string) $socid,
        'so'              => $parentSoId ? array('id' => $parentSoId, 'ref' => $parentSoRef, 'socid' => $socid) : null,
        'validated'       => true,
        'dolibarrEditUrl' => DOL_URL_ROOT.'/compta/facture/card.php?id='.(int)$newId,
        'message'         => $parentSoId
            ? "Created and validated invoice ".$inv->ref." linked to SO $parentSoRef."
            : "Created and validated invoice ".$inv->ref." under customer $socid (no SO).",
    );
}

/**
 * Record a payment against every unpaid invoice for this order.
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

    // Find unpaid invoices (type=0, paye=0) for this ref_client
    $sql = "SELECT rowid, ref, total_ttc FROM ".MAIN_DB_PREFIX."facture";
    $sql .= " WHERE ref_client = '".$db->escape($orderNumber)."'";
    $sql .= " AND entity IN (".getEntity('facture').")";
    $sql .= " AND type = 0 AND paye = 0";
    $sql .= " ORDER BY rowid";
    $res = $db->query($sql);
    if (!$res) throw new Exception("Query failed: ".$db->lasterror());

    $candidates = array();
    while ($obj = $db->fetch_object($res)) {
        $candidates[] = array('id' => (int)$obj->rowid, 'ref' => $obj->ref, 'total_ttc' => (float)$obj->total_ttc);
    }

    $payments = array();
    $skipped  = array();
    $failed   = array();
    $totalPaid = 0.0;

    foreach ($candidates as $c) {
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

        $p = new Paiement($db);
        $p->datepaye    = $payoutDateUnix;
        $p->paiementid  = $paymentTypeId;
        $p->num_payment = $payoutId;
        $p->note_private= "eBay payout $payoutId - order $orderNumber (invoice ".$f->ref.")";
        if ($userNote !== '') $p->note_private .= "\nUser note: ".$userNote;
        $p->amounts     = array($f->id => $remain);
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
        $totalPaid += $remain;
        $payments[] = array(
            'invoiceId' => (string) $f->id,
            'invoiceRef'=> $f->ref,
            'amount'    => round($remain, 2),
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

    $now = dol_now();
    $payoutDate = isset($body['payoutDate']) ? $body['payoutDate'] : null;
    $payoutDateSql = $payoutDate ? "'".$db->escape(date('Y-m-d', strtotime($payoutDate)))."'" : 'NULL';

    $sql = "INSERT INTO ".MAIN_DB_PREFIX."ebayreconcile_payout";
    $sql .= " (entity, payout_id, payout_date, payout_method, csv_filename, orders_count, payments_count, total_paid, settled_at, settled_by, summary_json, date_creation)";
    $sql .= " VALUES (";
    $sql .= " 1,";
    $sql .= " '".$db->escape($payoutId)."',";
    $sql .= " ".$payoutDateSql.",";
    $sql .= " '".$db->escape($body['payoutMethod'] ?? '')."',";
    $sql .= " '".$db->escape($body['sourceFile'] ?? '')."',";
    $sql .= " ".(int)($body['ordersCount'] ?? 0).",";
    $sql .= " ".(int)($body['paymentsCount'] ?? 0).",";
    $sql .= " ".(float)($body['totalPaid'] ?? 0).",";
    $sql .= " '".$db->idate($now)."',";
    $sql .= " ".(int)$user->id.",";
    $sql .= " '".$db->escape(json_encode($body['items'] ?? array()))."',";
    $sql .= " '".$db->idate($now)."'";
    $sql .= ")";

    if (!$db->query($sql)) throw new Exception('Insert failed: '.$db->lasterror());
    return array('ok' => true, 'id' => $db->last_insert_id(MAIN_DB_PREFIX.'ebayreconcile_payout'));
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
