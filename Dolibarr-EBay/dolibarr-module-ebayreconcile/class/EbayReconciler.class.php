<?php
/**
 * EbayReconciler — main business logic.
 *
 * Responsibilities:
 *   - Parse an eBay payout CSV (in-memory string, no on-disk file).
 *   - Group by Order number, summing Net amount and capturing per-row breakdown.
 *   - Look up the corresponding Dolibarr Sales Order by ref_client.
 *   - Sum invoices (type=0) for that ref_client to get Dolibarr net.
 *   - Classify each order as MATCH / MISMATCH / MISSING_IN_DOLIBARR / NO_LINKED_INVOICES.
 *   - Extract payout-level metadata (payout id, date, method) from CSV header.
 *
 * Uses Dolibarr's $db directly — no REST API, no external calls.
 */

class EbayReconciler
{
    /** @var DoliDB */
    protected $db;

    /** @var float */
    public $matchTolerance = 0.01;

    public function __construct($db)
    {
        $this->db = $db;
        global $conf;
        if (!empty($conf->global->EBAYRECONCILE_MATCH_TOLERANCE)) {
            $this->matchTolerance = (float) $conf->global->EBAYRECONCILE_MATCH_TOLERANCE;
        }
    }

    /**
     * Reconcile a payout CSV.
     *
     * @param string $csvContent  Raw CSV file contents
     * @return array              ['summary'=>..., 'payout'=>..., 'results'=>[...]]
     */
    public function reconcileCsv($csvContent)
    {
        $parsed = $this->parseCsv($csvContent);
        $groups = $parsed['groups'];
        $payout = $parsed['payout'];

        $results = array();
        foreach ($groups as $orderNumber => $g) {
            $results[] = $this->reconcileOneOrder($orderNumber, $g);
        }

        // Stable order: status group, then order number.
        usort($results, function ($a, $b) {
            $sa = $a['status']; $sb = $b['status'];
            if ($sa !== $sb) return strcmp($sa, $sb);
            return strcmp($a['order_number'], $b['order_number']);
        });

        $summary = $this->summarise($results);

        return array(
            'summary' => $summary,
            'payout'  => $payout,
            'results' => $results,
        );
    }

    /**
     * Parse CSV: returns ['groups' => [orderNum => g], 'payout' => {...}]
     */
    protected function parseCsv($csvContent)
    {
        $lines = preg_split("/\r\n|\n|\r/", $csvContent);
        $headerIdx = -1;
        foreach ($lines as $i => $line) {
            $candidate = ltrim($line, "\xEF\xBB\xBF\"");
            if (strpos($candidate, 'Transaction creation date') === 0) {
                $headerIdx = $i;
                break;
            }
        }
        if ($headerIdx === -1) {
            throw new Exception('Could not find header row in CSV. Upload an eBay payout CSV.');
        }

        $header = $this->parseRow($lines[$headerIdx]);
        $col = function ($name) use ($header) {
            $i = array_search($name, $header, true);
            return ($i === false) ? -1 : $i;
        };
        $orderCol       = $col('Order number');
        $netCol         = $col('Net amount');
        $typeCol        = $col('Type');
        $dateCol        = $col('Transaction creation date');
        $descCol        = $col('Description');
        $payoutDateCol  = $col('Payout date');
        $payoutIdCol    = $col('Payout ID');
        $payoutMethodCol= $col('Payout method');

        if ($orderCol < 0 || $netCol < 0) {
            throw new Exception('CSV missing required columns (Order number / Net amount).');
        }

        $payout = null;
        $groups = array();

        for ($i = $headerIdx + 1; $i < count($lines); $i++) {
            $row = $this->parseRow($lines[$i]);
            if (count($row) <= max($orderCol, $netCol)) continue;

            $order = trim($row[$orderCol]);
            if ($order === '' || $order === '--') continue;
            $netRaw = trim(str_replace(',', '', $row[$netCol]));
            if ($netRaw === '' || $netRaw === '--') continue;
            if (!is_numeric($netRaw)) continue;
            $net = (float) $netRaw;

            // Capture payout-level info once.
            if ($payout === null && $payoutIdCol >= 0) {
                $pid = isset($row[$payoutIdCol]) ? trim($row[$payoutIdCol]) : '';
                if ($pid !== '' && $pid !== '--') {
                    $pd = ($payoutDateCol >= 0 && isset($row[$payoutDateCol])) ? trim($row[$payoutDateCol]) : '';
                    $payout = array(
                        'id'        => $pid,
                        'date'      => $pd,
                        'date_unix' => $pd ? (int) strtotime($pd) : 0,
                        'method'    => ($payoutMethodCol >= 0 && isset($row[$payoutMethodCol])) ? trim($row[$payoutMethodCol]) : '',
                    );
                }
            }

            if (!isset($groups[$order])) {
                $groups[$order] = array(
                    'orderNumber' => $order,
                    'ebayNet'     => 0.0,
                    'rows'        => 0,
                    'types'       => array(),
                    'lines'       => array(),
                );
            }
            $groups[$order]['ebayNet'] += $net;
            $groups[$order]['rows']    += 1;
            $type = ($typeCol >= 0 && isset($row[$typeCol])) ? trim($row[$typeCol]) : '';
            $groups[$order]['types'][$type] = true;
            $groups[$order]['lines'][] = array(
                'date'        => ($dateCol >= 0 && isset($row[$dateCol])) ? trim($row[$dateCol]) : '',
                'type'        => $type,
                'net'         => round($net, 2),
                'description' => ($descCol >= 0 && isset($row[$descCol])) ? trim($row[$descCol]) : '',
            );
        }

        // Finalise: round totals and normalise types
        foreach ($groups as $k => $g) {
            $groups[$k]['ebayNet'] = round($g['ebayNet'], 2);
            $groups[$k]['types'] = array_values(array_keys($g['types']));
        }

        return array('groups' => $groups, 'payout' => $payout);
    }

