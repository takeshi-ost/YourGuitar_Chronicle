-- Initial staging state is closed; jobs and review reflection start disabled.
INSERT INTO settings VALUES (1, 'offline', 'Service setup is in progress.', 0);
INSERT INTO auto_crawl VALUES (1, 0, 'electric_acoustic', 1950, 1980, 3600, 0);
INSERT INTO review_settings VALUES (1, 0);
INSERT INTO backup_settings VALUES (1, 10);
INSERT INTO backup_schedules(target,enabled,interval_hours,generations,next_run)
SELECT target,0,24,10,0 FROM (VALUES ('chronicle'),('accounts'),('operations'),('authentication')) AS targets(target);
