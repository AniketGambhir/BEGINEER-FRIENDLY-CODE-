"""
CodeSense AI Error Tutor - Flask backend
Finds mistakes in Java, Python and C code and explains them in simple English.

PUBLIC-SAFE BY DEFAULT
  * By default the server only ANALYSES code (it never runs it), so it works on
    Render's normal Python environment and is safe to put on the internet.
  * To also run programs, set the environment variable ENABLE_EXECUTION=1
    (needs javac / gcc installed; only do this on a local machine or a sandbox).
"""

import io
import keyword  # noqa: F401  (kept for future rules)
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
from collections import defaultdict, deque

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # 64 KB request limit

ENABLE_EXECUTION = os.environ.get("ENABLE_EXECUTION", "0") == "1"
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "5"))
MAX_CODE_CHARS = 20000
MAX_OUTPUT_CHARS = 4000
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

LABELS = {"java": "Java", "python": "Python", "c": "C"}
API_PATHS = ("/run", "/analyze", "/api/")


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def make_error(line, title, explanation, fix="", code="", kind="syntax"):
    return {
        "line": line,
        "title": title,
        "explanation": explanation,
        "message": explanation,
        "fix": fix,
        "suggestion": fix,
        "code": code,
        "type": kind,
    }


def format_error(e):
    text = "\u26a0 " + e["title"].upper()
    if e.get("line"):
        text += " \u2014 LINE %s" % e["line"]
    text += "\n\n" + e["explanation"]
    if e.get("fix"):
        text += "\n\nSuggested fix:\n" + e["fix"]
    return text


def clip(text):
    text = text or ""
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n... (output cut)"
    return text


# ----------------------------------------------------------------------------
# Simple in-memory rate limiter (per worker)
# ----------------------------------------------------------------------------
_hits = defaultdict(deque)
_lock = threading.Lock()


def rate_limited(ip):
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
        if len(_hits) > 5000:  # keep memory small
            for k in [k for k, v in _hits.items() if not v]:
                _hits.pop(k, None)
        return False


# ----------------------------------------------------------------------------
# Language detection
# ----------------------------------------------------------------------------
def detect_language(code):
    score = {"java": 0, "python": 0, "c": 0}
    rules = [
        ("java", r"\bpublic\s+class\b", 4),
        ("java", r"System\.out\.print", 4),
        ("java", r"\bpublic\s+static\s+void\s+main\b", 4),
        ("java", r"String\s*\[\s*\]\s*args", 3),
        ("java", r"^\s*import\s+java\.", 4),
        ("java", r"\bnew\s+\w+\s*\(", 1),
        ("python", r"^\s*def\s+\w+\s*\(.*\)\s*:?\s*$", 4),
        ("python", r"^\s*(elif|except|finally)\b", 3),
        ("python", r"^\s*print\s*\(", 2),
        ("python", r"^\s*from\s+\w+\s+import\b", 3),
        ("python", r"^\s*import\s+\w+\s*$", 2),
        ("python", r"\b(True|False|None)\b", 1),
        ("python", r"if\s+__name__\s*==", 4),
        ("python", r"^\s*(if|for|while)\b[^{;]*:\s*$", 2),
        ("c", r"#\s*include\s*[<\"]", 5),
        ("c", r"\bprintf\s*\(", 3),
        ("c", r"\bscanf\s*\(", 3),
        ("c", r"\bint\s+main\s*\(", 3),
        ("c", r"\b(malloc|free|sizeof)\b", 2),
        ("c", r"->", 1),
    ]
    for lang, pattern, weight in rules:
        if re.search(pattern, code, re.M):
            score[lang] += weight
    best = max(score, key=score.get)
    if score[best] == 0:
        return "python" if (";" not in code and "{" not in code) else "c"
    return best


