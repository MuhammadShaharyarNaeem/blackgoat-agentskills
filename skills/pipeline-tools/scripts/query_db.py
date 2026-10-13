#!/usr/bin/env python3
"""Run one validated, read-only SELECT against a DEV SQL Server database.

The connection string comes from Azure App Configuration (optionally through a
Key Vault reference) and lives only in memory: it is never written to disk,
printed, logged or put in argv; the password reaches sqlcmd through the child
environment (SQLCMDPASSWORD). Pure standard library.

Usage:
    python query_db.py --app-config <name> --key <key> [--label <label>]
                       (--query "<sql>" | --file <path.sql>)
                       [--format table|csv|json] [--max-rows N] [--timeout S]
    python query_db.py --self-test
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FORMATS = ("table", "csv", "json")
SEP = "\x1f"  # sqlcmd -s column separator (ASCII unit separator)
META, COL, END = "__qdb_meta__", "__qdb_col__", "__qdb_end__"
SQLCMD_DEFAULT = (r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170"
                  r"\Tools\Binn\SQLCMD.EXE")
MULTI_ROW_PREFIXES = ("JSON_F52E2B61", "XML_F52E2B61")  # FOR JSON / FOR XML

DENY = frozenset("""
INSERT UPDATE DELETE MERGE TRUNCATE DROP ALTER CREATE GRANT REVOKE DENY EXEC
EXECUTE INTO DECLARE SET USE BEGIN COMMIT ROLLBACK SAVE BACKUP RESTORE DBCC
KILL SHUTDOWN RECONFIGURE WAITFOR BULK OPENROWSET OPENQUERY OPENDATASOURCE
OPENXML WRITETEXT UPDATETEXT READTEXT RAISERROR THROW DISABLE ENABLE RECEIVE
SEND CHECKPOINT SETUSER ADD MOVE GET
""".split())
STATEMENT_VERBS = frozenset(("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE"))
WORD_CHARS = re.compile(r"[A-Za-z0-9_@#$]")
# sqlcmd commands it honours at a line start with OR without ':' (osql
# compatibility): ':anything', '!!cmd' (OS shell), GO [n], RESET, ED, EXIT[(..)],
# QUIT. The command word must end at a non-word char, so 'GoLive' passes.
SQLCMD_LINE = re.compile(
    r"^\s*(:|!!|(?:GO|RESET|ED|EXIT|QUIT)(?![A-Za-z0-9_@#$]))", re.IGNORECASE)


class Refused(Exception):
    """A guardrail refusal -- exit 1, nothing executed."""


class SetupError(Exception):
    """az/sqlcmd/connection/SQL failure -- exit 2."""


# ---------------------------------------------------------------- validator
def tokenize(sql):
    """Return (tokens, sanitized). tokens: [(kind, text)] with kind in
    word | string | ident | semi | punct. sanitized: the text with every
    comment replaced by one space, literals untouched. Raises Refused."""
    tokens, out, i, n = [], [], 0, len(sql)
    while i < n:
        c = sql[i]
        two = sql[i:i + 2]
        if two == "--":
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" ")
            i = j
        elif two == "/*":
            depth, j = 1, i + 2
            while j < n and depth:
                if sql[j:j + 2] == "/*":
                    depth, j = depth + 1, j + 2
                elif sql[j:j + 2] == "*/":
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise Refused("unterminated /* comment")
            out.append(" ")
            i = j
        elif c in "'\"[":
            close = {"'": "'", '"': '"', "[": "]"}[c]
            j = i + 1
            while True:
                k = sql.find(close, j)
                if k < 0:
                    raise Refused("unterminated %s literal or identifier" % c)
                if sql[k + 1:k + 2] == close:  # '' "" ]] escapes
                    j = k + 2
                    continue
                break
            text = sql[i:k + 1]
            tokens.append(("string" if c == "'" else "ident", text))
            out.append(text)
            i = k + 1
        elif WORD_CHARS.match(c):
            j = i
            while j < n and WORD_CHARS.match(sql[j]):
                j += 1
            word = sql[i:j]
            if word.upper() == "N" and sql[j:j + 1] == "'":
                out.append(word)  # N'...' -- the quote is read next pass
            else:
                tokens.append(("word", word))
                out.append(word)
            i = j
        else:
            if c == ";":
                tokens.append(("semi", c))
            elif not c.isspace():
                tokens.append(("punct", c))
            out.append(c)
            i += 1
    return tokens, "".join(out)


def check_lines(text):
    """Refuse a line sqlcmd would read as a command. Run on the RAW text too:
    sqlcmd scans physical lines before T-SQL parsing, so a command line inside
    a multi-line '...' literal or /* */ comment still executes."""
    for line in text.splitlines():
        m = SQLCMD_LINE.match(line)
        if not m:
            continue
        if m.group(1) == ":":
            raise Refused("a line starting with ':' (sqlcmd command)")
        raise Refused("a line starting with sqlcmd command %s"
                      % m.group(1).upper())


def validate(sql):
    """Return the sanitized single SELECT (no trailing ';'). Raises Refused."""
    if not sql or not sql.strip():
        raise Refused("empty query")
    if "$(" in sql:
        raise Refused("'$(' (sqlcmd variable)")
    check_lines(sql)
    tokens, sanitized = tokenize(sql)
    check_lines(sanitized)
    semis = [i for i, t in enumerate(tokens) if t[0] == "semi"]
    if semis and (len(semis) > 1 or semis[0] != len(tokens) - 1):
        raise Refused("more than one statement (';' before the end)")
    if semis:
        sanitized = sanitized[:sanitized.rindex(";")]
        tokens = tokens[:-1]
    words = [t[1].upper() for t in tokens if t[0] == "word"]
    for i, (kind, text) in enumerate(tokens):
        name = text.strip("[]\"").lower() if kind in ("word", "ident") else ""
        if name.startswith(("sp_", "xp_")):
            raise Refused("system procedure identifier %r" % text)
        if kind == "word" and text.upper() in DENY:
            raise Refused("denied keyword %s" % text.upper())
    if ("NEXT", "VALUE", "FOR") in zip(words, words[1:], words[2:]):
        raise Refused("NEXT VALUE FOR (advances a sequence)")
    if not tokens or tokens[0][0] != "word":
        raise Refused("first keyword must be SELECT or WITH")
    first = tokens[0][1].upper()
    if first == "WITH":
        depth, verb = 0, None
        for kind, text in tokens[1:]:
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
            elif depth == 0 and kind == "word" and text.upper() in STATEMENT_VERBS:
                verb = text.upper()
                break
        if verb != "SELECT":
            raise Refused("WITH must end in a top-level SELECT")
    elif first != "SELECT":
        raise Refused("first keyword must be SELECT or WITH, not %s" % first)
    return sanitized.strip()


# -------------------------------------------------------- connection string
def parse_conn(conn):
    """ADO.NET 'k=v;k=v' -> {lowercased key: value}, honouring quoted values."""
    out, i, n = {}, 0, len(conn)
    while i < n:
        eq = conn.find("=", i)
        if eq < 0:
            break
        key = conn[i:eq].strip().lower()
        j = eq + 1
        while j < n and conn[j] == " ":
            j += 1
        if j < n and conn[j] in "'\"":
            q, k, buf = conn[j], j + 1, []
            while k < n:
                if conn[k] == q and conn[k + 1:k + 2] == q:
                    buf.append(q)
                    k += 2
                elif conn[k] == q:
                    break
                else:
                    buf.append(conn[k])
                    k += 1
            value = "".join(buf)
            end = conn.find(";", k)
        else:
            end = conn.find(";", j)
            value = conn[j:end if end >= 0 else n].strip()
        if key:
            out[key] = value
        i = n if end < 0 else end + 1
    return out


def pick(parts, *names):
    for name in names:
        if parts.get(name):
            return parts[name]
    return ""


def connection_target(parts):
    server = pick(parts, "server", "data source", "address", "addr",
                  "network address")
    database = pick(parts, "database", "initial catalog")
    if not server:
        raise SetupError("connection string has no Server/Data Source")
    host = re.sub(r"^(tcp|np|lpc):", "", server, flags=re.IGNORECASE)
    host = re.split(r"[,\\]", host)[0].strip()
    return server, host, database


def dev_guard(host, database):
    if "dev" not in host.lower() and "dev" not in (database or "").lower():
        raise Refused("not a DEV target: neither server host %r nor database "
                      "%r contains 'dev'" % (host, database))


def build_sqlcmd(sqlcmd, parts, server, database, query_file, timeout):
    """Return (argv, env-additions). The password is only ever in env."""
    argv = [sqlcmd, "-S", server, "-x", "-K", "ReadOnly", "-N",
            "-b", "-r", "1", "-t", str(timeout), "-l", "30", "-h", "-1",
            "-y", "8000", "-s", SEP, "-f", "65001", "-i", str(query_file)]
    if database:
        argv[3:3] = ["-d", database]
    auth = pick(parts, "authentication").lower().replace(" ", "")
    user = pick(parts, "user id", "uid", "user", "username")
    password = pick(parts, "password", "pwd")
    integrated = pick(parts, "integrated security", "trusted_connection").lower()
    env = {}
    if auth in ("activedirectorypassword",):
        argv += ["-G", "-U", user]
        env["SQLCMDPASSWORD"] = password
    elif auth in ("activedirectoryintegrated",):
        argv += ["-G"]
    elif auth not in ("", "sqlpassword"):
        raise SetupError("Authentication=%s is not supported by sqlcmd v15 here"
                         % pick(parts, "authentication"))
    elif integrated in ("true", "yes", "sspi"):
        argv += ["-E"]
    elif user:
        argv += ["-U", user]
        env["SQLCMDPASSWORD"] = password
    else:
        raise SetupError("connection string has no User ID and no integrated auth")
    return argv, env


def wrap(query, max_rows):
    literal = query.replace("'", "''")
    return (
        "SET NOCOUNT ON;\n"
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED;\n"
        "SELECT N'%s', @@SERVERNAME, DB_NAME();\n"
        "SELECT N'%s', column_ordinal, name FROM "
        "sys.dm_exec_describe_first_result_set(N'%s', NULL, 0) "
        "ORDER BY column_ordinal;\n"
        "BEGIN TRAN;\n"
        "SET ROWCOUNT %d;\n"
        "%s\n;\n"
        "SET ROWCOUNT 0;\n"
        "ROLLBACK TRAN;\n"
        "SELECT N'%s';\n" % (META, COL, literal, max_rows, query, END))


# ---------------------------------------------------------------- execution
def default_runner(argv, env=None, timeout=None):
    full = dict(os.environ)
    full.update(env or {})
    try:
        p = subprocess.run(argv, capture_output=True, env=full, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SetupError("%s timed out after %ss" % (Path(argv[0]).name, timeout))
    except OSError as exc:
        raise SetupError("could not start %s: %s" % (Path(argv[0]).name, exc))
    decode = lambda b: b.decode("utf-8", errors="replace")  # noqa: E731
    return p.returncode, decode(p.stdout), decode(p.stderr)


def az_value(runner, az, args, what):
    code, out, err = runner([az] + args + ["--query", "value", "-o", "tsv"],
                            timeout=120)
    if code != 0:
        raise SetupError("%s failed (exit %d): %s -- run 'az login' first if "
                         "not signed in" % (what, code, err.strip()[-300:]))
    value = out.strip()
    if not value:
        raise SetupError("%s returned an empty value" % what)
    return value


def fetch_conn(runner, app_config, key, label):
    az = shutil.which("az")
    if not az:
        raise SetupError("az CLI not found on PATH")
    args = ["appconfig", "kv", "show", "--name", app_config, "--key", key]
    if label:
        args += ["--label", label]
    conn = az_value(runner, az, args, "az appconfig kv show (%s)" % key)
    if conn.startswith("{") and '"uri"' in conn:
        try:
            uri = json.loads(conn)["uri"]
        except (ValueError, KeyError, TypeError):
            raise SetupError("malformed Key Vault reference in %s" % key)
        conn = az_value(runner, az, ["keyvault", "secret", "show", "--id", uri],
                        "az keyvault secret show (reference in %s)" % key)
    return conn


def split_rows(lines, ncols):
    """Join physical lines into logical rows of ncols fields."""
    rows, buf = [], None
    for line in lines:
        if buf is None and ncols > 1 and not line.strip():
            continue  # a blank line between rows, not part of a value
        if buf is None and ncols > 1 and SEP not in line and rows:
            rows[-1] += "\n" + line  # a newline inside the last column
            continue
        buf = line if buf is None else buf + "\n" + line
        if buf.count(SEP) >= ncols - 1:
            rows.append(buf)
            buf = None
    if buf is not None:
        rows.append(buf)
    return rows


def parse_output(stdout):
    lines = stdout.replace("\r\n", "\n").split("\n")
    meta = next((i for i, l in enumerate(lines) if l.startswith(META + SEP)), None)
    end = max((i for i, l in enumerate(lines) if l.strip() == END), default=None)
    if meta is None or end is None or end < meta:
        raise SetupError("could not parse sqlcmd output (markers missing)")
    _, server, database = [f.strip() for f in lines[meta].split(SEP)][:3]
    columns, i = [], meta + 1
    while i < end and (not lines[i].strip() or lines[i].startswith(COL + SEP)):
        if lines[i].strip():
            fields = [f.strip() for f in lines[i].split(SEP)]
            columns.append(fields[2] if fields[2] != "NULL" else
                           "col%s" % fields[1])
        i += 1
    if not columns:
        raise SetupError("could not describe the result set's columns")
    body = lines[i:end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    data = []
    for row in split_rows(body, len(columns)):
        fields = [f.strip() for f in row.split(SEP)][:len(columns)]
        fields += [""] * (len(columns) - len(fields))
        data.append([None if f == "NULL" else f for f in fields])
    if len(columns) == 1 and columns[0].startswith(MULTI_ROW_PREFIXES) and data:
        data = [["".join(r[0] or "" for r in data)]]
    return (server if server != "NULL" else None,
            database if database != "NULL" else None, columns, data)


def run_query(sql, args, runner):
    """Validate, fetch, guard, execute. Returns (server, database, cols, data)."""
    query = validate(sql)  # before any az or sqlcmd call
    sqlcmd = shutil.which("sqlcmd") or (
        SQLCMD_DEFAULT if Path(SQLCMD_DEFAULT).is_file() else None)
    if not sqlcmd:
        raise SetupError("sqlcmd not found on PATH")
    parts = parse_conn(fetch_conn(runner, args.app_config, args.key, args.label))
    server, host, database = connection_target(parts)
    try:
        dev_guard(host, database)
    except Refused as exc:
        exc.target = (host, database)
        raise
    tmp = tempfile.mkdtemp(prefix="query_db_")
    try:
        qfile = Path(tmp) / "q.sql"
        qfile.write_text(wrap(query, args.max_rows), encoding="utf-8")
        argv, env = build_sqlcmd(sqlcmd, parts, server, database, qfile,
                                 args.timeout)
        code, out, err = runner(argv, env=env, timeout=args.timeout + 60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if code != 0:
        raise SetupError("sqlcmd exit %d: %s" % (code, (err or out).strip()[-1500:]))
    return parse_output(out)


# ---------------------------------------------------------------------- CLI
class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


PURPOSE = ("Runs one validated read-only SELECT against a DEV SQL Server "
           "database whose connection string lives in Azure App Configuration.")

EPILOG = """\
Reads:
  The App Configuration key (az appconfig kv show); a Key Vault reference
  value ({"uri": ...}) is resolved with az keyvault secret show. The
  connection string stays in memory: never on disk, printed, logged or in
  argv. The password reaches sqlcmd only as SQLCMDPASSWORD in the child env.
  Auth: SQL login; Integrated Security -> -E; Active Directory Password /
  Integrated -> -G; any other Authentication= value is exit 2.

