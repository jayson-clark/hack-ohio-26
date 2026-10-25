"""Full-text search (sqlite FTS5): ranked, with highlighted snippets.

Every word must match, as a prefix ("calib" finds "calibration"), and the
porter stemmer folds "routes"/"routing". Matches in snippets are wrapped in
\x02...\x03 so clients can highlight them without trusting HTML.
"""

import re

HL_OPEN, HL_CLOSE = "\x02", "\x03"
WORD_RE = re.compile(r"[\w./:-]+", re.UNICODE)


def fts_query(text, any_word=False):
    """User text -> an FTS5 MATCH expression, or '' if there's nothing to search for."""
    words = []
    for w in WORD_RE.findall(text or ""):
        w = w.strip(".:-/")
        if w:
            words.append('"' + w.replace('"', "") + '"*')
    return (" OR " if any_word else " ").join(words)


def search_entries(db, text, kind=None, tag=None, user=None, archived=False, limit=50, any_word=False):
    match = fts_query(text, any_word)
    if not match:
        return []
    sql = f"""select e.*, snippet(entries_fts, 1, '{HL_OPEN}', '{HL_CLOSE}', '…', 24) as snippet,
                     highlight(entries_fts, 0, '{HL_OPEN}', '{HL_CLOSE}') as title_hl,
                     bm25(entries_fts, 6.0, 1.0, 3.0) as rank
              from entries_fts join entries e on e.id = entries_fts.rowid
              where entries_fts match ?"""
    args = [match]
    if not archived:
        sql += " and e.archived = 0"
    if kind:
        sql += " and e.kind = ?"
        args.append(kind)
    if tag:
        sql += " and (',' || e.tags || ',') like ?"
        args.append(f"%,{tag.lower()},%")
    if user:
        sql += " and e.author_user = ?"
        args.append(user)
    sql += " order by rank limit ?"
    args.append(int(limit))
    return db.q(sql, args)


def search_messages(db, text, channel=None, limit=30):
    match = fts_query(text)
    if not match:
        return []
    sql = f"""select m.*, snippet(messages_fts, 0, '{HL_OPEN}', '{HL_CLOSE}', '…', 24) as snippet,
                     bm25(messages_fts) as rank
              from messages_fts join messages m on m.id = messages_fts.rowid
              where messages_fts match ?"""
    args = [match]
    if channel:
        sql += " and m.channel = ?"
        args.append(channel)
    sql += " order by rank limit ?"
    args.append(int(limit))
    return db.q(sql, args)
