/* eBay Reconciliation — frontend JS
   Bootstrapped from window.EBR_BOOT (set inline by reconcile.php).
   Handles: filter chips, search, sort, per-row Approve/Create-invoice,
   bulk Approve, bulk Pay, and saves payout summary on Pay all success. */

(function () {
    function uploadT(key, fallback) {
        var dict = window.EBR_UPLOAD_I18N || {};
        return dict[key] || fallback;
    }

    function initUploadUi() {
        var input = document.querySelector('#ebrUploadForm input[type="file"][name="payoutcsv"]');
        var label = document.getElementById('ebrSelectedFile');
        if (!input || !label) return;

        function showSelected() {
            var file = input.files && input.files[0];
            label.textContent = file
                ? uploadT('SelectedFile', 'Selected file:') + ' ' + file.name
                : uploadT('NoFileSelected', 'No file selected yet.');
        }
        input.addEventListener('change', showSelected);

        // Drag-and-drop onto the dropzone. The markup advertises "Drop or
        // Browse", but without these handlers a dropped file just makes the
        // browser navigate to it. Wire drop -> populate the file input.
        var zone = (input.closest && input.closest('.ebr-dropzone'))
            || document.querySelector('#ebrUploadForm .ebr-dropzone');
        if (!zone) return;

        function squelch(e) { e.preventDefault(); e.stopPropagation(); }
        ['dragenter', 'dragover'].forEach(function (ev) {
            zone.addEventListener(ev, function (e) { squelch(e); zone.classList.add('ebr-dragover'); });
        });
        ['dragleave', 'dragend'].forEach(function (ev) {
            zone.addEventListener(ev, function (e) { squelch(e); zone.classList.remove('ebr-dragover'); });
        });
        zone.addEventListener('drop', function (e) {
            squelch(e);
            zone.classList.remove('ebr-dragover');
            var files = e.dataTransfer && e.dataTransfer.files;
            if (!files || !files.length) return;
            var file = files[0];
            // Accept only CSV, matching the input's accept attribute.
            var okName = /\.csv$/i.test(file.name);
            var okType = !file.type || /csv|excel|text\/plain/i.test(file.type);
            if (!okName && !okType) {
                label.textContent = uploadT('InvalidFileType', 'Please drop a .csv payout file.');
                return;
            }
            // Programmatically assign the dropped file to the <input> so the
            // normal form submit carries it. Needs DataTransfer (modern browsers).
            try {
                var dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
            } catch (err) {
                label.textContent = uploadT('DragDropUnsupported', 'Drag-and-drop is not supported in this browser — click to browse instead.');
                return;
            }
            showSelected();
        });
    }

    initUploadUi();
    if (!window.EBR_BOOT) return; // page rendered without results (just upload form)

    var state = {
        results: window.EBR_BOOT.results || [],
        payout: window.EBR_BOOT.payout || null,
        sourceFile: window.EBR_BOOT.sourceFile || null,
        writePerm: !!window.EBR_BOOT.writePerm,
        actionUrl: window.EBR_BOOT.actionUrl,
        token: window.EBR_BOOT.token,
        invoiceUrlTemplate: window.EBR_BOOT.invoiceUrlTemplate,
        orderUrlTemplate: window.EBR_BOOT.orderUrlTemplate,
        i18n: window.EBR_BOOT.i18n || {},
        filter: "ALL",
        query: "",
        sortKey: null,
        sortDir: 1,
        pending: null,    // approve modal pending
        pendingCreate: null, // create-invoice modal pending
        pendingBulkPay: null,
    };
    window.__EBR = state; // for debugging

    function fmt(n) {
        if (n === null || n === undefined || n === "") return "";
        var v = Number(n);
        if (!isFinite(v)) return String(n);
        return v.toFixed(2);
    }
    function soUrl(id)  { return state.orderUrlTemplate.replace("{id}", id); }
    function invUrl(id) { return state.invoiceUrlTemplate.replace("{id}", id); }
    function t(key, fallback) { return state.i18n[key] || fallback; }

    function pickLargestInvoice(r) {
        var invs = (r.invoices || []).filter(function (i) { return i.type === "invoice"; });
        if (invs.length === 0) return null;
        return invs.reduce(function (a, b) {
            return Math.abs(Number(b.total_ht || 0)) > Math.abs(Number(a.total_ht || 0)) ? b : a;
        });
    }

    function diffCell(v) {
        if (v === null || v === undefined || v === "") return "";
        var n = Number(v);
        var cls = n > 0 ? "ebr-diff-pos" : (n < 0 ? "ebr-diff-neg" : "ebr-diff-zero");
        return '<span class="' + cls + '">' + fmt(v) + '</span>';
    }

    function ebayNetCell(r) {
        var main = fmt(r.ebay_net);
        var lines = r.ebay_lines || [];
        if (lines.length <= 1) return main;
        var parts = lines.map(function (l) {
            var n = Number(l.net);
            var cls = n > 0 ? "bd-pos" : (n < 0 ? "bd-neg" : "");
            var sign = n > 0 ? "+" : "";
            var lbl = l.type || "row";
            return '<span class="bd-row">' + esc(lbl) + ' <span class="' + cls + '">' + sign + n.toFixed(2) + '</span></span>';
        });
        return main + '<span class="ebr-breakdown">' + parts.join('<span class="bd-sep">·</span>') + '</span>';
    }

    function typeCell(r) {
        var ty = r.ebay_type || (r.ebay_types || []).join(', ');
        if (!ty) return '<span class="ebr-sub">-</span>';
        var cls = /refund/i.test(ty) ? 'ebr-type-refund' : 'ebr-type-other';
        return '<span class="ebr-typebadge ' + cls + '">' + esc(ty) + '</span>';
    }

    // What document the action will create for this row: credit note for refunds,
    // invoice otherwise. Backend sets suggested_action; fall back to has_refund.
    function docTypeForRow(r) {
        return r.suggested_action || (r.has_refund ? 'credit_note' : 'invoice');
    }
    function docLabel(r) {
        return docTypeForRow(r) === 'credit_note' ? 'Create credit note' : 'Create invoice';
    }

    function invoicesCell(r) {
        if (!r.invoices || r.invoices.length === 0) return '<span class="ebr-sub">-</span>';
        return r.invoices.map(function (i) {
            var label = i.ref || i.id;
            var type = i.type ? ' <span class="ebr-sub">[' + esc(i.type) + ']</span>' : '';
            var href = i.id ? invUrl(i.id) : "#";
            return '<a href="' + href + '" target="_blank" rel="noopener" title="id ' + i.id + ', total_ht ' + fmt(i.total_ht) + '">' + esc(label) + '</a>' + type;
        }).join(", ");
    }

    function actionCell(r) {
        var parts = [];
        if (r._adjusted) {
            var a = r._adjusted;
            var label = a.action === 'credit_note' ? 'CN' : 'INV';
            var ref = a.newInvoiceRef || ('#' + a.newInvoiceId);
            parts.push('<span class="ebr-actiontag"><i class="fa fa-check"></i> ' + label + ' ' + esc(ref) + ' created</span>'
                + ' <a href="' + (a.dolibarrEditUrl || '#') + '" target="_blank" rel="noopener" style="font-size:11px;">view</a>');
        }
        if (r._paid) {
            var p = r._paid;
            if (p.summary && p.summary.paid > 0) {
                parts.push('<span class="ebr-actiontag paid"><i class="fa fa-money-check-alt"></i> paid ' + (p.summary.totalPaid||0).toFixed(2) + '</span>');
            } else if (p.summary && p.summary.failed > 0) {
                parts.push('<span class="ebr-actiontag notapplied"><i class="fa fa-exclamation-triangle"></i> pay failed</span>');
            } else if (p.summary && p.summary.skipped > 0) {
                parts.push('<span class="ebr-actiontag"><i class="fa fa-check"></i> no balance</span>');
            }
        }
        if (parts.length) return parts.join(' ');

        if (r.status === 'MATCH' && (r.invoices || []).some(function (i) { return i.type === 'invoice'; }) && !hasPayableInvoice(r)) {
            return '<span class="ebr-actiontag paid"><i class="fa fa-check-circle"></i> already paid</span>';
        }

        if (!state.writePerm) return '';

        var isCN = docTypeForRow(r) === 'credit_note';
        var icon = isCN ? 'fa-file-invoice-dollar' : 'fa-file-invoice';
        if (r.status === 'MISMATCH') {
            var target = pickLargestInvoice(r);
            if (!target) return '<span class="ebr-sub">no parent</span>';
            return '<button class="button" data-approve="' + esc(r.order_number) + '"><i class="fa ' + icon + '"></i> ' + docLabel(r) + '</button>';
        }
        if (r.status === 'MISSING_IN_DOLIBARR' || r.status === 'NO_LINKED_INVOICES') {
            return '<button class="button" data-create="' + esc(r.order_number) + '"><i class="fa ' + icon + '"></i> ' + docLabel(r) + '</button>';
        }
        return '';
    }

    function noteCell(r) {
        var status = r._noteStatus
            ? '<span class="ebr-note-status' + (r._noteStatusError ? ' err' : '') + '">' + esc(r._noteStatus) + '</span>'
            : '';
        var isEditing = !!r._noteEditing;
        var hasNote = !!(r.notes && String(r.notes).trim() !== '');
        if (!state.writePerm) {
            return hasNote
                ? '<div class="ebr-note-view">' + esc(r.notes) + '</div>' + status
                : status;
        }
        if (isEditing) {
            return ''
                + '<textarea class="ebr-note-input' + (r._noteSaving ? ' is-saving' : '') + '"'
                + ' data-note-order="' + esc(r.order_number) + '"'
                + ' placeholder="' + esc(t('NotesPlaceholder', 'Add a note for this order')) + '">'
                + esc(r._noteDraft !== undefined ? r._noteDraft : (r.notes || '')) + '</textarea>'
                + '<div class="ebr-note-actions">'
                + '<button class="button" type="button" data-note-save="' + esc(r.order_number) + '">' + esc(t('SaveNote', 'Save note')) + '</button>'
                + '<button class="button" type="button" data-note-cancel="' + esc(r.order_number) + '">' + esc(t('Cancel', 'Cancel')) + '</button>'
                + '</div>'
                + status;
        }
        return ''
            + (hasNote ? '<div class="ebr-note-view">' + esc(r.notes) + '</div>' : '')
            + '<div class="ebr-note-actions">'
            + '<button class="button" type="button" data-note-edit="' + esc(r.order_number) + '">'
            + esc(hasNote ? t('EditNote', 'Edit note') : uploadT('AddNote', 'Add note'))
            + '</button>'
            + '</div>'
            + status;
    }

    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function unresolvedRows() {
        return state.results.filter(function (r) {
            return (r.status === 'MISMATCH' && !r._adjusted)
                || r.status === 'MISSING_IN_DOLIBARR' && !r._adjusted
                || r.status === 'NO_LINKED_INVOICES' && !r._adjusted;
        });
    }
    function hasPayableInvoice(r) {
        return (r.invoices || []).some(function (i) {
            return i.type === 'invoice' && Number(i.remain_to_pay || 0) > 0.00001;
        });
    }
    function approveActionForRow(r) {
        // The correcting document follows the eBay transaction type, not the diff
        // sign: a refund issues a credit note, everything else an invoice.
        return docTypeForRow(r);
    }
    function recalcRowAfterAdjustment(row, action, newInvoiceId, newInvoiceRef, amount, signedAmountOverride) {
        if (!row) return;
        var signedAmount = signedAmountOverride !== undefined && signedAmountOverride !== null
            ? Number(signedAmountOverride || 0)
            : (action === 'credit_note' ? -Math.abs(Number(amount || 0)) : Math.abs(Number(amount || 0)));
        row.invoices = row.invoices || [];
        row.invoices.push({
            id: Number(newInvoiceId || 0),
            ref: newInvoiceRef || ('#' + newInvoiceId),
            type: action === 'credit_note' ? 'credit_note' : 'invoice',
            total_ht: signedAmount,
            is_paid: action === 'credit_note',
            remain_to_pay: action === 'credit_note' ? 0 : Math.max(0, Number(signedAmount)),
        });
        row.dolibarr_net = Number(row.dolibarr_net || 0) + signedAmount;
        var ebay = Number(row.ebay_net || 0);
        var dol = Number(row.dolibarr_net || 0);
        // Consistent with the backend: diff is always eBay - Dolibarr.
        var nextDiff = Number((ebay - dol).toFixed(2));
        row.diff = nextDiff;
        if (Math.abs(nextDiff) <= 0.01) {
            row.status = 'MATCH';
            row.notes = row.notes || '';
        } else {
            row.status = 'MISMATCH';
        }
    }
    function rowsToPay() {
        return state.results.filter(function (r) {
            return !r._paid && (r._adjusted || (r.status === 'MATCH' && hasPayableInvoice(r)));
        });
    }
    function eligibleMismatches() {
        return state.results.filter(function (r) {
            return r.status === 'MISMATCH' && !r._adjusted && pickLargestInvoice(r);
        });
    }
    function eligibleCreates() {
        return state.results.filter(function (r) {
            return (r.status === 'MISSING_IN_DOLIBARR' || r.status === 'NO_LINKED_INVOICES')
                && !r._adjusted;
        });
    }

    // ---------- Rendering ----------

    function render() {
        var q = state.query.trim().toLowerCase();
        var rows = state.results.slice();
        if (state.filter !== 'ALL') rows = rows.filter(function (r) { return r.status === state.filter; });
        if (q) {
            rows = rows.filter(function (r) {
                var hay = [r.order_number, r.dolibarr_order_ref].concat((r.invoices||[]).map(function(i){return i.ref||'';})).join(' ').toLowerCase();
                return hay.indexOf(q) !== -1;
            });
        }
        var k = state.sortKey, dir = state.sortDir;
        if (k) {
            var numericKeys = { ebay_net:1, dolibarr_net:1, diff:1 };
            rows.sort(function (a, b) {
                var av = a[k], bv = b[k];
                if (k === 'invoice_refs') {
                    av = (a.invoices||[]).map(function(i){return i.ref||'';}).join(',');
                    bv = (b.invoices||[]).map(function(i){return i.ref||'';}).join(',');
                }
                if (numericKeys[k]) { av = Number(av); bv = Number(bv); }
                if (av === undefined || av === null) av = '';
                if (bv === undefined || bv === null) bv = '';
                if (av < bv) return -1 * dir;
                if (av > bv) return  1 * dir;
                return 0;
            });
        }

        var tbody = document.getElementById('ebrTbody');
        if (rows.length === 0) {
            tbody.innerHTML = '';
            document.getElementById('ebrEmpty').hidden = false;
        } else {
            document.getElementById('ebrEmpty').hidden = true;
            tbody.innerHTML = rows.map(function (r, i) {
                return '<tr class="' + (i % 2 === 0 ? 'pair' : 'impair') + '">'
                    + '<td><span class="ebr-badge ' + r.status + '">' + r.status.replace(/_/g, ' ') + '</span></td>'
                    + '<td><strong>' + esc(r.order_number) + '</strong></td>'
                    + '<td>' + typeCell(r) + '</td>'
                    + '<td class="num">' + ebayNetCell(r) + '</td>'
                    + '<td class="num">' + fmt(r.dolibarr_net) + '</td>'
                    + '<td class="num">' + diffCell(r.diff) + '</td>'
                    + '<td>' + (r.dolibarr_order_ref && r.dolibarr_order_id ? '<a href="' + soUrl(r.dolibarr_order_id) + '" target="_blank" rel="noopener">' + esc(r.dolibarr_order_ref) + '</a>' : esc(r.dolibarr_order_ref || '')) + '</td>'
                    + '<td>' + invoicesCell(r) + '</td>'
                    + '<td class="ebr-cell-notes">' + noteCell(r) + '</td>'
                    + '<td>' + actionCell(r) + '</td>'
                + '</tr>';
            }).join('');
        }

        // Update sort indicators
        document.querySelectorAll('#ebrTable th[data-key]').forEach(function (th) {
            th.classList.remove('sort-asc', 'sort-desc');
            if (th.dataset.key === state.sortKey) th.classList.add(state.sortDir === 1 ? 'sort-asc' : 'sort-desc');
        });

        // Update chip counts
        var totals = { ALL: state.results.length, MATCH: 0, MISMATCH: 0, MISSING_IN_DOLIBARR: 0, NO_LINKED_INVOICES: 0 };
        state.results.forEach(function (r) { totals[r.status] = (totals[r.status] || 0) + 1; });
        document.querySelectorAll('.ebr-chip .ebr-count').forEach(function (el) {
            el.textContent = totals[el.dataset.count] || 0;
        });

        // Bulk buttons
        var bulkA = document.getElementById('ebrBulkApprove');
        if (bulkA) {
            var n = eligibleMismatches().length;
            bulkA.hidden = !state.writePerm;
            bulkA.disabled = n === 0;
            bulkA.classList.toggle('ebr-bulk-disabled', n === 0);
            bulkA.textContent = 'Approve all mismatches (' + n + ')';
        }
        var bulkC = document.getElementById('ebrBulkCreate');
        if (bulkC) {
            var nc = eligibleCreates().length;
            bulkC.hidden = !state.writePerm;
            bulkC.disabled = nc === 0;
            bulkC.classList.toggle('ebr-bulk-disabled', nc === 0);
            bulkC.textContent = 'Create all documents (' + nc + ')';
        }
        var bulkP = document.getElementById('ebrBulkPay');
        if (bulkP) {
            var unresolved = unresolvedRows().length;
            var toPay = rowsToPay().length;
            var ready = state.writePerm && state.payout && state.payout.id && state.payout.date_unix;
            bulkP.hidden = !state.writePerm;
            bulkP.style.display = '';
            bulkP.disabled = !ready || unresolved > 0 || toPay === 0;
            bulkP.classList.toggle('ebr-bulk-disabled', !ready || unresolved > 0 || toPay === 0);
            bulkP.style.opacity = '';
            bulkP.textContent = unresolved > 0
                ? 'Pay all (resolve ' + unresolved + ' first)'
                : 'Pay all (' + toPay + ')';
        }
    }

    // ---------- AJAX helper ----------

    function jpost(action, payload) {
        return fetch(state.actionUrl + '?action=' + encodeURIComponent(action) + '&token=' + encodeURIComponent(state.token), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'same-origin',
        }).then(function (r) {
            return r.text().then(function (text) {
                if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + text.slice(0, 300));
                try { return JSON.parse(text); }
                catch (_) { throw new Error('Response was not JSON: ' + text.slice(0, 300)); }
            });
        });
    }

    // ---------- Modals ----------

    function ensureModal(id, html) {
        if (document.getElementById(id)) return document.getElementById(id);
        var div = document.createElement('div');
        div.id = id;
        div.className = 'ebr-modal-bg';
        div.innerHTML = html;
        document.body.appendChild(div);
        return div;
    }

    function openApproveModal(orderNumber) {
        var r = state.results.find(function (x) { return x.order_number === orderNumber; });
        if (!r) return;
        var target = pickLargestInvoice(r);
        if (!target) { showToast('No parent invoice to credit against', true); return; }
        var diff = Number(r.diff);
        var action = approveActionForRow(r);
        var amount = Math.abs(diff);

        state.pending = {
            action: action,
            orderNumber: r.order_number,
            parentInvoiceId: target.id,
            amount: amount,
            note: r.notes || '',
        };

        var modal = ensureModal('ebrApproveModal',
            '<div class="ebr-modal" style="width:480px;">'
            + '<div class="mhead"><i class="fa fa-check-circle"></i> Approve adjustment</div>'
            + '<div class="mbody"><dl id="ebrApproveBody"></dl>'
            + '<div class="mnote">Confirm will create + validate the document in Dolibarr. The reconciler will pick it up alongside the existing invoice so the totals net out.</div>'
            + '<div id="ebrApproveErr" class="ebr-error" hidden></div></div>'
            + '<div class="mfoot"><button class="button" id="ebrApproveCancel">Cancel</button>'
            + '<button class="butAction" id="ebrApproveConfirm">Confirm</button></div>'
            + '</div>');

        var actionLabel = action === 'credit_note'
            ? '<strong style="color:#b3261e">Credit note</strong>'
            : '<strong style="color:#1e8a4a">Invoice (additional)</strong>';
        document.getElementById('ebrApproveBody').innerHTML =
            '<dt>Order</dt><dd><code>' + esc(r.order_number) + '</code></dd>' +
            '<dt>SO</dt><dd><code>' + esc(r.dolibarr_order_ref || '-') + '</code></dd>' +
            '<dt>eBay net</dt><dd>' + fmt(r.ebay_net) + '</dd>' +
            '<dt>Dolibarr net</dt><dd>' + fmt(r.dolibarr_net) + '</dd>' +
            '<dt>Diff</dt><dd>' + diffCell(r.diff) + '</dd>' +
            '<dt>Will create</dt><dd>' + actionLabel + ' for <strong>' + amount.toFixed(2) + '</strong></dd>' +
            '<dt>Linked to</dt><dd><code>' + esc(target.ref) + '</code> <span class="ebr-sub">(id ' + target.id + ')</span></dd>';

        var confirmBtn = document.getElementById('ebrApproveConfirm');
        confirmBtn.onclick = confirmApprove;
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm';
        document.getElementById('ebrApproveCancel').onclick = function () { modal.classList.remove('open'); };
        document.getElementById('ebrApproveErr').hidden = true;
        modal.classList.add('open');
    }

    function confirmApprove() {
        if (!state.pending) return;
        var btn = document.getElementById('ebrApproveConfirm');
        btn.disabled = true; btn.textContent = 'Creating...';
        jpost('approve', state.pending).then(function (data) {
            if (!data.ok) throw new Error(data.error || 'n8n returned ok=false');
            var target = state.results.find(function (x) { return x.order_number === state.pending.orderNumber; });
            if (target) {
                target._adjusted = data;
                recalcRowAfterAdjustment(target, data.action, data.newInvoiceId, data.newInvoiceRef, data.amount);
            }
            showToast(data.message + ' <a href="' + data.dolibarrEditUrl + '" target="_blank">Open</a>', false);
            document.getElementById('ebrApproveModal').classList.remove('open');
            state.pending = null;
            render();
        }).catch(function (err) {
            document.getElementById('ebrApproveErr').textContent = err.message;
            document.getElementById('ebrApproveErr').hidden = false;
            btn.disabled = false; btn.textContent = 'Retry';
        });
    }

    function openCreateInvoiceModal(orderNumber) {
        var r = state.results.find(function (x) { return x.order_number === orderNumber; });
        if (!r) return;
        var hasSO = r.status === 'NO_LINKED_INVOICES';
        var lines = (r.ebay_lines && r.ebay_lines.length > 0)
            ? r.ebay_lines
            : [{ date:'', type:'eBay sale', description: r.order_number, net: r.ebay_net }];

        var docType = docTypeForRow(r);
        var isCN = docType === 'credit_note';

        state.pendingCreate = {
            orderNumber: r.order_number,
            ebayNet: r.ebay_net,
            lines: lines,
            parentSoId: hasSO ? r.dolibarr_order_id : null,
            action: docType,
            note: r.notes || '',
        };

        var modal = ensureModal('ebrCreateModal',
            '<div class="ebr-modal" style="width:520px;">'
            + '<div class="mhead" id="ebrCreateHead"></div>'
            + '<div class="mbody"><dl id="ebrCreateBody"></dl>'
            + '<div class="mnote" id="ebrCreateNote"></div>'
            + '<div id="ebrCreateErr" class="ebr-error" hidden></div></div>'
            + '<div class="mfoot"><button class="button" id="ebrCreateCancel">Cancel</button>'
            + '<button class="butAction" id="ebrCreateConfirm">Confirm</button></div>'
            + '</div>');
        document.getElementById('ebrCreateHead').innerHTML = isCN
            ? '<i class="fa fa-file-invoice-dollar"></i> Create credit note'
            : '<i class="fa fa-file-invoice"></i> Create missing invoice';
        document.getElementById('ebrCreateNote').textContent = isCN
            ? 'Confirm will create a credit note in Dolibarr (positive amount, issued to eBay — not applied to a source invoice), then validate it.'
            : 'Confirm will create the invoice in Dolibarr (one line per CSV row), then validate it.';

        var linesHtml = lines.map(function (l) {
            var n = Number(l.net || 0);
            var cls = n > 0 ? 'ebr-diff-pos' : (n < 0 ? 'ebr-diff-neg' : '');
            return '<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #eef3f5;">'
                + '<span><span class="ebr-sub">' + esc(l.date||'') + '</span> ' + esc(l.type||'') + ' <span class="ebr-sub">' + esc((l.description||'').slice(0,40)) + '</span></span>'
                + '<span class="' + cls + '">' + n.toFixed(2) + '</span>'
                + '</div>';
        }).join('');

        var willCreate = isCN
            ? '<strong style="color:#b3261e">Credit note</strong> for <strong>' + Math.abs(Number(r.ebay_net || 0)).toFixed(2) + '</strong>'
            : '<strong style="color:#1e8a4a">Invoice</strong> for <strong>' + fmt(r.ebay_net) + '</strong>';
        document.getElementById('ebrCreateBody').innerHTML =
            '<dt>Order</dt><dd><code>' + esc(r.order_number) + '</code></dd>' +
            '<dt>Status</dt><dd>' + r.status.replace(/_/g, ' ') + '</dd>' +
            '<dt>eBay type</dt><dd>' + esc(r.ebay_type || (r.ebay_types || []).join(', ') || '-') + '</dd>' +
            (hasSO
                ? '<dt>Linking to SO</dt><dd><code>' + esc(r.dolibarr_order_ref) + '</code></dd>'
                : '<dt>Customer</dt><dd>default eBay customer</dd>') +
            '<dt>Will create</dt><dd>' + willCreate + '</dd>' +
            '<dt>Lines (' + lines.length + ')</dt><dd><div style="max-height:140px;overflow:auto;">' + linesHtml + '</div></dd>';

        var confirmBtn = document.getElementById('ebrCreateConfirm');
        confirmBtn.onclick = confirmCreate;
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm';
        document.getElementById('ebrCreateCancel').onclick = function () { modal.classList.remove('open'); };
        document.getElementById('ebrCreateErr').hidden = true;
        modal.classList.add('open');
    }

    function confirmCreate() {
        if (!state.pendingCreate) return;
        var btn = document.getElementById('ebrCreateConfirm');
        btn.disabled = true; btn.textContent = 'Creating...';
        jpost('create_invoice', state.pendingCreate).then(function (data) {
            if (!data.ok) throw new Error(data.error || 'n8n returned ok=false');
            var target = state.results.find(function (x) { return x.order_number === state.pendingCreate.orderNumber; });
            if (target) {
                var act = data.action || 'invoice';
                target._adjusted = {
                    action: act,
                    newInvoiceId: data.newInvoiceId,
                    newInvoiceRef: data.newInvoiceRef,
                    applied: false,
                    dolibarrEditUrl: data.dolibarrEditUrl,
                };
                // Credit notes reduce the Dolibarr-side net (negative); invoices keep their sign.
                var signed = act === 'credit_note' ? -Math.abs(Number(data.totalHt || 0)) : Number(data.totalHt || 0);
                recalcRowAfterAdjustment(target, act, data.newInvoiceId, data.newInvoiceRef, Math.abs(Number(data.totalHt || 0)), signed);
            }
            showToast(data.message + ' <a href="' + data.dolibarrEditUrl + '" target="_blank">Open</a>', false);
            document.getElementById('ebrCreateModal').classList.remove('open');
            state.pendingCreate = null;
            render();
        }).catch(function (err) {
            document.getElementById('ebrCreateErr').textContent = err.message;
            document.getElementById('ebrCreateErr').hidden = false;
            btn.disabled = false; btn.textContent = 'Retry';
        });
    }

    // ---------- Bulk actions ----------

    function runBulkApprove() {
        var elig = eligibleMismatches().map(function (r) {
            var target = pickLargestInvoice(r);
            var diff = Number(r.diff);
            return {
                row: r,
                payload: {
                    action: approveActionForRow(r),
                    orderNumber: r.order_number,
                    parentInvoiceId: target.id,
                    amount: Math.abs(diff),
                    note: r.notes || '',
                },
            };
        });
        if (!elig.length) return;
        if (!confirm('Approve and process ' + elig.length + ' mismatch(es)?')) return;
        showToast('Processing ' + elig.length + '...', false);
        var done = 0, ok = 0, fail = 0;
        var CONCURRENCY = 3;
        var cursor = 0;
        function worker() {
            return new Promise(function (resolve) {
                function next() {
                    if (cursor >= elig.length) return resolve();
                    var item = elig[cursor++];
                    jpost('approve', item.payload).then(function (data) {
                        if (data.ok) { item.row._adjusted = data; ok++; } else { fail++; }
                    }).catch(function () { fail++; }).then(function () {
                        done++; render(); next();
                    });
                }
                next();
            });
        }
        Promise.all([worker(), worker(), worker()]).then(function () {
            showToast('Bulk approve done: ' + ok + ' ok, ' + fail + ' failed', fail > 0);
        });
    }

    function runBulkCreate() {
        var elig = eligibleCreates().map(function (r) {
            var hasSO = r.status === 'NO_LINKED_INVOICES';
            var lines = (r.ebay_lines && r.ebay_lines.length > 0)
                ? r.ebay_lines
                : [{ date: '', type: 'eBay sale', description: r.order_number, net: r.ebay_net }];
            return {
                row: r,
                payload: {
                    orderNumber: r.order_number,
                    ebayNet: r.ebay_net,
                    lines: lines,
                    parentSoId: hasSO ? r.dolibarr_order_id : null,
                    action: docTypeForRow(r),
                    note: r.notes || '',
                },
            };
        });
        if (!elig.length) return;
        if (!confirm('Create ' + elig.length + ' document(s)?')) return;
        showToast('Creating ' + elig.length + ' invoice(s)...', false);
        var ok = 0, fail = 0;
        var cursor = 0;
        function worker() {
            return new Promise(function (resolve) {
                function next() {
                    if (cursor >= elig.length) return resolve();
                    var item = elig[cursor++];
                    jpost('create_invoice', item.payload).then(function (data) {
                        if (data && data.ok) {
                            item.row._adjusted = {
                                action: data.action || 'invoice',
                                newInvoiceId: data.newInvoiceId,
                                newInvoiceRef: data.newInvoiceRef,
                                applied: false,
                                dolibarrEditUrl: data.dolibarrEditUrl,
                            };
                            ok++;
                        } else { fail++; }
                    }).catch(function () { fail++; }).then(function () {
                        render(); next();
                    });
                }
                next();
            });
        }
        Promise.all([worker(), worker(), worker()]).then(function () {
            showToast('Bulk create done: ' + ok + ' created, ' + fail + ' failed', fail > 0);
        });
    }

    function runBulkPay() {
        if (unresolvedRows().length > 0) {
            showToast('Resolve all mismatches / missing rows first.', true);
            return;
        }
        var elig = rowsToPay();
        if (!elig.length) return;
        openBulkPayModal(elig);
    }

    function openBulkPayModal(elig) {
        state.pendingBulkPay = elig.slice();
        var modal = ensureModal('ebrBulkPayModal',
            '<div class="ebr-modal" style="width:520px;">'
            + '<div class="mhead"><i class="fa fa-money-check-alt"></i> Pay all matched orders</div>'
            + '<div class="mbody"><dl id="ebrBulkPayBody"></dl>'
            + '<div class="mnote">Confirm will record payments in Dolibarr using this payout reference. Rows with no remaining balance will be skipped automatically.</div>'
            + '<div id="ebrBulkPayErr" class="ebr-error" hidden></div></div>'
            + '<div class="mfoot"><button class="button" id="ebrBulkPayCancel">Cancel</button>'
            + '<button class="butAction" id="ebrBulkPayConfirm">Confirm</button></div>'
            + '</div>');

        var totalRemain = elig.reduce(function (sum, row) {
            return sum + (row.invoices || []).reduce(function (inner, inv) {
                return inner + (inv.type === 'invoice' ? Number(inv.remain_to_pay || 0) : 0);
            }, 0);
        }, 0);
        document.getElementById('ebrBulkPayBody').innerHTML =
            '<dt>Payout</dt><dd><code>' + esc(state.payout.id) + '</code></dd>' +
            '<dt>Payout date</dt><dd>' + esc(state.payout.date || '-') + '</dd>' +
            '<dt>Orders to pay</dt><dd><strong>' + elig.length + '</strong></dd>' +
            '<dt>Estimated payable</dt><dd><strong>' + totalRemain.toFixed(2) + '</strong></dd>';

        var confirmBtn = document.getElementById('ebrBulkPayConfirm');
        confirmBtn.onclick = confirmBulkPay;
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm';
        document.getElementById('ebrBulkPayCancel').onclick = function () {
            modal.classList.remove('open');
            state.pendingBulkPay = null;
        };
        document.getElementById('ebrBulkPayErr').hidden = true;
        modal.classList.add('open');
    }

    function confirmBulkPay() {
        var elig = state.pendingBulkPay || [];
        if (!elig.length) return;
        var btn = document.getElementById('ebrBulkPayConfirm');
        btn.disabled = true;
        btn.textContent = 'Paying...';
        showToast('Paying ' + elig.length + '...', false);
        var done = 0, ok = 0, fail = 0, noop = 0;
        var cursor = 0;
        function worker() {
            return new Promise(function (resolve) {
                function next() {
                    if (cursor >= elig.length) return resolve();
                    var row = elig[cursor++];
                    var payload = {
                        orderNumber: row.order_number,
                        payoutId: state.payout.id,
                        payoutDateUnix: state.payout.date_unix,
                        note: row.notes || '',
                    };
                    jpost('pay', payload).then(function (data) {
                        row._paid = data;
                        // Three distinct outcomes:
                        //   - paid > 0:   real payment recorded → ok
                        //   - failed > 0: something errored in Dolibarr → fail
                        //   - paid = 0, failed = 0, skipped > 0: nothing to pay
                        //     (already paid or zero-balance invoice) → no-op
                        if (data && data.summary && data.summary.paid > 0) ok++;
                        else if (data && data.summary && data.summary.failed > 0) fail++;
                        else noop++;
                    }).catch(function (err) {
                        // Always mark the row as attempted, so it's removed from
                        // rowsToPay() and the bulk counter doesn't linger at "1"
                        // after a transient network/parse error.
                        row._paid = {
                            ok: false,
                            summary: { paid: 0, failed: 1, skipped: 0, totalPaid: 0 },
                            error: (err && err.message) ? err.message : 'unknown'
                        };
                        fail++;
                    }).then(function () {
                        done++; render(); next();
                    });
                }
                next();
            });
        }
        Promise.all([worker(), worker(), worker()]).then(function () {
            var modal = document.getElementById('ebrBulkPayModal');
            if (modal) modal.classList.remove('open');
            state.pendingBulkPay = null;
            if (ok > 0) savePayoutSummary().catch(function(){});
            var bits = [ok + ' paid'];
            if (fail > 0) bits.push(fail + ' failed');
            if (noop > 0) bits.push(noop + ' nothing to pay');
            showToast('Bulk pay done: ' + bits.join(', '), fail > 0);
        }).catch(function (err) {
            var errBox = document.getElementById('ebrBulkPayErr');
            if (errBox) {
                errBox.textContent = err && err.message ? err.message : 'Bulk pay failed';
                errBox.hidden = false;
            }
            btn.disabled = false;
            btn.textContent = 'Retry';
        });
    }

    function savePayoutSummary() {
        if (!state.payout || !state.payout.id) return Promise.resolve();
        var paidRows = state.results.filter(function (r) { return r._paid && r._paid.summary && r._paid.summary.paid > 0; });
        if (paidRows.length === 0) return Promise.resolve();
        var items = [];
        var totalPaid = 0;
        paidRows.forEach(function (r) {
            (r._paid.payments || []).forEach(function (p) {
                var amt = Number(p.amount || 0);
                totalPaid += amt;
                items.push({
                    orderNumber: r.order_number,
                    soRef: r.dolibarr_order_ref,
                    soId: r.dolibarr_order_id,
                    invoiceRef: p.invoiceRef,
                    invoiceId: p.invoiceId,
                    amount: Math.round(amt * 100) / 100,
                    paymentId: p.paymentId,
                });
            });
        });
        return jpost('save_payout', {
            payoutId: state.payout.id,
            payoutDate: state.payout.date,
            payoutMethod: state.payout.method,
            sourceFile: state.sourceFile,
            ordersCount: paidRows.length,
            paymentsCount: items.length,
            totalPaid: Math.round(totalPaid * 100) / 100,
            items: items,
        });
    }

    // ---------- Toast ----------

    function showToast(html, isError) {
        var prev = document.querySelector('.ebr-toast');
        if (prev) prev.remove();
        var t = document.createElement('div');
        t.className = 'ebr-toast' + (isError ? ' err' : '');
        t.innerHTML = html;
        document.body.appendChild(t);
        setTimeout(function () { t.remove(); }, isError ? 8000 : 6000);
    }

    function saveNote(orderNumber, note, el) {
        var row = state.results.find(function (x) { return x.order_number === orderNumber; });
        if (!row) return;
        row.notes = note;
        row._noteSaving = true;
        row._noteStatus = t('Saving', 'Saving...');
        row._noteStatusError = false;
        render();

        jpost('save_note', { orderNumber: orderNumber, note: note }).then(function (data) {
            if (!data.ok) throw new Error(data.error || 'save_note returned ok=false');
            row._noteSaving = false;
            row._noteStatus = t('Saved', 'Saved');
            row._noteStatusError = false;
            row._noteEditing = false;
            row._noteDraft = undefined;
            render();
            setTimeout(function () {
                if (row._noteStatus === t('Saved', 'Saved')) {
                    row._noteStatus = '';
                    render();
                }
            }, 1600);
        }).catch(function (err) {
            row._noteSaving = false;
            row._noteStatus = t('SaveFailed', 'Save failed') + ': ' + err.message;
            row._noteStatusError = true;
            render();
            if (el) el.focus();
        });
    }

    // ---------- Wiring ----------

    document.addEventListener('click', function (e) {
        var ap = e.target.closest('[data-approve]');
        if (ap) { e.preventDefault(); openApproveModal(ap.dataset.approve); return; }
        var cr = e.target.closest('[data-create]');
        if (cr) { e.preventDefault(); openCreateInvoiceModal(cr.dataset.create); return; }
        var noteEdit = e.target.closest('[data-note-edit]');
        if (noteEdit) {
            var rowEdit = state.results.find(function (x) { return x.order_number === noteEdit.dataset.noteEdit; });
            if (rowEdit) {
                rowEdit._noteEditing = true;
                rowEdit._noteDraft = rowEdit.notes || '';
                render();
            }
            return;
        }
        var noteCancel = e.target.closest('[data-note-cancel]');
        if (noteCancel) {
            var rowCancel = state.results.find(function (x) { return x.order_number === noteCancel.dataset.noteCancel; });
            if (rowCancel) {
                rowCancel._noteEditing = false;
                rowCancel._noteDraft = undefined;
                rowCancel._noteStatus = '';
                rowCancel._noteStatusError = false;
                render();
            }
            return;
        }
        var noteSave = e.target.closest('[data-note-save]');
        if (noteSave) {
            var rowSave = state.results.find(function (x) { return x.order_number === noteSave.dataset.noteSave; });
            if (rowSave) {
                saveNote(rowSave.order_number, rowSave._noteDraft || '', null);
            }
            return;
        }
        var chip = e.target.closest('.ebr-chip');
        if (chip) {
            document.querySelectorAll('.ebr-chip').forEach(function (c) { c.classList.remove('active'); });
            chip.classList.add('active');
            state.filter = chip.dataset.status;
            render();
            return;
        }
        var th = e.target.closest('#ebrTable th[data-key]');
        if (th) {
            var k = th.dataset.key;
            if (state.sortKey === k) state.sortDir *= -1;
            else { state.sortKey = k; state.sortDir = 1; }
            render();
            return;
        }
    });

    document.addEventListener('input', function (e) {
        var note = e.target.closest('.ebr-note-input');
        if (!note) return;
        var row = state.results.find(function (x) { return x.order_number === note.dataset.noteOrder; });
        if (!row) return;
        row._noteDraft = note.value;
    });

    var search = document.getElementById('ebrSearch');
    if (search) search.addEventListener('input', function (e) { state.query = e.target.value; render(); });

    var bA = document.getElementById('ebrBulkApprove');
    if (bA) bA.addEventListener('click', runBulkApprove);
    var bC = document.getElementById('ebrBulkCreate');
    if (bC) bC.addEventListener('click', runBulkCreate);
    var bP = document.getElementById('ebrBulkPay');
    if (bP) bP.addEventListener('click', runBulkPay);

    var dlCsv = document.getElementById('ebrDlCsv');
    if (dlCsv) dlCsv.addEventListener('click', downloadCsv);
    var dlJson = document.getElementById('ebrDlJson');
    if (dlJson) dlJson.addEventListener('click', downloadJson);

    function downloadCsv() {
        var cols = ["status","order_number","ebay_type","ebay_net","dolibarr_net","diff","dolibarr_order_ref","dolibarr_order_id","invoice_count","invoice_refs","invoice_amounts","notes"];
        function escCell(v) {
            if (v === null || v === undefined) return '';
            var s = String(v);
            return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
        }
        var lines = [cols.join(',')];
        state.results.forEach(function (r) {
            var invs = r.invoices || [];
            lines.push([
                r.status,
                r.order_number,
                r.ebay_type || (r.ebay_types || []).join(' / '),
                fmt(r.ebay_net),
                fmt(r.dolibarr_net),
                fmt(r.diff),
                r.dolibarr_order_ref || '',
                r.dolibarr_order_id || '',
                invs.length,
                invs.map(function(i){return i.ref || '';}).join('|'),
                invs.map(function(i){return fmt(i.total_ht);}).join('|'),
                r.notes || '',
            ].map(escCell).join(','));
        });
        var blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
        triggerDownload(blob, 'reconcile-report.csv');
    }
    function downloadJson() {
        var blob = new Blob([JSON.stringify(state.results, null, 2)], { type: 'application/json' });
        triggerDownload(blob, 'reconcile-report.json');
    }
    function triggerDownload(blob, filename) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    // Kick off first render
    render();
})();