Writes:
  Only a temp file in a private temp dir holding the wrapped query (never
  the connection string), deleted after sqlcmd exits.

Guards (checked BEFORE any az or sqlcmd call; failure = exit 1, refused):
  comments stripped and '..' N'..' ".." [..] treated as opaque (unterminated
  = refused); one statement, at most one trailing ';'; no '$('; no line,
  raw or comment-stripped, even inside a literal, whose first token is a
  sqlcmd command with or without ':' -- ':', '!!', GO, RESET, ED, EXIT, QUIT
  (case-insensitive; 'GoLive' passes); first keyword SELECT, or WITH ending
  in a top-level SELECT; denied words outside literals: INSERT UPDATE DELETE
  MERGE TRUNCATE DROP ALTER CREATE GRANT REVOKE DENY EXEC EXECUTE INTO
  DECLARE SET USE BEGIN COMMIT ROLLBACK SAVE BACKUP RESTORE DBCC KILL
  SHUTDOWN RECONFIGURE WAITFOR BULK OPENROWSET OPENQUERY OPENDATASOURCE
  OPENXML WRITETEXT UPDATETEXT READTEXT RAISERROR THROW DISABLE ENABLE
  RECEIVE SEND CHECKPOINT SETUSER ADD MOVE GET, NEXT VALUE FOR, any sp_/xp_
  identifier. FOR JSON/XML are allowed. Bracket an identifier that collides
  with a denied word ([Update]); move a line-leading alias like 'ed.' or
  'go,' onto the previous line.
  DEV only, no override: the server host or database name must contain
  'dev'. Execution wraps the query in SET NOCOUNT ON, SET ROWCOUNT
  <max-rows>, READ COMMITTED, BEGIN TRAN ... ROLLBACK TRAN, with sqlcmd
  -x -K ReadOnly -N -b. No -X: it disables SQLCMDPASSWORD, the only
  secret-safe password channel, so the command-line refusal above is the
  ONLY guard against sqlcmd commands. These are SCRIPT-LEVEL guards: the only
  hard guarantee is a read-only database login.

