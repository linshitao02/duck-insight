# -*- coding: utf-8 -*-
"""把应用库里的 MySQL 语句转成 SQLite 能执行的写法。外部数据源仍走 MySQL。"""
import re


def placeholders(sql):
    """pymysql 的 %s / %% 转成 sqlite 的 ? / %。"""
    out = []
    i = 0
    while i < len(sql):
        if sql.startswith("%%", i):
            out.append("%")
            i += 2
        elif sql.startswith("%s", i):
            out.append("?")
            i += 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def quote_idents(sql):
    return re.sub(r"`([^`]+)`", r'"\1"', sql)


def dates(sql):
    def _shift(match):
        fn, n, unit = match.group(1).upper(), int(match.group(2)), match.group(3).lower()
        sign = "-" if fn == "DATE_SUB" else "+"
        unit = {"hour": "hours", "day": "days", "minute": "minutes"}.get(unit, unit + "s")
        return f"datetime('now', '{sign}{n} {unit}')"

    sql = re.sub(
        r"DATE_(SUB|ADD)\(\s*NOW\(\)\s*,\s*INTERVAL\s+(\d+)\s+(HOUR|DAY|MINUTE)S?\s*\)",
        _shift,
        sql,
        flags=re.I,
    )
    sql = re.sub(r"\bCURDATE\(\)", "date('now')", sql, flags=re.I)
    sql = re.sub(r"\bNOW\(\)", "datetime('now')", sql, flags=re.I)
    return sql


def adapt_sql(sql):
    """运行期 SQL：占位符、反引号、日期函数。"""
    return dates(quote_idents(placeholders(sql or "")))


_SHOW_COLUMNS = re.compile(r"^\s*SHOW\s+COLUMNS\s+FROM\s+[\"`]?([A-Za-z0-9_]+)[\"`]?", re.I)


def show_columns_table(sql):
    match = _SHOW_COLUMNS.match(sql or "")
    return match.group(1) if match else None


def adapt_type_ddl(ddl):
    text = re.sub(r"\s+COMMENT\s+'(?:\\'|[^'])*'", "", ddl or "", flags=re.I)
    text = re.sub(r"\s+ON UPDATE CURRENT_TIMESTAMP", "", text, flags=re.I)
    text = re.sub(r"\s+CHARACTER SET \w+", "", text, flags=re.I)
    text = re.sub(r"\s+COLLATE \w+", "", text, flags=re.I)
    text = re.sub(r"\bAUTO_INCREMENT\b", "", text, flags=re.I)
    text = re.sub(r"\bUNSIGNED\b", "", text, flags=re.I)
    for pattern, repl in (
        (r"\blongtext\b", "TEXT"),
        (r"\bmediumtext\b", "TEXT"),
        (r"\btinyint\b", "INTEGER"),
        (r"\bbigint\b", "INTEGER"),
        (r"\bsmallint\b", "INTEGER"),
        (r"\bvarchar\(\d+\)", "TEXT"),
        (r"\bdouble\b", "REAL"),
        (r"\bfloat\b", "REAL"),
        (r"\bdecimal\(\s*\d+\s*,\s*\d+\s*\)", "REAL"),
        (r"\bdatetime\b", "TEXT"),
        (r"\btimestamp\b", "TEXT"),
        (r"\bint\b", "INTEGER"),
    ):
        text = re.sub(pattern, repl, text, flags=re.I)
    return quote_idents(re.sub(r"\s+", " ", text).strip())


def _split_top(body):
    parts, buf, depth, quote = [], [], 0, False
    for ch in body:
        if ch == "'" and (not buf or buf[-1] != "\\"):
            quote = not quote
        elif not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                piece = "".join(buf).strip()
                if piece:
                    parts.append(piece)
                buf = []
                continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _rewrite_column(raw):
    text = adapt_type_ddl(raw)
    if re.search(r"\bAUTOINCREMENT\b", raw, re.I) or re.search(r"\bAUTO_INCREMENT\b", raw, re.I):
        name = text.split()[0]
        return f"{name} INTEGER PRIMARY KEY AUTOINCREMENT", True
    return text, False


def convert_create_table(stmt):
    """一条 MySQL CREATE TABLE 拆成 SQLite 建表和索引语句。"""
    text = re.sub(r"\)\s*ENGINE\s*=[\s\S]*$", ")", stmt.strip().rstrip(";"), flags=re.I)
    match = re.match(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+[\"`]?([A-Za-z0-9_]+)[\"`]?\s*\((.*)\)\s*$",
        text,
        flags=re.I | re.S,
    )
    if not match:
        return [adapt_sql(stmt)]
    table, body = match.group(1), match.group(2)
    columns, constraints, indexes = [], [], []
    auto_pk = False
    for part in _split_top(body):
        head = part.lstrip().upper()
        if head.startswith("PRIMARY KEY"):
            constraints.append(quote_idents(part))
        elif head.startswith("UNIQUE KEY") or head.startswith("UNIQUE INDEX"):
            cols = re.search(r"\((.*)\)\s*$", part, flags=re.S)
            if cols:
                constraints.append(f"UNIQUE ({quote_idents(cols.group(1))})")
        elif head.startswith("KEY") or head.startswith("INDEX"):
            named = re.match(
                r"(?:KEY|INDEX)\s+[\"`]?([A-Za-z0-9_]+)[\"`]?\s*\((.*)\)\s*$",
                part,
                flags=re.I | re.S,
            )
            if named:
                indexes.append((named.group(1), quote_idents(named.group(2))))
        else:
            column, is_auto = _rewrite_column(part)
            columns.append(column)
            auto_pk = auto_pk or is_auto
    if auto_pk:
        constraints = [
            item for item in constraints
            if not re.match(r'PRIMARY\s+KEY\s*\(\s*"?id"?\s*\)\s*$', item, flags=re.I)
        ]
    body_sql = ",\n  ".join(columns + constraints)
    statements = [f'CREATE TABLE IF NOT EXISTS "{table}" (\n  {body_sql}\n)']
    for name, cols in indexes:
        statements.append(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})')
    return statements


def convert_schema(sql_text):
    statements = []
    blob = "\n".join(
        line for line in sql_text.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    for stmt in (part.strip() for part in blob.split(";")):
        if not stmt:
            continue
        head = stmt.lstrip().lower()
        if head.startswith("create database") or head.startswith("use "):
            continue
        if head.startswith("create table"):
            statements.extend(convert_create_table(stmt))
        else:
            statements.append(adapt_sql(stmt))
    return statements