# ----------------------------------------------------------------------------
# Java / C analysis (comments and string contents are removed first)
# ----------------------------------------------------------------------------
def mask_c_like(code):
    """Return (lines_without_comments_and_string_text, unclosed_quotes)."""
    out, cur, unclosed = [], [], []
    i, n, state, line = 0, len(code), None, 1
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if ch == '"':
                state = "str"
                cur.append('"')
                i += 1
                continue
            if ch == "'":
                state = "chr"
                cur.append("'")
                i += 1
                continue
            if ch == "\n":
                out.append("".join(cur))
                cur = []
                line += 1
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = None
                out.append("".join(cur))
                cur = []
                line += 1
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state = None
                i += 2
                continue
            if ch == "\n":
                out.append("".join(cur))
                cur = []
                line += 1
            i += 1
            continue
        quote = '"' if state == "str" else "'"
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            cur.append(quote)
            state = None
            i += 1
            continue
        if ch == "\n":
            unclosed.append((line, quote))
            state = None
            out.append("".join(cur))
            cur = []
            line += 1
            i += 1
            continue
        i += 1
    out.append("".join(cur))
    return out, unclosed


CONTROL_RE = re.compile(r"^(if|else|for|while|switch|do|try|catch|finally|synchronized)\b")
NEXT_CONTINUES = ("{", ".", "?", ":", "&&", "||", ")", "=", "+ ", "- ", "* ", "/ ")


def check_semicolons(masked, raw, lang):
    errors = []
    nonblank = [i for i, l in enumerate(masked) if l.strip()]
    next_of = dict(zip(nonblank, nonblank[1:]))
    stack = []  # True when the open brace is an initializer / enum body
    for idx, line in enumerate(masked):
        s = line.strip()
        in_init = bool(stack and stack[-1])
        for pos, ch in enumerate(line):
            if ch == "{":
                before = line[:pos].rstrip()
                stack.append(
                    before.endswith("=") or before.endswith("]") or bool(re.search(r"\benum\s+\w*$", before))
                )
            elif ch == "}" and stack:
                stack.pop()
        if not s or in_init:
            continue
        if lang == "c" and s.startswith("#"):
            continue
        if s.startswith("@"):
            continue
        last = s[-1]
        if last in ";{}":
            continue
        is_decl_kw = bool(re.match(r"^(import|package)\b", s))
        if not is_decl_kw:
            if not (s.endswith("++") or s.endswith("--")):
                if last in ":,([+-*/%&|=<>?.\\^~!":
                    continue
            core = s.lstrip("}").strip()
            if CONTROL_RE.match(core):
                continue
        nxt = masked[next_of[idx]].strip() if idx in next_of else ""
        if nxt.startswith(NEXT_CONTINUES):
            continue
        original = raw[idx].strip() if idx < len(raw) else s
        errors.append(
            make_error(
                idx + 1,
                "Missing semicolon",
                "A semicolon (;) is missing after this text:\n%s\n\nIn %s, every statement must end with a semicolon."
                % (original, LABELS[lang]),
                original + ";",
                original,
            )
        )
    return errors


CLOSERS = {")": "(", "]": "[", "}": "{"}
BRACKET_NAMES = {"(": "parenthesis ( )", "[": "square bracket [ ]", "{": "curly brace { }"}
MATCHING_CLOSE = {"(": ")", "[": "]", "{": "}"}


def check_brackets(masked, lang):
    stack = []
    for ln, line in enumerate(masked, 1):
        if lang == "c" and line.strip().startswith("#"):
            continue
        for ch in line:
            if ch in "([{":
                stack.append((ch, ln))
            elif ch in ")]}":
                if not stack:
                    return [make_error(
                        ln, "Extra closing bracket",
                        "There is an extra '%s' on line %d that has no matching opening bracket." % (ch, ln),
                        "Delete the extra '%s' or add the missing '%s' before it." % (ch, CLOSERS[ch]),
                        masked[ln - 1].strip())]
                top, top_line = stack[-1]
                if top != CLOSERS[ch]:
                    return [make_error(
                        ln, "Brackets do not match",
                        "On line %d there is a '%s', but the bracket opened on line %d was '%s', which needs '%s'."
                        % (ln, ch, top_line, top, MATCHING_CLOSE[top]),
                        "Use '%s' here instead." % MATCHING_CLOSE[top],
                        masked[ln - 1].strip())]
                stack.pop()
    if stack:
        top, top_line = stack[-1]
        return [make_error(
            top_line, "Missing closing bracket",
            "The %s opened on line %d is never closed." % (BRACKET_NAMES[top], top_line),
            "Add '%s' where that block or expression should end." % MATCHING_CLOSE[top],
            masked[top_line - 1].strip())]
    return []


