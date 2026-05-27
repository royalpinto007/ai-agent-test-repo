<?php
/* Copyright (C) 2026 TXS Corp
 *
 * Module descriptor for eBay Reconciliation.
 *
 * Reconciles an eBay payout CSV against Dolibarr sales orders / invoices /
 * credit notes, lets the user fix mismatches with one click (creates credit
 * notes, missing invoices), and records payments using the payout's own ID
 * and date.
 */

require_once DOL_DOCUMENT_ROOT.'/core/modules/DolibarrModules.class.php';

class modEbayReconcile extends DolibarrModules
{
    public function __construct($db)
    {
        global $langs, $conf;

        $this->db = $db;
        // Module ID — must be unique across all installed modules. Custom modules use 500000+.
        $this->numero = 500201;
        $this->rights_class = 'ebayreconcile';
        $this->family = "billing";
        $this->module_position = '90';
        $this->name = preg_replace('/^mod/i', '', get_class($this));
        $this->description = "Reconcile eBay payouts against Dolibarr invoices and credit notes";
        $this->descriptionlong = "Upload an eBay payout CSV, match each order to its Dolibarr Sales Order, create credit notes or missing invoices for any discrepancies, and record payments using the payout's own ID and date.";
        $this->editor_name = 'TXS Corp';
        $this->editor_url = 'https://staging.txscorp.com';
        $this->version = '1.0.7';
        $this->const_name = 'MAIN_MODULE_'.strtoupper($this->name);
        $this->picto = 'bank_account';

        // Files included by this module
        $this->module_parts = array(
            'css' => array('/ebayreconcile/css/ebayreconcile.css'),
            'js'  => array('/ebayreconcile/js/ebayreconcile.js'),
        );

        // Directories this module needs writeable
        $this->dirs = array("/ebayreconcile/temp");

        // Config (admin setup) page URL
        $this->config_page_url = array("setup.php@ebayreconcile");

        // Dependencies — none, but Bank module recommended (we link payments to bank accounts)
        $this->depends = array('modBanque');
        $this->requiredby = array();
        $this->conflictwith = array();

        // Compatibility — works on Dolibarr 18+
        $this->phpmin = array(7, 4);
        $this->need_dolibarr_version = array(18, 0);
        $this->langfiles = array("ebayreconcile@ebayreconcile");

        // Default constants installed with the module
        $this->const = array(
            // Default eBay generic customer socid (used when a row has no SO and we need to create an invoice somewhere)
            0 => array('EBAYRECONCILE_DEFAULT_SOCID', 'chaine', '3657', 'Default eBay customer socid', 0, 'allentities', 1),
            // Bank account id for eBay payouts (1 = CityNational in our staging)
            1 => array('EBAYRECONCILE_BANK_ACCOUNT_ID', 'chaine', '1', 'Bank account id for eBay payouts', 0, 'allentities', 1),
            // Payment type id (2 = VIR / Credit Transfer)
            2 => array('EBAYRECONCILE_PAYMENT_TYPE_ID', 'chaine', '2', 'Payment type id for payouts (2 = VIR)', 0, 'allentities', 1),
            // Tolerance for "match" classification — diff smaller than this (absolute) is considered MATCH
            3 => array('EBAYRECONCILE_MATCH_TOLERANCE', 'chaine', '0.01', 'Tolerance for MATCH classification', 0, 'allentities', 1),
        );

        // Database tables created by this module (SQL files in /sql/)
        $this->tables = array();

        // Permissions
        $this->rights = array();
        $r = 0;

        $this->rights[$r][0] = $this->numero + 1;
        $this->rights[$r][1] = 'Use eBay reconciliation (upload, view results)';
        $this->rights[$r][2] = 'r';
        $this->rights[$r][3] = 1; // default = enabled
        $this->rights[$r][4] = 'use';
        $r++;

        $this->rights[$r][0] = $this->numero + 2;
        $this->rights[$r][1] = 'Approve adjustments / create invoices / record payments';
        $this->rights[$r][2] = 'w';
        $this->rights[$r][3] = 0; // default = disabled (admin/finance only)
        $this->rights[$r][4] = 'write';
        $r++;

        $this->rights[$r][0] = $this->numero + 3;
        $this->rights[$r][1] = 'Configure eBay reconciliation defaults';
        $this->rights[$r][2] = 'w';
        $this->rights[$r][3] = 0;
        $this->rights[$r][4] = 'admin';

        // Top menu & left menu entries
        $this->menu = array();
        $r = 0;

        // Left menu group under existing "Bank/Cash" top menu
        $this->menu[$r++] = array(
            'fk_menu'   => 'fk_mainmenu=bank',
            'type'      => 'left',
            'titre'     => 'eBay payouts',
            'mainmenu'  => 'bank',
            'leftmenu'  => 'ebayreconcile',
            'url'       => '/ebayreconcile/reconcile.php',
            'langs'     => 'ebayreconcile@ebayreconcile',
            'position'  => 1000,
            'enabled'   => '$conf->ebayreconcile->enabled',
            'perms'     => '$user->rights->ebayreconcile->use',
            'target'    => '',
            'user'      => 2,
        );

        $this->menu[$r++] = array(
            'fk_menu'   => 'fk_mainmenu=bank,fk_leftmenu=ebayreconcile',
            'type'      => 'left',
            'titre'     => 'Reconcile a payout',
            'mainmenu'  => 'bank',
            'leftmenu'  => 'ebayreconcile',
            'url'       => '/ebayreconcile/reconcile.php',
            'langs'     => 'ebayreconcile@ebayreconcile',
            'position'  => 1010,
            'enabled'   => '$conf->ebayreconcile->enabled',
            'perms'     => '$user->rights->ebayreconcile->use',
            'target'    => '',
            'user'      => 2,
        );

        $this->menu[$r++] = array(
            'fk_menu'   => 'fk_mainmenu=bank,fk_leftmenu=ebayreconcile',
            'type'      => 'left',
            'titre'     => 'Payouts history',
            'mainmenu'  => 'bank',
            'leftmenu'  => 'ebayreconcile',
            'url'       => '/ebayreconcile/history.php',
            'langs'     => 'ebayreconcile@ebayreconcile',
            'position'  => 1020,
            'enabled'   => '$conf->ebayreconcile->enabled',
            'perms'     => '$user->rights->ebayreconcile->use',
            'target'    => '',
            'user'      => 2,
        );
    }

    /**
     * Module install
     */
    public function init($options = '')
    {
        $sql = array();
        $result = $this->_load_tables('/ebayreconcile/sql/');
        if ($result < 0) return $result;
        return $this->_init($sql, $options);
    }

    /**
     * Module uninstall — keeps tables/data by default
     */
    public function remove($options = '')
    {
        $sql = array();
        return $this->_remove($sql, $options);
    }
}