Output:
  sqlcmd runs with -h -1 -y 8000 and separator U+001F; columns come from
  sys.dm_exec_describe_first_result_set. Values are text, trimmed, cut at
  8000 chars; NULL -> null (a literal 'NULL' string is indistinguishable).
  FOR JSON/XML chunks are re-joined into one value.
  --format json (default): the JSON report on stdout, data included.
  --format table|csv: the data on stdout (success only); the JSON report,
  data null, on stderr at every exit.

JSON keys:
  ok, server, database, rows, columns, data, refused, error. server/database
  are @@SERVERNAME/DB_NAME() once connected, the parsed host/database on a
  DEV refusal, otherwise null. data is a list of rows aligned to columns.

Exit codes:
  0  the SELECT ran; data returned.
  1  refused: a guard above, or not a DEV target. Nothing executed.
  2  setup/runtime failure: az or sqlcmd missing or failing (try az login),
     key not found, unsupported auth, SQL error, unparseable output.

Self-test:
  python query_db.py --self-test   (no network, no database)
"""


def report(**kw):
    base = {"ok": False, "server": None, "database": None, "rows": 0,
            "columns": [], "data": None, "refused": None, "error": None}
    base.update(kw)
    return base


def render(columns, data, fmt):
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([["" if v is None else v for v in r] for r in data])
        return buf.getvalue()
    cells = [columns] + [["NULL" if v is None else v for v in r] for r in data]
    widths = [max(len(str(r[i])) for r in cells) for i in range(len(columns))]
    lines = [" | ".join(str(v).ljust(w) for v, w in zip(r, widths)) for r in cells]
    lines.insert(1, "-+-".join("-" * w for w in widths))
    return "\n".join(lines) + "\n"


def main(argv, runner=default_runner, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    parser = PurposeFirstParser(
        prog="query_db.py", description=PURPOSE, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-config", help="App Configuration store name")
    parser.add_argument("--key", help="key holding the connection string")
    parser.add_argument("--label", help="key label (optional)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--query", help="the SELECT to run")
    group.add_argument("--file", help="path to a .sql file holding the SELECT")
    parser.add_argument("--format", default="json", choices=FORMATS)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=60,
                        help="query timeout in seconds")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in tests and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()

    def emit(rep, code):
        if args.format == "json":
            print(json.dumps(rep, indent=2), file=out)
        else:
            if code == 0:
                out.write(render(rep["columns"], rep.pop("data"), args.format))
            rep["data"] = None
            print(json.dumps(rep, indent=2), file=err)
        return code

    missing = [f for f, v in (("--app-config", args.app_config),
                              ("--key", args.key)) if not v]
    if not (args.query or args.file):
        missing.append("--query or --file")
    if missing:
        return emit(report(error="missing required argument(s): "
                           + ", ".join(missing)), 2)
    if args.max_rows < 1 or args.timeout < 1:
        return emit(report(error="--max-rows and --timeout must be >= 1"), 2)
    sql = args.query
    if args.file:
        try:
            sql = Path(args.file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            return emit(report(error="cannot read --file: %s" % exc), 2)
    try:
        server, database, columns, data = run_query(sql, args, runner)
    except Refused as exc:
        host, db = getattr(exc, "target", (None, None))
        return emit(report(server=host, database=db, refused=str(exc)), 1)
    except SetupError as exc:
        return emit(report(error=str(exc)), 2)
    return emit(report(ok=True, server=server, database=database,
                       rows=len(data), columns=columns, data=data), 0)


# ---------------------------------------------------------------- self-test
def run_self_test():
    CONN = ("Server=tcp:gorelo-dev-sql.database.windows.net,1433;"
            "Initial Catalog=Gorelo;Persist Security Info=False;"
            "User ID=reader;Password=\"s3cr;et\"\"pw\";Encrypt=True;")
    SECRET = 's3cr;et"pw'

    def fake_output(cols, rows):
        lines = [SEP.join([META, "gorelo-dev-sql", "Gorelo"]), ""]
        lines += [SEP.join([COL, str(i + 1), c]) for i, c in enumerate(cols)]
        lines += [""] + [SEP.join(r) for r in rows] + ["", END]
        return "\r\n".join(lines) + "\r\n"

    class Stub:
        def __init__(self, conn=CONN, sql_out=None, az_code=0, sql_code=0,
                     kv=None):
            self.calls, self.conn, self.kv = [], conn, kv
            self.sql_out = sql_out or fake_output(["name"], [["A"], ["B"]])
            self.az_code, self.sql_code = az_code, sql_code
            self.query_text = None

        def __call__(self, argv, env=None, timeout=None):
            self.calls.append((list(argv), dict(env or {})))
            if "appconfig" in argv:
                return self.az_code, self.conn + "\n", "ERROR: not logged in"
            if "keyvault" in argv:
                return 0, (self.kv or "") + "\n", ""
            self.query_text = Path(argv[argv.index("-i") + 1]).read_text(
                encoding="utf-8")
            return self.sql_code, self.sql_out, "Msg 208: Invalid object"

    def call(argv, stub):
        o, e = io.StringIO(), io.StringIO()
        code = main(argv, runner=stub, out=o, err=e)
        return code, o.getvalue(), e.getvalue()

    BASE = ["--app-config", "gorelo-dev", "--key", "K", "--label", "usw"]

    class ValidatorTests(unittest.TestCase):
        def ok(self, sql):
            return validate(sql)

        def no(self, sql, fragment=""):
            with self.assertRaises(Refused) as ctx:
                validate(sql)
            self.assertIn(fragment, str(ctx.exception))

        def test_accepted(self):
            for sql in (
                    "SELECT 1",
                    "select top 5 name from sys.tables order by name",
                    "WITH c AS (SELECT 1 AS x), d (y) AS (SELECT x FROM c) "
                    "SELECT * FROM d",
                    "SELECT 'DROP TABLE x; --' AS s",
                    "SELECT N'it''s EXEC' AS s",
                    "SELECT [Update], \"Delete\" FROM [dbo].[T]",
                    "SELECT id FROM t FOR JSON PATH",
                    "SELECT id FROM t FOR XML AUTO",
                    "SELECT 1;",
                    "SELECT 1 -- trailing comment; DROP\n",
                    "SELECT a /* outer /* nested */ still */ FROM t",
                    "SELECT [a]]b] FROM t",
                    "SELECT DATEADD(day, -1, GETDATE()) AS d",
                    "SELECT [Send] FROM t",
                    "SELECT 'checkpoint' AS x",
                    "SELECT * FROM t WHERE note = 'exit'",
                    "SELECT id,\n  GoLive,\n  EDate, Quitter FROM t",
                    "SELECT 1 AS a\n  WHERE 1 != 2"):
                with self.subTest(sql=sql):
                    self.ok(sql)

        def test_comments_removed_in_executed_text(self):
            self.assertEqual(self.ok("SELECT 1 /* x */ -- y\n;"), "SELECT 1")

        def test_each_deny_keyword(self):
            for word in sorted(DENY):
                self.no("SELECT 1 AS a WHERE 1 = 1 %s x" % word.lower(),
                        "denied keyword " + word)

        def test_refused(self):
            cases = {
                "SELECT * INTO #t FROM x": "INTO",
                "SELECT 1; SELECT 2": "more than one statement",
                "SELECT 1;;": "more than one statement",
                "SELECT 1\nGO\n": "GO",
                "SELECT 1\n go 5\n": "GO",
                "SELECT 1\n:!! dir\n": "':'",
                "SELECT '$(var)'": "$(",
                "SELECT 1 /* a /* b */ */ DROP TABLE x": "DROP",
                "SELECT 1 /* a /* b */ DROP TABLE x": "unterminated",
                "SELECT 'abc": "unterminated",
                "SELECT [abc": "unterminated",
                "exec sp_who": "EXEC",
                "sp_who": "sp_who",
                "SELECT 1 exec x": "EXEC",
                "SELECT * FROM sys.sp_who": "sp_who",
                "SELECT * FROM [xp_cmdshell]": "xp_cmdshell",
                "SELECT NEXT VALUE FOR dbo.seq": "NEXT VALUE FOR",
                "WITH c AS (SELECT 1 AS x) DELETE FROM c": "DELETE",
                "UPDATE x SET y = 1": "UPDATE",
                "(SELECT 1)": "first keyword",
                "VALUES (1)": "first keyword",
                "": "empty",
                "SELECT 1\n/**/GO\n": "GO",
                # sqlcmd commands honoured without ':' (osql compatibility)
                "SELECT 1\n!! whoami": "!!",
                "SELECT 1\nRESET\nDISABLE TRIGGER trg ON dbo.t": "RESET",
                "SELECT 1\nQUIT": "QUIT",
                "SELECT 1\nEXIT(SELECT 1)": "EXIT",
                "SELECT 1\ngo 5": "GO",
                "SELECT 1\n  Go": "GO",
                "SELECT 1\n!!dir": "!!",
                "SELECT 1\n:!!": "':'",
                "SELECT 1\nexit": "EXIT",
                "SELECT 1\n\tED": "ED",
                "SELECT 'a\n!! whoami\n' AS s": "!!",  # raw line in a literal
                "SELECT 1 /*\nQUIT\n*/": "QUIT",
                # side-effecting keywords
                "SELECT 1\nRAISERROR('x', 10, 1) WITH LOG": "RAISERROR",
                "DISABLE TRIGGER ALL ON DATABASE": "DISABLE",
                "RECEIVE TOP(1) * FROM q": "RECEIVE",
                "CHECKPOINT": "CHECKPOINT",
                "SETUSER": "SETUSER",
                "ADD SENSITIVITY CLASSIFICATION TO dbo.t.c WITH "
                "(LABEL = 'x')": "ADD",
            }
            for sql, fragment in cases.items():
                with self.subTest(sql=sql):
                    self.no(sql, fragment)

        def test_with_requires_select(self):
            with self.assertRaises(Refused):
                validate("WITH c AS (SELECT 1 AS x) TABLE c")

    class ConnectionTests(unittest.TestCase):
        def test_parse_quoted_and_aliases(self):
            p = parse_conn(CONN)
            self.assertEqual(p["password"], SECRET)
            self.assertEqual(p["user id"], "reader")
            server, host, db = connection_target(p)
            self.assertEqual(host, "gorelo-dev-sql.database.windows.net")
            self.assertEqual(db, "Gorelo")
            p = parse_conn("Data Source=srv\\inst;Database=AppDev;UID=u;PWD=p")
            self.assertEqual(connection_target(p)[1:], ("srv", "AppDev"))

        def test_dev_guard(self):
            dev_guard("gorelo-dev-sql.x", "Prod")
            dev_guard("sql-main", "App_DEV")
            with self.assertRaises(Refused):
                dev_guard("gorelo-prod-sql.database.windows.net", "Gorelo")

        def test_password_never_in_argv(self):
            p = parse_conn(CONN)
            argv, env = build_sqlcmd("sqlcmd", p, "srv", "db", "q.sql", 60)
            self.assertNotIn(SECRET, " ".join(argv))
            self.assertNotIn("-P", argv)
            self.assertEqual(env, {"SQLCMDPASSWORD": SECRET})
            for flag in ("-K", "-N", "-b", "-x"):
                self.assertIn(flag, argv)
            self.assertNotIn("-X", argv)  # -X would disable SQLCMDPASSWORD
            self.assertEqual(argv[argv.index("-K") + 1], "ReadOnly")
            self.assertEqual(argv[argv.index("-t") + 1], "60")

        def test_auth_mapping(self):
            p = parse_conn("Server=s;Authentication=Active Directory Password;"
                           "User ID=u;Password=p")
            argv, env = build_sqlcmd("sqlcmd", p, "s", "", "q", 5)
            self.assertIn("-G", argv)
            self.assertEqual(env["SQLCMDPASSWORD"], "p")
            argv, env = build_sqlcmd("sqlcmd", parse_conn(
                "Server=s;Integrated Security=SSPI"), "s", "", "q", 5)
            self.assertIn("-E", argv)
            with self.assertRaises(SetupError):
                build_sqlcmd("sqlcmd", parse_conn(
                    "Server=s;Authentication=Active Directory Interactive"),
                    "s", "", "q", 5)

    class FlowTests(unittest.TestCase):
        def setUp(self):
            self.which = shutil.which
            shutil.which = lambda name: name  # pretend az and sqlcmd exist

        def tearDown(self):
            shutil.which = self.which

        def test_refusal_makes_no_call(self):
            stub = Stub()
            code, out, _ = call(BASE + ["--query", "UPDATE x SET y=1"], stub)
            self.assertEqual(code, 1)
            self.assertIn("UPDATE", json.loads(out)["refused"])
            self.assertEqual(stub.calls, [])

        def test_happy_path_json(self):
            stub = Stub(sql_out=fake_output(
                ["id", "note"], [["1", "a\nb"], ["2", "NULL"]]))
            code, out, _ = call(BASE + ["--query", "SELECT id, note FROM t;"],
                                stub)
            rep = json.loads(out)
            self.assertEqual(code, 0, rep)
            self.assertEqual(rep["columns"], ["id", "note"])
            self.assertEqual(rep["data"], [["1", "a\nb"], ["2", None]])
            self.assertEqual((rep["server"], rep["database"], rep["rows"]),
                             ("gorelo-dev-sql", "Gorelo", 2))
            argv, env = stub.calls[-1]
            self.assertNotIn(SECRET, " ".join(argv))
            self.assertEqual(env, {"SQLCMDPASSWORD": SECRET})
            self.assertNotIn(SECRET, stub.query_text)
            self.assertIn("BEGIN TRAN;", stub.query_text)
            self.assertIn("ROLLBACK TRAN;", stub.query_text)
            self.assertIn("SET ROWCOUNT 500;", stub.query_text)
            self.assertFalse(Path(argv[argv.index("-i") + 1]).exists())
            self.assertNotIn(SECRET, out)

        def test_csv_and_table_put_report_on_stderr(self):
            for fmt, first in (("csv", "name"), ("table", "name")):
                code, out, err = call(BASE + ["--query", "SELECT name FROM t",
                                              "--format", fmt], Stub())
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith(first))
                rep = json.loads(err)
                self.assertEqual((rep["rows"], rep["data"]), (2, None))

        def test_for_json_chunks_joined(self):
            col = "JSON_F52E2B61-18A1-11d1-B105-00805F49916B"
            stub = Stub(sql_out=fake_output([col], [['[{"a":'], ["1}]"]]))
            code, out, _ = call(BASE + ["--query",
                                        "SELECT 1 AS a FOR JSON PATH"], stub)
            self.assertEqual(json.loads(out)["data"], [['[{"a":1}]']])

        def test_key_vault_reference(self):
            stub = Stub(conn='{"uri":"https://kv.vault.azure.net/secrets/c"}',
                        kv=CONN)
            code, out, _ = call(BASE + ["--query", "SELECT 1"], stub)
            self.assertEqual(code, 0, out)
            self.assertIn("keyvault", stub.calls[1][0])

        def test_az_failure_is_exit_2(self):
            code, out, _ = call(BASE + ["--query", "SELECT 1"], Stub(az_code=1))
            self.assertEqual(code, 2)
            self.assertIn("az login", json.loads(out)["error"])

        def test_non_dev_refused_before_sqlcmd(self):
            stub = Stub(conn=CONN.replace("gorelo-dev-sql", "gorelo-prod-sql"))
            code, out, _ = call(BASE + ["--query", "SELECT 1"], stub)
            rep = json.loads(out)
            self.assertEqual(code, 1)
            self.assertIn("not a DEV target", rep["refused"])
            self.assertEqual(len(stub.calls), 1)  # az only
            self.assertNotIn(SECRET, out)

        def test_sql_error_is_exit_2(self):
            code, out, _ = call(BASE + ["--query", "SELECT 1"], Stub(sql_code=1))
            self.assertEqual(code, 2)
            self.assertIn("Msg 208", json.loads(out)["error"])

        def test_unsupported_auth_is_exit_2(self):
            stub = Stub(conn="Server=dev;Authentication=Active Directory "
                             "Default;Database=x")
            code, out, _ = call(BASE + ["--query", "SELECT 1"], stub)
            self.assertEqual(code, 2)
            self.assertIn("not supported", json.loads(out)["error"])

        def test_missing_args_is_exit_2(self):
            code, out, _ = call(["--key", "K"], Stub())
            self.assertEqual(code, 2)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(t) for t in
                               (ValidatorTests, ConnectionTests, FlowTests))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
