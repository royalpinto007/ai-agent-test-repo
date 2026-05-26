-- Indexes
ALTER TABLE llx_ebayreconcile_payout ADD INDEX idx_ebayreconcile_payout_payout_id (payout_id);
ALTER TABLE llx_ebayreconcile_payout ADD INDEX idx_ebayreconcile_payout_settled_at (settled_at);
