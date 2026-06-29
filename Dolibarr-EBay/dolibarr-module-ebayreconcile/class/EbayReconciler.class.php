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

        // Payout lines with no eBay order number become one "No order #" bucket so
        // the file ties out to the penny — nothing is silently dropped.
        if (!empty($parsed['noOrderLines'])) {
            $results[] = $this->reconcileNoOrderBucket($parsed['noOrderLines']);
        }

        // Stable order: status group, then order number.
        usort($results, function ($a, $b) {
            $sa = $a['status']; $sb = $b['status'];
            if ($sa !== $sb) return strcmp($sa, $sb);
            return strcmp($a['order_number'], $b['order_number']);
        });

        $summary = $this->summarise($results);
        // Fold in the file-level tie-out totals (gross sales, credits, debits, net payout).
        if (!empty($parsed['totals'])) {
            $summary = array_merge($summary, $parsed['totals']);
        }

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

        // eBay's own payout figure lives in the summary block above the
        // transaction header as a row "Amount","8,496.29 USD". Capture it so we can
        // prove the reconciled net ties out to the amount eBay actually paid.
        $statedPayout = null;
        $scanTo = ($headerIdx === -1) ? count($lines) : $headerIdx;
        for ($j = 0; $j < $scanTo; $j++) {
            $cells = $this->parseRow($lines[$j]);
            if (isset($cells[0]) && strcasecmp(trim($cells[0]), 'Amount') === 0 && isset($cells[1])) {
                $amt = trim(preg_replace('/[^0-9.\-]/', '', str_replace(',', '', $cells[1])));
                if ($amt !== '' && is_numeric($amt)) { $statedPayout = (float) $amt; break; }
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
        $grossCol       = $col('Gross transaction amount');
        $payoutDateCol  = $col('Payout date');
        $payoutIdCol    = $col('Payout ID');
        $payoutMethodCol= $col('Payout method');

        if ($orderCol < 0 || $netCol < 0) {
            throw new Exception('CSV missing required columns (Order number / Net amount).');
        }

        $payout = null;
        $groups = array();
        $noOrderLines = array();
        // File-level tie-out totals (every numeric line counts, order or not).
        $grossSales = 0.0;   // sum of Gross transaction amount
        $debits     = 0.0;   // sum of positive net lines (money in / income)
        $credits    = 0.0;   // sum of negative net lines (money out / owed to eBay)

        for ($i = $headerIdx + 1; $i < count($lines); $i++) {
            $row = $this->parseRow($lines[$i]);
            if (count($row) <= max($orderCol, $netCol)) continue;

            $netRaw = trim(str_replace(',', '', $row[$netCol]));
            if ($netRaw === '' || $netRaw === '--') continue;
            if (!is_numeric($netRaw)) continue;
            $net = (float) $netRaw;

            // Tie-out accumulators (sign-based credits/debits + gross sales).
            if ($net >= 0) $debits += $net; else $credits += $net;
            if ($grossCol >= 0 && isset($row[$grossCol])) {
                $grossRaw = trim(str_replace(',', '', $row[$grossCol]));
                if ($grossRaw !== '' && $grossRaw !== '--' && is_numeric($grossRaw)) {
                    $grossSales += (float) $grossRaw;
                }
            }

            $order = trim($row[$orderCol]);

            // Capture payout-level info once. Done before the order check so a
            // payout whose first row carries no order number still yields metadata.
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

            $type = ($typeCol >= 0 && isset($row[$typeCol])) ? trim($row[$typeCol]) : '';
            $line = array(
                'date'        => ($dateCol >= 0 && isset($row[$dateCol])) ? trim($row[$dateCol]) : '',
                'type'        => $type,
                'net'         => round($net, 2),
                'description' => ($descCol >= 0 && isset($row[$descCol])) ? trim($row[$descCol]) : '',
            );

            // A payout line with no eBay order number (a payout-level fee, dispute,
            // shipping adjustment, ...) still moves money. It used to be dropped,
            // which made the payout fail to tie out. Collect these into a dedicated
            // "No order #" bucket so every debit/credit on the file is accounted for.
            if ($order === '' || $order === '--') {
                $noOrderLines[] = $line;
                continue;
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
            $groups[$order]['types'][$type] = true;
            $groups[$order]['lines'][] = $line;
        }

        // Finalise: round totals and normalise types
        foreach ($groups as $k => $g) {
            $groups[$k]['ebayNet'] = round($g['ebayNet'], 2);
            $groups[$k]['types'] = array_values(array_keys($g['types']));
        }

        return array(
            'groups'       => $groups,
            'payout'       => $payout,
            'noOrderLines' => $noOrderLines,
            'totals'       => array(
                'grossSales'   => round($grossSales, 2),
                'debits'       => round($debits, 2),
                'credits'      => round($credits, 2),
                'netPayout'    => round($debits + $credits, 2),
                'statedPayout' => $statedPayout !== null ? round($statedPayout, 2) : null,
                'tiesOut'      => $statedPayout !== null ? (abs($statedPayout - ($debits + $credits)) <= 0.01) : null,
                'tieDiff'      => $statedPayout !== null ? round(($debits + $credits) - $statedPayout, 2) : null,
            ),
        );
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
        // Sign-based: negative eBay net means we owe eBay (credit note);
        // positive means eBay owes us (invoice). For MISMATCH the JS overrides
        // this with the diff sign, but for MISSING/NO_LINKED_INVOICES the eBay
        // net is the full amount and its sign is authoritative.
        $suggestedAction = $g['ebayNet'] < 0 ? 'credit_note' : 'invoice';
        $base = array(
            'order_number'     => $orderNumber,
            'ebay_net'         => $g['ebayNet'],
            'ebay_rows'        => $g['rows'],
            'ebay_types'       => $g['types'],
            'ebay_type'        => $this->primaryType($g['types'], $hasRefund),
            'ebay_lines'       => $g['lines'],
            'has_refund'       => $hasRefund,
            'suggested_action' => $suggestedAction,
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
            if (isset($so['statut']) && (int) $so['statut'] === -1 && abs($diff) <= $this->matchTolerance) {
                // Cancelled SO (Commande::STATUS_CANCELED): the eBay refund+order
                // net to ~0 and there's nothing in Dolibarr to post against —
                // treat as reconciled rather than offering to create a document.
                $status = 'MATCH';
                $notes  = 'Cancelled SO ' . $so['ref'] . ' — nothing to post.';
            } else {
                $status = 'NO_LINKED_INVOICES';
                $notes  = 'Sales order ' . $so['ref'] . ' has no linked invoices/credit notes';
            }
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

    /**
     * Build the synthetic "No order #" bucket from payout lines that carried no
     * eBay order number. There's no SO / ref_client to match, so it behaves like a
     * MISSING row: the action creates a document under the default eBay customer,
     * sign-driven (negative net -> credit note, positive -> invoice). A bucket that
     * nets to zero (offsetting lines) is Exclude-only.
     */
    protected function reconcileNoOrderBucket($lines)
    {
        $net = 0.0;
        $types = array();
        foreach ($lines as $l) {
            $net += (float) $l['net'];
            $t = isset($l['type']) ? trim((string) $l['type']) : '';
            if ($t !== '') $types[$t] = true;
        }
        $net = round($net, 2);
        $types = array_values(array_keys($types));
        $hasRefund = false;
        foreach ($lines as $l) {
            if (!empty($l['type']) && strcasecmp(trim((string) $l['type']), 'Refund') === 0) { $hasRefund = true; break; }
        }

        return array(
            'order_number'       => '(no order #)',
            'ebay_net'           => $net,
            'ebay_rows'          => count($lines),
            'ebay_types'         => $types,
            'ebay_type'          => $this->primaryType($types, $hasRefund),
            'ebay_lines'         => $lines,
            'has_refund'         => $hasRefund,
            'suggested_action'   => $net < 0 ? 'credit_note' : 'invoice',
            'dolibarr_order_ref' => null,
            'dolibarr_order_id'  => null,
            'dolibarr_net'       => 0,
            'diff'               => $net,   // diff = eBay net - 0 (nothing in Dolibarr)
            'invoices'           => array(),
            'status'             => 'NO_ORDER_NUMBER',
            'notes'              => 'Payout line(s) with no eBay order number — must be accounted for so the payout ties out.',
        );
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
     * A short label of the eBay transaction type(s) in this group, for display
     * (CSV "Type" column: Order / Refund / Shipping label / Other fee). Refund
     * wins when present since it drives the credit-note handling.
     */
    protected function primaryType($types, $hasRefund)
    {
        if ($hasRefund) return 'Refund';
        $types = array_values(array_filter((array) $types, function ($t) { return trim((string) $t) !== ''; }));
        if (empty($types)) return '';
        foreach (array('Shipping label', 'Other fee', 'Order') as $pref) {
            foreach ($types as $t) {
                if (strcasecmp(trim((string) $t), $pref) === 0) return $pref;
            }
        }
        return implode(', ', $types);
    }

    /**
     * Find SO with ref_client exactly = $orderNumber.
     * Returns ['id'=>..., 'ref'=>..., 'socid'=>...] or null.
     */
    public function findSalesOrder($orderNumber)
    {
        $sql = "SELECT rowid, ref, fk_soc, fk_statut FROM " . MAIN_DB_PREFIX . "commande";
        $sql .= " WHERE ref_client = '" . $this->db->escape($orderNumber) . "'";
        $sql .= " AND entity IN (" . getEntity('commande') . ")";
        $sql .= " ORDER BY rowid DESC LIMIT 1";
        $res = $this->db->query($sql);
        if (!$res) return null;
        if ($this->db->num_rows($res) === 0) return null;
        $obj = $this->db->fetch_object($res);
        return array(
            'id'     => (int) $obj->rowid,
            'ref'    => $obj->ref,
            'socid'  => (int) $obj->fk_soc,
            'statut' => (int) $obj->fk_statut,   // -1 = cancelled (Commande::STATUS_CANCELED)
        );
    }

    /**
     * Find invoices (type=0) AND credit notes (type=2) for an eBay order.
     *
     * Dolibarr RMA/return credit notes may not keep the eBay order number in
     * ref_client, but they are linked back to the original invoice through
     * fk_facture_source. Include those source-linked credit notes so returns
     * already handled in Dolibarr are not counted as new credits to create.
     * Returns [{id, ref, type:'invoice'|'credit_note', total_ht, is_paid, remain_to_pay}, ...]
     */
    public function findInvoicesAndCreditNotes($orderNumber)
    {
        require_once DOL_DOCUMENT_ROOT.'/compta/facture/class/facture.class.php';

        $out = array();
        $seen = array();
        $sourceInvoiceIds = array();

        $addDoc = function($obj) use (&$out, &$seen, &$sourceInvoiceIds) {
            $rowid = (int) $obj->rowid;
            if ($rowid <= 0 || !empty($seen[$rowid])) return;
            $seen[$rowid] = true;

            $isCreditNote = ((int) $obj->type === 2);
            if (!$isCreditNote) $sourceInvoiceIds[] = $rowid;

            // Remaining-to-pay (amount still DUE) for BOTH invoices and credit
            // notes. getRemainToPay() returns it signed — credit notes come back
            // negative — so summing across docs gives the net outstanding position
            // used as dolNet in reconcileOneOrder.
            $remainToPay = 0.0;
            $facture = new Facture($this->db);
            if ($facture->fetch($rowid) > 0) {
                $remainToPay = (float) (method_exists($facture, 'getRemainToPay')
                    ? $facture->getRemainToPay()
                    : ($facture->total_ttc - $facture->getSommePaiement()));
            }
            $out[] = array(
                'id'       => $rowid,
                'ref'      => $obj->ref,
                'type'     => $isCreditNote ? 'credit_note' : 'invoice',
                'total_ht' => (float) $obj->total_ht,
                'is_paid'  => abs($remainToPay) <= 0.00001,
                'remain_to_pay' => round($remainToPay, 2),
                'source_invoice_id' => !empty($obj->fk_facture_source) ? (int) $obj->fk_facture_source : 0,
            );
        };

        $sql = "SELECT rowid, ref, type, total_ht, paye, fk_facture_source FROM " . MAIN_DB_PREFIX . "facture";
        $sql .= " WHERE ref_client = '" . $this->db->escape($orderNumber) . "'";
        $sql .= " AND entity IN (" . getEntity('facture') . ")";
        $sql .= " AND type IN (0, 2)";
        // Only validated/closed documents count for reconciliation. Drafts are
        // intentionally ignored so unfinished Dolibarr paperwork does not mask a
        // missing invoice/credit note or get reused by the workflow.
        $sql .= " AND fk_statut > 0";
        $sql .= " AND fk_statut <> " . ((int) Facture::STATUS_ABANDONED);
        $sql .= " ORDER BY rowid";
        $res = $this->db->query($sql);
        if (!$res) return array();
        while ($obj = $this->db->fetch_object($res)) $addDoc($obj);

        $sourceInvoiceIds = array_values(array_unique(array_filter(array_map('intval', $sourceInvoiceIds))));
        if (!empty($sourceInvoiceIds)) {
            $sql = "SELECT rowid, ref, type, total_ht, paye, fk_facture_source FROM " . MAIN_DB_PREFIX . "facture";
            $sql .= " WHERE fk_facture_source IN (" . implode(',', $sourceInvoiceIds) . ")";
            $sql .= " AND entity IN (" . getEntity('facture') . ")";
            $sql .= " AND type = 2";
            $sql .= " AND fk_statut > 0";
            $sql .= " AND fk_statut <> " . ((int) Facture::STATUS_ABANDONED);
            $sql .= " ORDER BY rowid";
            $res = $this->db->query($sql);
            if ($res) {
                while ($obj = $this->db->fetch_object($res)) $addDoc($obj);
            }
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
            'noOrderNumber'     => 0,
            'netTotal'          => 0.0,   // sum of every line's eBay net = the payout total
        );
        foreach ($results as $r) {
            $s['netTotal'] += (float) $r['ebay_net'];
            switch ($r['status']) {
                case 'MATCH':               $s['matches']++; break;
                case 'MISMATCH':            $s['mismatches']++; break;
                case 'MISSING_IN_DOLIBARR': $s['missingInDolibarr']++; break;
                case 'NO_LINKED_INVOICES':  $s['noLinkedInvoices']++; break;
                case 'NO_ORDER_NUMBER':     $s['noOrderNumber']++; break;
            }
        }
        $s['netTotal'] = round($s['netTotal'], 2);
        return $s;
    }
}