JAVA_CASE_FIXES = [
    (re.compile(r"\bsystem\.out\b"), "System.out", "In Java, 'System' must start with a capital S."),
    (re.compile(r"\bSystem\.Out\b"), "System.out", "In Java, 'out' must be written in small letters."),
    (re.compile(r"\.(Println|PrintLn|Print)\b"), None, "Java method names such as println are written in small letters."),
    (re.compile(r"\bstring\b(?=\s*(\[\s*\])?\s+\w)"), "String", "In Java, the text type is 'String' with a capital S."),
    (re.compile(r"\bPublic\b"), "public", "'public' must be written in small letters in Java."),
    (re.compile(r"\bStatic\b"), "static", "'static' must be written in small letters in Java."),
]
C_CASE_FIXES = [
    (re.compile(r"\bPrintf\b"), "printf", "In C, 'printf' must be written in small letters."),
    (re.compile(r"\bScanf\b"), "scanf", "In C, 'scanf' must be written in small letters."),
    (re.compile(r"\bMain\s*\("), "main(", "In C, the starting function is 'main' in small letters."),
]


def check_case_and_includes(masked, raw, lang):
    errors = []
    fixes = JAVA_CASE_FIXES if lang == "java" else C_CASE_FIXES
    for idx, line in enumerate(masked):
        for pattern, correct, why in fixes:
            if pattern.search(line):
                original = raw[idx].strip() if idx < len(raw) else line.strip()
                if correct is None:
                    fixed = pattern.sub(lambda m: "." + m.group(1).lower(), original)
                else:
                    fixed = pattern.sub(correct, original)
                errors.append(make_error(
                    idx + 1, "Wrong capital / small letters",
                    "%s\n\nThis line uses the wrong letter case:\n%s" % (why, original), fixed, original))
                break
    if lang == "c":
        joined = "\n".join(masked)
        if re.search(r"\b(printf|scanf|puts|getchar)\s*\(", joined) and not re.search(r"#\s*include\s*<stdio\.h>", joined):
            for idx, line in enumerate(masked):
                if re.search(r"\b(printf|scanf|puts|getchar)\s*\(", line):
                    errors.append(make_error(
                        idx + 1, "Missing #include <stdio.h>",
                        "You use printf/scanf, but the file never includes the input/output library.",
                        "Add this as the very first line:\n#include <stdio.h>",
                        raw[idx].strip() if idx < len(raw) else ""))
                    break
    return errors


def check_c_like(code, lang):
    raw = code.split("\n")
    masked, unclosed = mask_c_like(code)
    errors = []
    for ln, quote in unclosed:
        original = raw[ln - 1].strip() if ln - 1 < len(raw) else ""
        if quote == '"':
            errors.append(make_error(
                ln, "Missing closing quote",
                "A text started with a double quote (\") but never ended on this line.",
                "Add a closing \" at the end of the text.", original))
        else:
            errors.append(make_error(
                ln, "Missing closing single quote",
                "A character started with a single quote (') but never ended.",
                "Add a closing ' after the character.", original))
    if errors:
        return errors
    errors = check_brackets(masked, lang)
    if errors:
        return errors
    errors = check_case_and_includes(masked, raw, lang)
    errors += check_semicolons(masked, raw, lang)
    errors.sort(key=lambda e: e["line"])
    return errors