    /**
     * Minimal RFC-4180-ish CSV row parser — handles double-quoted fields with
     * embedded commas. Doesn't handle escaped quotes-in-quotes, which the eBay
     * payout CSV doesn't use.
     */
    protected function parseRow($line)
    {
        $out = array();
        $cur = '';
        $inQ = false;
        $len = strlen($line);
        for ($i = 0; $i < $len; $i++) {
            $c = $line[$i];
            if ($c === '"') { $inQ = !$inQ; continue; }
            if ($c === ',' && !$inQ) { $out[] = $cur; $cur = ''; continue; }
            $cur .= $c;
        }
        $out[] = $cur;
        return $out;
    }

    /**
     * For one eBay order group, find SO + invoices in Dolibarr.
     */
    protected function reconcileOneOrder($orderNumber, $g)
    {
        $hasRefund = $this->groupHasRefund($g);
        $base = array(
            'order_number' => $orderNumber,
            'ebay_net'     => $g['ebayNet'],
            'ebay_rows'    => $g['rows'],
            'ebay_types'   => $g['types'],
            'ebay_lines'   => $g['lines'],
            'has_refund'   => $hasRefund,
        );

        // 1. Find the SO by ref_client.
        $so = $this->findSalesOrder($orderNumber);
        if (!$so) {
            $docs = $this->findInvoicesAndCreditNotes($orderNumber);
            $invoices = array_filter($docs, function ($d) { return $d['type'] === 'invoice'; });
            if (count($invoices) === 0) {
                return array_merge($base, array(
                    'dolibarr_order_ref' => null,
                    'dolibarr_order_id'  => null,
                    'dolibarr_net'       => 0,
                    'diff'               => round($g['ebayNet'], 2),
                    'invoices'           => array(),
                    'status'             => 'MISSING_IN_DOLIBARR',
                    'notes'              => 'No sales order with this ref_client',
                ));
            }

            // dolNet = amount still due (remaining to pay), not gross invoice total.
            $dolNet = 0.0;
            foreach ($docs as $d) {
                $dolNet += (float) $d['remain_to_pay'];
            }
            $dolNet = round($dolNet, 2);
            $diff = round($g['ebayNet'] - $dolNet, 2);
            $status = abs($diff) > $this->matchTolerance ? 'MISMATCH' : 'MATCH';
            $notes = $status === 'MATCH'
                ? 'No sales order with this ref_client, but invoice exists'
                : 'No sales order with this ref_client; invoice exists but totals differ';

            return array_merge($base, array(
                'dolibarr_order_ref' => null,
                'dolibarr_order_id'  => null,
                'dolibarr_net'       => $dolNet,
                'diff'               => $diff,
                'invoices'           => array_values($docs),
                'status'             => $status,
                'notes'              => $notes,
            ));
        }

        // 2. Find all invoices + CNs by ref_client.
        $docs = $this->findInvoicesAndCreditNotes($orderNumber);
        $invoices = array_filter($docs, function ($d) { return $d['type'] === 'invoice'; });

        // 3. dolNet = the amount still DUE in Dolibarr (remaining to pay), summed
        //    across invoices and credit notes — NOT the gross invoice total.
        //    getRemainToPay() is signed (credit notes come back negative), so the
        //    sum is the net customer position still outstanding. Using the due
        //    amount means an invoice already settled in an earlier cycle contributes
        //    0, so a later eBay refund no longer cancels against a long-paid invoice.
        $dolNet = 0.0;
        foreach ($docs as $d) {
            $dolNet += (float) $d['remain_to_pay'];
        }
        $dolNet = round($dolNet, 2);
        // Compare eBay net cash against the Dolibarr amount due, on the same sign
        // basis: eBay - Dolibarr. A refund (negative eBay) only nets to ~0 when a
        // matching credit note carries the offsetting negative due.
        $diff = round($g['ebayNet'] - $dolNet, 2);

        if (count($invoices) === 0) {
            $status = 'NO_LINKED_INVOICES';
            $notes  = 'Sales order ' . $so['ref'] . ' has no linked invoices/credit notes';
        } elseif (abs($diff) > $this->matchTolerance) {
            $status = 'MISMATCH';
            $notes  = '';
        } else {
            $status = 'MATCH';
            $notes  = '';
        }

        return array_merge($base, array(
            'dolibarr_order_ref' => $so['ref'],
            'dolibarr_order_id'  => $so['id'],
            'dolibarr_net'       => $dolNet,
            'diff'               => $diff,
            'invoices'           => array_values($docs),
            'status'             => $status,
            'notes'              => $notes,
        ));
    }

