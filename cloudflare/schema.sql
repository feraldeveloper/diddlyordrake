CREATE TABLE IF NOT EXISTS votes (
  voter_id TEXT PRIMARY KEY,
  choice TEXT NOT NULL CHECK (choice IN ('diddly', 'drake'))
);

-- Keep totals in two rows, avoiding a full vote-table scan on every page view.
CREATE TABLE IF NOT EXISTS vote_totals (
  choice TEXT PRIMARY KEY CHECK (choice IN ('diddly', 'drake')),
  count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0)
);
INSERT OR IGNORE INTO vote_totals (choice, count)
SELECT 'diddly', COUNT(*) FROM votes WHERE choice = 'diddly';
INSERT OR IGNORE INTO vote_totals (choice, count)
SELECT 'drake', COUNT(*) FROM votes WHERE choice = 'drake';

CREATE TRIGGER IF NOT EXISTS vote_insert AFTER INSERT ON votes
BEGIN
  UPDATE vote_totals SET count = count + 1 WHERE choice = NEW.choice;
END;

CREATE TRIGGER IF NOT EXISTS vote_change AFTER UPDATE OF choice ON votes
WHEN OLD.choice <> NEW.choice
BEGIN
  UPDATE vote_totals SET count = count - 1 WHERE choice = OLD.choice;
  UPDATE vote_totals SET count = count + 1 WHERE choice = NEW.choice;
END;

CREATE TRIGGER IF NOT EXISTS vote_delete AFTER DELETE ON votes
BEGIN
  UPDATE vote_totals SET count = count - 1 WHERE choice = OLD.choice;
END;