# ----------------------------------------------------------------------------
# Python analysis
# ----------------------------------------------------------------------------
PY_BLOCK_WORDS = {"def", "class", "if", "elif", "else", "for", "while", "try", "except", "finally", "with"}


def check_python_colons(code):
    errors = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return errors
    lines = code.split("\n")
    logical = []
    skip = (tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
    for t in tokens:
        if t.type in skip:
            continue
        if t.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            if logical:
                first = logical[0]
                if first.type == tokenize.NAME and first.string in PY_BLOCK_WORDS:
                    depth, has_colon = 0, False
                    for tok in logical:
                        if tok.type == tokenize.OP:
                            if tok.string in "([{":
                                depth += 1
                            elif tok.string in ")]}":
                                depth -= 1
                            elif tok.string == ":" and depth == 0:
                                has_colon = True
                                break
                    if not has_colon:
                        ln = first.start[0]
                        text = lines[ln - 1].strip() if ln - 1 < len(lines) else ""
                        errors.append(make_error(
                            ln, "Missing colon",
                            "A colon (:) is missing at the end of this line:\n%s\n\n"
                            "In Python, a line that starts a block (like '%s') must end with a colon." % (text, first.string),
                            text + ":", text))
                logical = []
            continue
        logical.append(t)
    return errors


def translate_python_error(e, lines):
    msg = e.msg or ""
    low = msg.lower()
    ln = e.lineno or 1
    text = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
    if isinstance(e, IndentationError):
        if "expected an indented block" in low:
            return make_error(ln, "Missing indentation",
                              "Python expects the line after a ':' to be pushed to the right (indented).",
                              "Add 4 spaces at the start of the line that belongs inside the block.", text)
        if "unindent" in low:
            return make_error(ln, "Indentation does not match",
                              "This line is indented differently from the lines around it.",
                              "Use the same number of spaces as the other lines in this block.", text)
        return make_error(ln, "Unexpected indentation",
                          "This line has extra spaces at the start that Python did not expect.",
                          "Remove the extra spaces so it lines up with the code above.", text)
    if "unterminated string" in low or "eol while scanning" in low:
        return make_error(ln, "Missing closing quote",
                          "A text started with a quote but the closing quote is missing.",
                          "Add the same quote mark at the end of the text.", text)
    if "was never closed" in low:
        return make_error(ln, "Bracket is never closed",
                          "You opened a bracket ( [ { on this line but never closed it.",
                          "Add the matching closing bracket ) ] }.", text)
    if "unmatched" in low or "closing parenthesis" in low:
        return make_error(ln, "Extra closing bracket",
                          "There is a closing bracket that has no opening bracket.",
                          "Remove it or add the missing opening bracket.", text)
    if "missing parentheses in call to 'print'" in low:
        return make_error(ln, "print needs brackets",
                          "In Python 3, print must be written with brackets.",
                          re.sub(r"^print\s+(.*)$", r"print(\1)", text), text)
    if "expected ':'" in low:
        return make_error(ln, "Missing colon",
                          "A colon (:) is missing at the end of this line.", text + ":", text)
    if "forgot a comma" in low:
        return make_error(ln, "Missing comma",
                          "Two items are written next to each other without a comma between them.",
                          "Put a comma (,) between the items.", text)
    if "maybe you meant '=='" in low or "cannot assign" in low:
        return make_error(ln, "'=' used where '==' is needed",
                          "A single = stores a value. To compare two values use ==.",
                          "Use == when you compare.", text)
    if "invalid syntax" in low:
        return make_error(ln, "Something is wrong on this line",
                          "Python cannot understand this line. Check for a missing bracket, quote, colon or a misspelled word.",
                          "", text)
    return make_error(ln, "Syntax error",
                      "Python found a problem on this line: %s" % msg, "", text)


def check_python(code):
    errors = check_python_colons(code)
    if errors:
        return errors
    try:
        compile(code, "<student-code>", "exec")
    except SyntaxError as e:
        return [translate_python_error(e, code.split("\n"))]
    except (ValueError, RecursionError, MemoryError):
        return [make_error(1, "Code cannot be read",
                           "The code is too complicated or contains strange characters.", "", "")]
    return []


def analyze(code, lang):
    if lang == "python":
        return check_python(code)
    return check_c_like(code, lang)


# ----------------------------------------------------------------------------
# Optional: compile / run (only when ENABLE_EXECUTION=1)
# ----------------------------------------------------------------------------
COMPILER_RULES = [
    (r"';' expected|expected ';'", "Missing semicolon",
     "A semicolon (;) is missing at the end of a statement.", "Add ; at the end of the line."),
    (r"expected '\)'|'\)' expected", "Missing closing bracket",
     "A closing bracket ) is missing.", "Add ) where the expression ends."),
    (r"reached end of file while parsing|at end of input|expected '\}'|'\}' expected", "Missing closing brace",
     "The file ended before a block was closed.", "Add a } to close the open block."),
    (r"unclosed string literal|missing terminating", "Missing closing quote",
     "A text started with a quote but never ended.", "Add the closing quote."),
    (r"cannot find symbol|undeclared|not declared", "Unknown name",
     "You used a name that was never created, or it is spelled differently.",
     "Check the spelling, and create the variable before using it."),
    (r"incompatible types|incompatible pointer|makes integer from pointer|makes pointer from integer",
     "Wrong type of value", "You put one kind of value where another kind is needed.",
     "Use the correct type or convert the value."),
    (r"missing return statement", "Missing return",
     "The method should give back a value, but some paths do not.", "Add a return statement."),
    (r"class, interface, enum, or record expected|expected declaration specifiers", "Code in the wrong place",
     "Some code is outside a class or function, or a brace is extra.", "Check the { } around this line."),
    (r"implicit declaration of function", "Function not known",
     "You called a function the compiler has not seen yet.", "Check the spelling or add the right #include."),
    (r"not a statement", "Not a valid statement",
     "This line does not do anything valid on its own.", "Check for a missing operator or method call."),
    (r"might not have been initialized|uninitialized", "Variable has no value",
     "You use a variable before giving it a value.", "Give the variable a value first."),
    (r"already defined|redeclaration|redefinition", "Name used twice",
     "Two things have the same name.", "Rename one of them."),
    (r"should be declared in a file", "Class name and file name differ",
     "A public class must have the same name as its file.", "Rename the class to match the file."),
]
COMPILER_LINE = re.compile(r"([\w.\-]+\.(?:java|c)):(\d+)(?::\d+)?:\s*(?:fatal\s+)?error:\s*(.+)")


def explain_compiler_output(text, lang, src_lines):
    errors = []
    for m in COMPILER_LINE.finditer(text):
        ln, msg = int(m.group(2)), m.group(3).strip()
        source = src_lines[ln - 1].strip() if 0 < ln <= len(src_lines) else ""
        for pattern, title, why, fix in COMPILER_RULES:
            if re.search(pattern, msg, re.I):
                if title == "Missing semicolon" and source:
                    fix = source + ";"
                errors.append(make_error(ln, title, why, fix, source, "compiler"))
                break
        else:
            errors.append(make_error(ln, "Compiler error",
                                     "The compiler reported: %s" % msg, "", source, "compiler"))
    return errors[:5]


PY_RUNTIME = {
    "NameError": "You used a name that Python does not know. It may be misspelled or created too late.",
    "ZeroDivisionError": "You divided a number by zero, which is not allowed.",
    "IndexError": "You asked for a list position that does not exist.",
    "KeyError": "You asked for a dictionary key that does not exist.",
    "TypeError": "You mixed values that do not work together (for example text + number).",
    "ValueError": "The value has the right type but a wrong content (for example int('abc')).",
    "AttributeError": "You used a method or property that this object does not have.",
    "ModuleNotFoundError": "Python cannot find the module you tried to import.",
    "RecursionError": "A function keeps calling itself and never stops.",
}
JAVA_RUNTIME = {
    "ArithmeticException": "You divided by zero.",
    "ArrayIndexOutOfBoundsException": "You used an array position that does not exist.",
    "StringIndexOutOfBoundsException": "You asked for a character position that is not in the text.",
    "NullPointerException": "You used a variable that has no object in it (null).",
    "NumberFormatException": "You tried to turn text into a number, but the text is not a number.",
    "ClassCastException": "You treated an object as the wrong type.",
    "StackOverflowError": "A method keeps calling itself and never stops.",
    "InputMismatchException": "The input was not the kind of value the program expected.",
}
SIGNALS = {
    -11: ("Crash: invalid memory access",
          "The program touched memory it does not own (often a bad pointer or array index)."),
    -8: ("Crash: math error", "The program divided by zero."),
    -6: ("Program stopped itself", "The program aborted, often after a memory problem."),
}


def explain_runtime(lang, rc, stderr):
    if lang == "python":
        last = [l for l in stderr.strip().split("\n") if l.strip()]
        if last:
            m = re.match(r"^([\w.]+):\s*(.*)$", last[-1])
            lines = re.findall(r'File "[^"]*main\.py", line (\d+)', stderr)
            if m:
                name = m.group(1).split(".")[-1]
                why = PY_RUNTIME.get(name, "The program stopped with an error.")
                return make_error(int(lines[-1]) if lines else None, name,
                                  "%s\n\nPython says: %s" % (why, last[-1]), "", "", "runtime")
    if lang == "java":
        m = re.search(r'Exception in thread "main" ([\w.$]+)(?::\s*(.*))?', stderr)
        if m:
            name = m.group(1).split(".")[-1]
            where = re.search(r"\((\w+)\.java:(\d+)\)", stderr)
            why = JAVA_RUNTIME.get(name, "The program stopped with an error.")
            return make_error(int(where.group(2)) if where else None, name,
                              "%s\n\nJava says: %s" % (why, m.group(0).split('"main" ')[-1]), "", "", "runtime")
    if lang == "c" and rc in SIGNALS:
        title, why = SIGNALS[rc]
        return make_error(None, title, why, "", "", "runtime")
    return None


def _limiter(mem_mb):
    def apply():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (RUN_TIMEOUT + 1, RUN_TIMEOUT + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1000000, 1000000))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if mem_mb:
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    return apply


