<?php
/**
 * Admin setup page — configure default socid, bank account, payment type, tolerance.
 */
$res = 0;
if (!$res && file_exists("../../main.inc.php"))    $res = @include "../../main.inc.php";
if (!$res && file_exists("../../../main.inc.php")) $res = @include "../../../main.inc.php";
if (!$res) die("Include of main fails");

require_once DOL_DOCUMENT_ROOT.'/custom/ebayreconcile/lib/ebayreconcile.lib.php';
require_once DOL_DOCUMENT_ROOT.'/core/lib/admin.lib.php';

global $langs, $user, $db;
$langs->loadLangs(array('ebayreconcile@ebayreconcile', 'admin'));

if (empty($user->admin)) accessforbidden();

$action = GETPOST('action', 'aZ09');

if ($action === 'save') {
    dolibarr_set_const($db, 'EBAYRECONCILE_DEFAULT_SOCID',     GETPOST('default_socid', 'int'),     'chaine', 0, '', 0);
    dolibarr_set_const($db, 'EBAYRECONCILE_BANK_ACCOUNT_ID',   GETPOST('bank_account_id', 'int'),   'chaine', 0, '', 0);
    dolibarr_set_const($db, 'EBAYRECONCILE_PAYMENT_TYPE_ID',   GETPOST('payment_type_id', 'int'),   'chaine', 0, '', 0);
    dolibarr_set_const($db, 'EBAYRECONCILE_MATCH_TOLERANCE',   GETPOST('match_tolerance', 'alpha'), 'chaine', 0, '', 0);
    setEventMessage($langs->trans("SetupSaved"));
}

llxHeader('', $langs->trans("SetupPageTitle"), '');

$head = ebayreconcileAdminPrepareHead();
print dol_get_fiche_head($head, 'settings', $langs->trans("ModuleEbayReconcileName"), -1, 'bank_account');

print '<form method="POST" action="'.$_SERVER['PHP_SELF'].'">';
print '<input type="hidden" name="token" value="'.newToken().'"/>';
print '<input type="hidden" name="action" value="save"/>';

print '<table class="noborder centpercent">';
print '<tr class="liste_titre"><th>Setting</th><th>Value</th><th>Notes</th></tr>';

print '<tr><td>'.$langs->trans("SetupDefaultSocid").'</td>';
print '<td><input type="number" name="default_socid" value="'.(int)$conf->global->EBAYRECONCILE_DEFAULT_SOCID.'" /></td>';
print '<td><span class="opacitymedium">'.$langs->trans("SetupDefaultSocidHelp").'</span></td></tr>';

print '<tr><td>'.$langs->trans("SetupBankAccount").'</td>';
print '<td><input type="number" name="bank_account_id" value="'.(int)$conf->global->EBAYRECONCILE_BANK_ACCOUNT_ID.'" /></td>';
print '<td><span class="opacitymedium">'.$langs->trans("SetupBankAccountHelp").'</span></td></tr>';

print '<tr><td>'.$langs->trans("SetupPaymentType").'</td>';
print '<td><input type="number" name="payment_type_id" value="'.(int)$conf->global->EBAYRECONCILE_PAYMENT_TYPE_ID.'" /></td>';
print '<td><span class="opacitymedium">'.$langs->trans("SetupPaymentTypeHelp").'</span></td></tr>';

print '<tr><td>'.$langs->trans("SetupMatchTolerance").'</td>';
print '<td><input type="text" name="match_tolerance" value="'.dol_escape_htmltag($conf->global->EBAYRECONCILE_MATCH_TOLERANCE ?? '0.01').'" /></td>';
print '<td><span class="opacitymedium">'.$langs->trans("SetupMatchToleranceHelp").'</span></td></tr>';

print '</table>';

print '<div class="center" style="margin-top:14px">';
print '<button class="butAction" type="submit">'.$langs->trans("Save").'</button>';
print '</div>';

print '</form>';

print dol_get_fiche_end();

llxFooter();
$db->close();
