<?php
/**
 * Payouts history page — reads from llx_ebayreconcile_payout.
 */
$res = 0;
if (!$res && file_exists("../main.inc.php"))       $res = @include "../main.inc.php";
if (!$res && file_exists("../../main.inc.php"))    $res = @include "../../main.inc.php";
if (!$res && file_exists("../../../main.inc.php")) $res = @include "../../../main.inc.php";
if (!$res) die("Include of main fails");

global $langs, $user, $db;
$langs->loadLangs(array('ebayreconcile@ebayreconcile', 'main'));

if (empty($user->rights->ebayreconcile->use)) accessforbidden();

llxHeader('', $langs->trans("HistoryPageTitle"), '');
print '<link rel="stylesheet" href="'.dol_buildpath('/ebayreconcile/css/ebayreconcile.css', 1).'" />';
print load_fiche_titre($langs->trans("HistoryPageTitle"), '', 'bank_account');

$sql = "SELECT rowid, payout_id, payout_date, payout_method, csv_filename, orders_count, payments_count, total_paid, settled_at, settled_by, summary_json";
$sql .= " FROM ".MAIN_DB_PREFIX."ebayreconcile_payout";
$sql .= " WHERE entity IN (".getEntity('facture').")";
$sql .= " ORDER BY settled_at DESC";
$rs = $db->query($sql);

print '<div class="fichecenter ebr-card">';
print '<div class="ebr-titrebar"><i class="fa fa-history"></i> '.$langs->trans("PayoutsHistory").'</div>';
print '<div class="ebr-body">';

if (!$rs || $db->num_rows($rs) === 0) {
    print '<div class="ebr-empty">No payouts settled yet. Reconcile a payout and click <strong>Pay all</strong> — it will show up here.</div>';
} else {
    print '<div class="ebr-tablewrap">';
    print '<table class="liste ebr-table">';
    print '<thead><tr class="liste_titre">';
    print '<th>Payout ID</th><th>Payout date</th><th>Method</th>';
    print '<th class="num">Orders</th><th class="num">Payments</th><th class="num">Total paid</th>';
    print '<th>Settled at</th><th>By</th><th></th>';
    print '</tr></thead><tbody>';

    $idx = 0;
    while ($r = $db->fetch_object($rs)) {
        $items = json_decode($r->summary_json, true);
        if (!is_array($items)) $items = array();

        // Resolve settled_by username
        $byName = '-';
        if ($r->settled_by) {
            $u = new User($db);
            if ($u->fetch((int)$r->settled_by) > 0) $byName = $u->getFullName($langs);
        }

        print '<tr class="'.($idx % 2 === 0 ? 'pair' : 'impair').'">';
        print '<td><code>'.dol_escape_htmltag($r->payout_id).'</code></td>';
        print '<td>'.($r->payout_date ? dol_print_date($db->jdate($r->payout_date), 'day') : '-').'</td>';
        print '<td><span class="ebr-sub">'.dol_escape_htmltag($r->payout_method ?: '-').'</span></td>';
        print '<td class="num">'.(int)$r->orders_count.'</td>';
        print '<td class="num">'.(int)$r->payments_count.'</td>';
        print '<td class="num"><strong>'.price((float)$r->total_paid).'</strong></td>';
        print '<td><span class="ebr-sub">'.dol_print_date($db->jdate($r->settled_at), 'dayhour').'</span></td>';
        print '<td><span class="ebr-sub">'.dol_escape_htmltag($byName).'</span></td>';
        print '<td><a class="ebr-toggle" data-detail="'.$idx.'" href="javascript:;">details ▾</a></td>';
        print '</tr>';

        // Detail row (hidden by default)
        print '<tr class="ebr-detail" data-detail="'.$idx.'" hidden><td colspan="9"><div class="ebr-detail-inner">';
        if (empty($items)) {
            print '<em>No per-payment data recorded for this entry.</em>';
        } else {
            print '<table style="width:100%;font-size:11.5px;">';
            print '<thead><tr><th>Order</th><th>SO ref</th><th>Invoice</th><th class="num">Amount</th><th>Payment id</th></tr></thead><tbody>';
            foreach ($items as $it) {
                $soRef = $it['soRef'] ?? '-';
                $soUrl = !empty($it['soId']) ? DOL_URL_ROOT.'/commande/card.php?id='.(int)$it['soId'] : null;
                $invRef = $it['invoiceRef'] ?? '-';
                $invUrl = !empty($it['invoiceId']) ? DOL_URL_ROOT.'/compta/facture/card.php?id='.(int)$it['invoiceId'] : null;
                print '<tr>';
                print '<td>'.dol_escape_htmltag($it['orderNumber'] ?? '-').'</td>';
                print '<td>'.($soUrl ? '<a href="'.$soUrl.'" target="_blank">'.dol_escape_htmltag($soRef).'</a>' : dol_escape_htmltag($soRef)).'</td>';
                print '<td>'.($invUrl ? '<a href="'.$invUrl.'" target="_blank">'.dol_escape_htmltag($invRef).'</a>' : dol_escape_htmltag($invRef)).'</td>';
                print '<td class="num">'.price((float)($it['amount'] ?? 0)).'</td>';
                print '<td><code>'.dol_escape_htmltag($it['paymentId'] ?? '-').'</code></td>';
                print '</tr>';
            }
            print '</tbody></table>';
        }
        print '</div></td></tr>';
        $idx++;
    }
    print '</tbody></table></div>';

    print '<script>
    document.querySelectorAll("a.ebr-toggle").forEach(a => {
        a.addEventListener("click", e => {
            const idx = a.dataset.detail;
            const row = document.querySelector("tr.ebr-detail[data-detail=\""+idx+"\"]");
            if (row) row.hidden = !row.hidden;
        });
    });
    </script>';
}
print '</div></div>';

llxFooter();
$db->close();