def _to_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _run(cmd, cwd, timeout, mem_mb=512):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": cwd, "LANG": "C.UTF-8"}
    try:
        p = subprocess.run(
            cmd, cwd=cwd, input="", capture_output=True, text=True, errors="replace",
            timeout=timeout, env=env,
            preexec_fn=_limiter(mem_mb) if os.name == "posix" else None)
        return p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired as e:
        return None, _to_text(e.stdout), _to_text(e.stderr), True


def execute(code, lang):
    """Return dict(errors, output, note)."""
    result = {"errors": [], "output": "", "note": ""}
    work = tempfile.mkdtemp(prefix="codesense_")
    src_lines = code.split("\n")
    try:
        if lang == "python":
            path = os.path.join(work, "main.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            rc, out, err, timed_out = _run([sys.executable, "-I", "main.py"], work, RUN_TIMEOUT)
            run_lang = "python"
        elif lang == "c":
            if not shutil.which("gcc"):
                result["note"] = "GCC is not installed on this server, so C programs cannot be run here."
                return result
            with open(os.path.join(work, "main.c"), "w", encoding="utf-8") as f:
                f.write(code)
            crc, cout, cerr, cto = _run(["gcc", "main.c", "-o", "main.out", "-lm"], work, 15)
            if crc != 0:
                result["errors"] = explain_compiler_output(cerr, "c", src_lines)
                result["output"] = clip(cerr)
                return result
            rc, out, err, timed_out = _run(["./main.out"], work, RUN_TIMEOUT)
            run_lang = "c"
        else:
            if not (shutil.which("javac") and shutil.which("java")):
                result["note"] = "Java is not installed on this server, so Java programs cannot be run here."
                return result
            m = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", code) or re.search(r"\bclass\s+(\w+)", code)
            name = m.group(1) if m else "Main"
            with open(os.path.join(work, name + ".java"), "w", encoding="utf-8") as f:
                f.write(code)
            crc, cout, cerr, cto = _run(["javac", "-encoding", "UTF-8", name + ".java"], work, 20, mem_mb=0)
            if crc != 0:
                result["errors"] = explain_compiler_output(cerr, "java", src_lines)
                result["output"] = clip(cerr)
                return result
            rc, out, err, timed_out = _run(["java", "-Xmx128m", "-cp", ".", name], work, RUN_TIMEOUT + 3, mem_mb=0)
            run_lang = "java"

        if timed_out:
            result["errors"] = [make_error(None, "Program took too long",
                                           "The program ran for more than %d seconds and was stopped. "
                                           "It may have an endless loop." % RUN_TIMEOUT,
                                           "Check that every loop has a way to finish.", "", "runtime")]
        elif rc != 0:
            e = explain_runtime(run_lang, rc, err)
            if e:
                result["errors"] = [e]
        result["output"] = clip(out + (("\n" + err) if err else ""))
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify(status="ok", execution_enabled=ENABLE_EXECUTION)


@app.route("/run", methods=["POST"])
@app.route("/analyze", methods=["POST"])
@app.route("/api/run", methods=["POST"])
@app.route("/api/analyze", methods=["POST"])
def run_endpoint():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
    if rate_limited(ip):
        return jsonify(status="error", has_error=True,
                       message="Too many requests. Please wait a minute and try again."), 429

    data = request.get_json(silent=True) or request.form or {}
    code = (data.get("code") or "").replace("\r\n", "\n")
    requested = str(data.get("language") or data.get("lang") or "auto").strip().lower()
    aliases = {"py": "python", "python3": "python", "javac": "java", "gcc": "c"}
    requested = aliases.get(requested, requested)

    if not code.strip():
        return jsonify(status="error", has_error=True, message="Please type some code first.",
                       errors=[], output=""), 400
    if len(code) > MAX_CODE_CHARS:
        return jsonify(status="error", has_error=True,
                       message="Your code is too long (limit %d characters)." % MAX_CODE_CHARS,
                       errors=[], output=""), 413

    auto = requested not in LABELS
    lang = detect_language(code) if auto else requested

    errors = analyze(code, lang)[:5]
    output, executed, note = "", False, ""

    if not errors:
        if ENABLE_EXECUTION:
            ran = execute(code, lang)
            errors, output, note = ran["errors"], ran["output"], ran["note"]
            executed = not note
        else:
            note = "No mistakes found. (This public server checks your code but does not run it.)"

    if errors:
        headline = format_error(errors[0])
    elif executed:
        headline = "\u2714 No errors found. Program finished."
    else:
        headline = "\u2714 " + (note or "No errors found.")

    first = errors[0] if errors else {}
    return jsonify(
        status="error" if errors else "ok",
        has_error=bool(errors),
        language=lang,
        language_label=LABELS[lang],
        detected=auto,
        detected_language=LABELS[lang] if auto else None,
        errors=errors,
        error=first or None,
        title=first.get("title"),
        line=first.get("line"),
        explanation=first.get("explanation"),
        fix=first.get("fix"),
        suggestion=first.get("fix"),
        output=output,
        executed=executed,
        note=note,
        message=headline,
        formatted=headline,
    )


@app.errorhandler(Exception)
def handle_exception(e):
    is_api = request.path.startswith(API_PATHS)
    if isinstance(e, HTTPException):
        if is_api:
            return jsonify(status="error", has_error=True, message=e.description, errors=[], output=""), e.code
        return e
    app.logger.exception("Unhandled error")
    if is_api:
        return jsonify(status="error", has_error=True,
                       message="Something went wrong on the server. Please try again.",
                       errors=[], output=""), 500
    return "Internal Server Error", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
