-- RFC v7 names the decision record table `fraud_analysis`.
-- This migration preserves existing rows, primary keys and the rule_hits FK.
DO $$
BEGIN
    IF to_regclass('public.pix_decisions') IS NOT NULL
       AND to_regclass('public.fraud_analysis') IS NULL THEN
        ALTER TABLE public.pix_decisions RENAME TO fraud_analysis;
    END IF;
END;
$$;
