<?php
/**
 * eBay payout reconciliation — main page.
 *
 * GET  : show the upload form (and the in-memory last result, if any in $_SESSION).
 * POST (with file): parse the CSV, run reconciliation, render results.
 */

// Load Dolibarr environment (htdocs/custom/ebayreconcile/reconcile.php → up 3 levels to htdocs)
$res = 0;
if (!$res && file_exists("../main.inc.php"))       $res = @include "../main.inc.php";
if (!$res && file_exists("../../main.inc.php"))    $res = @include "../../main.inc.php";
if (!$res && file_exists("../../../main.inc.php")) $res = @include "../../../main.inc.php";
if (!$res) die("Include of main fails");

require_once DOL_DOCUMENT_ROOT.'/custom/ebayreconcile/class/EbayReconciler.class.php';
require_once DOL_DOCUMENT_ROOT.'/custom/ebayreconcile/lib/ebayreconcile.lib.php';

global $langs, $user, $conf, $db;
$langs->loadLangs(array('ebayreconcile@ebayreconcile', 'main', 'errors'));

// Permission gate
if (empty($user->rights->ebayreconcile->use)) accessforbidden();

$action = GETPOST('action', 'aZ09');

$reconcileResult = null;
$reconcileError = null;

// Handle CSV upload
if ($action === 'reconcile' && !empty($_FILES['payoutcsv']['tmp_name'])) {
    $tmp = $_FILES['payoutcsv']['tmp_name'];
    $name = $_FILES['payoutcsv']['name'];
    $content = file_get_contents($tmp);
    if ($content === false) {
        $reconcileError = "Could not read uploaded file";
    } else {
        try {
            $reconciler = new EbayReconciler($db);
            $reconcileResult = $reconciler->reconcileCsv($content);
            $reconcileResult['source_file'] = $name;
            // Stash in session so the action.php handlers can read payout metadata and per-row context
            // without re-uploading the CSV.
            $_SESSION['ebayreconcile_lastrun'] = $reconcileResult;
        } catch (Exception $e) {
            $reconcileError = $e->getMessage();
        }
    }
}

// Header — uses Dolibarr's standard chrome
llxHeader('', $langs->trans("ReconcilePageTitle"), '');

// Cache-bust assets by file mtime so a redeploy always reloads them (avoids a
// stale cached JS rendering against newer server HTML — e.g. a shifted table).
$ebrCssV = (int) @filemtime(dol_buildpath('/ebayreconcile/css/ebayreconcile.css', 0));
print '<link rel="stylesheet" href="'.dol_buildpath('/ebayreconcile/css/ebayreconcile.css', 1).'?v='.$ebrCssV.'" />';

// Topbar (Dolibarr's print_fiche_titre is the canonical h1 here)
print load_fiche_titre($langs->trans("ReconcilePageTitle"), '', 'bank_account');

// --- Upload card ---
print '<div class="fichecenter ebr-card">';
print '  <div class="ebr-titrebar">';
print '    <i class="fa fa-file-upload"></i> '.$langs->trans("UploadPayoutCsv");
print '  </div>';
print '  <div class="ebr-body">';
print '    <form method="POST" enctype="multipart/form-data" id="ebrUploadForm">';
print '      <input type="hidden" name="token" value="'.newToken().'"/>';
print '      <input type="hidden" name="action" value="reconcile"/>';
print '      <label class="ebr-dropzone">';
print '        <i class="fa fa-cloud-upload-alt"></i>';
print '        <div class="ebr-dz-text">';
print '          <div class="ebr-t1">'.$langs->trans("DropOrBrowse").'</div>';
print '          <div class="ebr-t2">'.$langs->trans("PayoutMatchExplain").'</div>';
print '          <div class="ebr-selected-file" id="ebrSelectedFile">'.$langs->trans("NoFileSelected").'</div>';
print '        </div>';
print '        <input type="file" name="payoutcsv" accept=".csv,text/csv" required />';
print '      </label>';
print '      <div style="margin-top:12px">';
print '        <button class="butAction" type="submit">'.$langs->trans("Reconcile").'</button>';
print '      </div>';
print '    </form>';
if ($reconcileError) {
    print '    <div class="ebr-error"><i class="fa fa-exclamation-triangle"></i> '.dol_escape_htmltag($reconcileError).'</div>';
}
print '  </div>';
print '</div>';

