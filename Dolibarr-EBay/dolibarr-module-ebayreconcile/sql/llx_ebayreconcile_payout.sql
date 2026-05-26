-- eBay Reconciliation — payout history table.
-- One row per settled payout (i.e. per successful "Pay all" run).
CREATE TABLE llx_ebayreconcile_payout (
    rowid               INTEGER AUTO_INCREMENT PRIMARY KEY,
    entity              INTEGER         NOT NULL DEFAULT 1,
    payout_id           VARCHAR(64)     NOT NULL,
    payout_date         DATE            NULL,
    payout_method       VARCHAR(255)    NULL,
    csv_filename        VARCHAR(255)    NULL,
    orders_count        INTEGER         NOT NULL DEFAULT 0,
    payments_count      INTEGER         NOT NULL DEFAULT 0,
    total_paid          DOUBLE(24,8)    NOT NULL DEFAULT 0,
    settled_at          DATETIME        NOT NULL,
    settled_by          INTEGER         NULL,           -- fk to llx_user.rowid
    summary_json        LONGTEXT        NULL,           -- full per-order payment list for the detail view
    date_creation       DATETIME        NOT NULL,
    tms                 TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=innodb DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
