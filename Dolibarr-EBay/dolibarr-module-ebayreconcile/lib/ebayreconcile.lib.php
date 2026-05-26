<?php
/**
 * Shared helpers for the eBay Reconciliation module.
 */

/**
 * Tab definitions for any future object cards (e.g. invoice tab showing the
 * reconcile origin). Kept here as a stub so menus/pages can call it without
 * crashing — extend when we add per-invoice eBay info.
 */
function ebayreconcileAdminPrepareHead()
{
    global $langs, $conf;

    $h = 0;
    $head = array();

    $head[$h][0] = dol_buildpath("/ebayreconcile/admin/setup.php", 1);
    $head[$h][1] = $langs->trans("Settings");
    $head[$h][2] = 'settings';
    $h++;

    return $head;
}