// --- If we have a result, render summary + table ---
if ($reconcileResult) {
    $summary = $reconcileResult['summary'];
    $payout  = $reconcileResult['payout'];
    $results = $reconcileResult['results'];

    // Summary tiles
    print '<div class="ebr-tiles">';
    $tiles = array(
        array($langs->trans("Orders"),           (int)$summary['ordersCompared'],   ''),
        array($langs->trans("Matches"),          (int)$summary['matches'],          'match'),
        array($langs->trans("Mismatches"),       (int)$summary['mismatches'],       'mismatch'),
        array($langs->trans("MissingInDolibarr"),(int)$summary['missingInDolibarr'],'missing'),
        array($langs->trans("NoLinkedInvoices"), (int)$summary['noLinkedInvoices'], 'noinv'),
    );
    foreach ($tiles as $t) {
        list($label, $num, $cls) = $t;
        print '<div class="ebr-tile '.$cls.'">';
        print '<div class="ebr-lbl">'.dol_escape_htmltag($label).'</div>';
        print '<div class="ebr-num">'.(int)$num.'</div>';
        print '</div>';
    }
    print '</div>';

    // Payout banner
    if ($payout) {
        print '<div class="ebr-payoutbanner">';
        print '<i class="fa fa-coins"></i> ';
        if (!empty($reconcileResult['source_file'])) {
            print '<span class="ebr-sub"><strong>File:</strong> '.dol_escape_htmltag($reconcileResult['source_file']).'</span> &middot; ';
        }
        print 'Payout <code>'.dol_escape_htmltag($payout['id']).'</code> &middot; ';
        print dol_escape_htmltag($payout['date']).' &middot; ';
        print dol_escape_htmltag($payout['method']);
        print '</div>';
    }

    // Toolbar — filters + bulk actions + downloads
    print '<div class="fichecenter ebr-card" id="ebrTablePanel">';
    print '<div class="ebr-titrebar">';
    print '<i class="fa fa-list"></i> Orders ';
    print '<span class="ebr-spacer"></span>';
    if ($user->rights->ebayreconcile->write) {
        print '<button class="butAction" id="ebrBulkApprove" type="button" hidden>'.$langs->trans("ApproveAllMismatches").'</button>';
        print '<button class="butAction" id="ebrBulkCreate" type="button" hidden>Create all invoices</button>';
        print '<button class="butAction" id="ebrBulkPay" type="button" hidden>'.$langs->trans("PayAll").'</button>';
    }
    print '<button class="button" id="ebrDlCsv"  type="button">CSV</button> ';
    print '<button class="button" id="ebrDlJson" type="button">JSON</button>';
    print '</div>';
    print '<div class="ebr-body">';

    print '<div class="ebr-helpbox">';
    print '<div class="ebr-helpbox-title"><i class="fa fa-info-circle"></i> '.$langs->trans("ReconcileHelpTitle").'</div>';
    print '<ul class="ebr-helpbox-list">';
    print '<li>'.$langs->trans("ReconcileHelpPoint1").'</li>';
    print '<li>'.$langs->trans("ReconcileHelpPoint2").'</li>';
    print '<li>'.$langs->trans("ReconcileHelpPoint3").'</li>';
    print '<li>'.$langs->trans("ReconcileHelpPoint4").'</li>';
    print '</ul>';
    print '</div>';

    // Filters
    print '<div class="ebr-filters">';
    print '<input type="search" id="ebrSearch" placeholder="Search by order, SO ref, invoice ref..." />';
    print ' <span class="ebr-chip active" data-status="ALL">All <span class="ebr-count" data-count="ALL">0</span></span>';
    print ' <span class="ebr-chip" data-status="MATCH">'.$langs->trans('StatusMATCH').' <span class="ebr-count" data-count="MATCH">0</span></span>';
    print ' <span class="ebr-chip" data-status="MISMATCH">'.$langs->trans('StatusMISMATCH').' <span class="ebr-count" data-count="MISMATCH">0</span></span>';
    print ' <span class="ebr-chip" data-status="MISSING_IN_DOLIBARR">'.$langs->trans('StatusMISSING_IN_DOLIBARR').' <span class="ebr-count" data-count="MISSING_IN_DOLIBARR">0</span></span>';
    print ' <span class="ebr-chip" data-status="NO_LINKED_INVOICES">'.$langs->trans('StatusNO_LINKED_INVOICES').' <span class="ebr-count" data-count="NO_LINKED_INVOICES">0</span></span>';
    print '</div>';

    // The table
    print '<div class="ebr-tablewrap">';
    print '<table class="liste ebr-table" id="ebrTable">';
    print '<thead><tr class="liste_titre">';
    print '<th data-key="status">'.$langs->trans("ColStatus").'</th>';
    print '<th data-key="order_number">'.$langs->trans("ColOrderNumber").'</th>';
    print '<th data-key="ebay_type">'.$langs->trans("ColEbayType").'</th>';
    print '<th data-key="ebay_net" class="num">'.$langs->trans("ColEbayNet").'</th>';
    print '<th data-key="dolibarr_net" class="num">'.$langs->trans("ColDolibarrNet").'</th>';
    print '<th data-key="diff" class="num">'.$langs->trans("ColDiff").'</th>';
    print '<th data-key="dolibarr_order_ref">'.$langs->trans("ColSORef").'</th>';
    print '<th data-key="invoice_refs">'.$langs->trans("ColInvoices").'</th>';
    print '<th data-key="notes" class="ebr-col-notes">'.$langs->trans("ColNotes").'</th>';
    print '<th>'.$langs->trans("ColAction").'</th>';
    print '</tr></thead>';
    print '<tbody id="ebrTbody"></tbody>';
    print '</table>';
    print '<div id="ebrEmpty" class="ebr-empty" hidden>No rows match the current filter.</div>';
    print '</div>';

    print '</div>'; // /ebr-body
    print '</div>'; // /fichecenter

    // Bootstrap state for the JS
    $bootstrap = array(
        'results'              => $results,
        'payout'               => $payout,
        'sourceFile'           => $reconcileResult['source_file'],
        'writePerm'            => !empty($user->rights->ebayreconcile->write),
        'invoiceUrlTemplate'   => DOL_URL_ROOT.'/compta/facture/card.php?id={id}',
        'orderUrlTemplate'     => DOL_URL_ROOT.'/commande/card.php?id={id}',
        'actionUrl'            => dol_buildpath('/ebayreconcile/action.php', 1),
        'token'                => newToken(),
        'i18n'                 => array(
            'NotesPlaceholder' => $langs->trans("NotesPlaceholder"),
            'Saving'           => $langs->trans("Saving"),
            'Saved'            => $langs->trans("Saved"),
            'SaveFailed'       => $langs->trans("SaveFailed"),
        ),
    );
    print '<script>window.EBR_BOOT = '.json_encode($bootstrap).';</script>';
}

print '<script>window.EBR_UPLOAD_I18N = '.json_encode(array(
    'NoFileSelected' => $langs->trans("NoFileSelected"),
    'SelectedFile'   => $langs->trans("SelectedFile"),
    'AddNote'        => $langs->trans("AddNote"),
    'EditNote'       => $langs->trans("EditNote"),
    'SaveNote'       => $langs->trans("SaveNote"),
    'Cancel'         => $langs->trans("Cancel"),
)).';</script>';

// JS for filters / sorting / bulk + per-row actions
$ebrJsV = (int) @filemtime(dol_buildpath('/ebayreconcile/js/ebayreconcile.js', 0));
print '<script src="'.dol_buildpath('/ebayreconcile/js/ebayreconcile.js', 1).'?v='.$ebrJsV.'"></script>';

llxFooter();
$db->close();