    protected function groupHasRefund($g)
    {
        if (!empty($g['types'])) {
            foreach ($g['types'] as $type) {
                if (strcasecmp(trim((string) $type), 'Refund') === 0) return true;
            }
        }
        if (!empty($g['lines'])) {
            foreach ($g['lines'] as $line) {
                if (!empty($line['type']) && strcasecmp(trim((string) $line['type']), 'Refund') === 0) return true;
            }
        }
        return false;
    }

    /**
     * Find SO with ref_client exactly = $orderNumber.
     * Returns ['id'=>..., 'ref'=>..., 'socid'=>...] or null.
     */
    public function findSalesOrder($orderNumber)
    {
        $sql = "SELECT rowid, ref, fk_soc FROM " . MAIN_DB_PREFIX . "commande";
        $sql .= " WHERE ref_client = '" . $this->db->escape($orderNumber) . "'";
        $sql .= " AND entity IN (" . getEntity('commande') . ")";
        $sql .= " ORDER BY rowid DESC LIMIT 1";
        $res = $this->db->query($sql);
        if (!$res) return null;
        if ($this->db->num_rows($res) === 0) return null;
        $obj = $this->db->fetch_object($res);
        return array(
            'id'    => (int) $obj->rowid,
            'ref'   => $obj->ref,
            'socid' => (int) $obj->fk_soc,
        );
    }

    /**
     * Find invoices (type=0) AND credit notes (type=2) by ref_client.
     * Returns [{id, ref, type:'invoice'|'credit_note', total_ht, is_paid, remain_to_pay}, ...]
     */
    public function findInvoicesAndCreditNotes($orderNumber)
    {
        require_once DOL_DOCUMENT_ROOT.'/compta/facture/class/facture.class.php';

        $sql = "SELECT rowid, ref, type, total_ht, paye FROM " . MAIN_DB_PREFIX . "facture";
        $sql .= " WHERE ref_client = '" . $this->db->escape($orderNumber) . "'";
        $sql .= " AND entity IN (" . getEntity('facture') . ")";
        $sql .= " AND type IN (0, 2)";
        $sql .= " ORDER BY rowid";
        $res = $this->db->query($sql);
        if (!$res) return array();
        $out = array();
        while ($obj = $this->db->fetch_object($res)) {
            $isCreditNote = ((int) $obj->type === 2);
            // Remaining-to-pay (amount still DUE) for BOTH invoices and credit
            // notes. getRemainToPay() returns it signed — credit notes come back
            // negative — so summing across docs gives the net outstanding position
            // used as dolNet in reconcileOneOrder.
            $remainToPay = 0.0;
            $facture = new Facture($this->db);
            if ($facture->fetch((int) $obj->rowid) > 0) {
                $remainToPay = (float) (method_exists($facture, 'getRemainToPay')
                    ? $facture->getRemainToPay()
                    : ($facture->total_ttc - $facture->getSommePaiement()));
            }
            $out[] = array(
                'id'       => (int) $obj->rowid,
                'ref'      => $obj->ref,
                'type'     => $isCreditNote ? 'credit_note' : 'invoice',
                'total_ht' => (float) $obj->total_ht,
                'is_paid'  => abs($remainToPay) <= 0.00001,
                'remain_to_pay' => round($remainToPay, 2),
            );
        }
        return $out;
    }

    /**
     * Build the summary counts the UI shows in the tiles.
     */
    protected function summarise($results)
    {
        $s = array(
            'ordersCompared'    => count($results),
            'matches'           => 0,
            'mismatches'        => 0,
            'missingInDolibarr' => 0,
            'noLinkedInvoices'  => 0,
        );
        foreach ($results as $r) {
            switch ($r['status']) {
                case 'MATCH':               $s['matches']++; break;
                case 'MISMATCH':            $s['mismatches']++; break;
                case 'MISSING_IN_DOLIBARR': $s['missingInDolibarr']++; break;
                case 'NO_LINKED_INVOICES':  $s['noLinkedInvoices']++; break;
            }
        }
        return $s;
    }
}
