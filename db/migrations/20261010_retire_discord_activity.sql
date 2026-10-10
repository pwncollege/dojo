BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DROP TABLE IF EXISTS public.discord_user_activity;
COMMIT;
