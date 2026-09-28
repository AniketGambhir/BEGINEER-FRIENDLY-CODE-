from flask import Flask, render_template, request, jsonify
import re
import os

app = Flask(__name__)


# ============================================================
# LANGUAGE INFORMATION
# ============================================================

LANGUAGES = {
    "java": {
        "name": "Java",
        "extension": ".java"
    },
    "python": {
        "name": "Python",
        "extension": ".py"
    },
    "c": {
        "name": "C",
        "extension": ".c"
    }
}


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(code):
    """
    Automatically detects whether the code is Java, Python or C.
    """

    if not code or not code.strip():
        return "java"

    # --------------------------------------------------------
    # Java patterns
    # --------------------------------------------------------

    java_patterns = [
        r"\bpublic\s+class\s+\w+",
        r"\bprivate\s+class\s+\w+",
        r"\bprotected\s+class\s+\w+",
        r"\bpublic\s+static\s+void\s+main",
        r"\bSystem\.out\.println",
        r"\bSystem\.out\.print",
        r"\bSystem\.out\.printf",
        r"\bimport\s+java\.",
        r"\bextends\s+\w+",
        r"\bimplements\s+\w+",
        r"\bString\[\]\s+\w+"
    ]

    # --------------------------------------------------------
    # Python patterns
    # --------------------------------------------------------

    python_patterns = [
        r"^\s*def\s+\w+\s*\(",
        r"^\s*class\s+\w+.*:",
        r"\bprint\s*\(",
        r"\bimport\s+\w+",
        r"\bfrom\s+\w+\s+import",
        r"__name__",
        r"__main__",
        r"\bself\.",
        r"\belif\b",
        r"\bNone\b",
        r"\bTrue\b",
        r"\bFalse\b"
    ]

    # --------------------------------------------------------
    # C patterns
    # --------------------------------------------------------

    c_patterns = [
        r"#include\s*<stdio\.h>",
        r"#include\s*<stdlib\.h>",
        r"\bint\s+main\s*\(",
        r"\bprintf\s*\(",
        r"\bscanf\s*\(",
        r"\bmalloc\s*\(",
        r"\bfree\s*\(",
        r"\bstruct\s+\w+",
        r"\bchar\s+\w+\s*\["
    ]

    java_score = 0
    python_score = 0
    c_score = 0

    for pattern in java_patterns:
        if re.search(pattern, code, re.MULTILINE):
            java_score += 1

    for pattern in python_patterns:
        if re.search(pattern, code, re.MULTILINE):
            python_score += 1

    for pattern in c_patterns:
        if re.search(pattern, code, re.MULTILINE):
            c_score += 1

    scores = {
        "java": java_score,
        "python": python_score,
        "c": c_score
    }

    detected = max(scores, key=scores.get)

    # If no useful pattern was found, default to Java
    if scores[detected] == 0:
        return "java"

    return detected


# ============================================================
# HELPER FUNCTION
# ============================================================

def make_diagnostic(
    error_type,
    message,
    simple,
    fix,
    line_number=None,
    line_text=None
):
    """
    Creates a standard error response.
    """

    return {
        "type": error_type,
        "message": message,
        "simple": simple,
        "fix": fix,
        "line": line_number,
        "line_text": line_text
    }


# ============================================================
# MISSING SEMICOLON CHECK
# ============================================================

def missing_semicolon(code, language):
    """
    Checks Java and C code for likely missing semicolons.
    """

    if language not in ["java", "c"]:
        return None

    lines = code.splitlines()

    # Lines that normally do not require semicolon
    ignored_starts = (
        "//",
        "/*",
        "*",
        "#",
        "import ",
        "package ",
        "public class ",
        "class ",
        "interface ",
        "enum "
    )

    for index, original_line in enumerate(lines):

        line = original_line.strip()

        if not line:
            continue

        # Ignore comments
        if line.startswith("//"):
            continue

        if line.startswith("/*"):
            continue

        # Ignore annotations
        if line.startswith("@"):
            continue

        # Ignore preprocessor statements in C
        if language == "c" and line.startswith("#"):
            continue

        # Ignore opening/closing blocks
        if line.endswith("{"):
            continue

        if line in ["}", "};", "{"]:
            continue

        # Java/C control statements that normally don't end with ;
        control_patterns = [
            r"^if\s*\(",
            r"^else\b",
            r"^else\s+if\s*\(",
            r"^for\s*\(",
            r"^while\s*\(",
            r"^switch\s*\(",
            r"^case\s+",
            r"^default\s*:",
            r"^try\b",
            r"^catch\s*\(",
            r"^finally\b",
            r"^do\b"
        ]

        is_control_statement = False

        for pattern in control_patterns:
            if re.match(pattern, line):
                is_control_statement = True
                break

        if is_control_statement:
            continue

        # Lines already ending correctly
        if line.endswith(";"):
            continue

        # Lines ending with block characters
        if line.endswith("{"):
            continue

        if line.endswith("}"):
            continue

        # Java class/method declarations
        if language == "java":

            if re.match(
                r"^(public|private|protected)?\s*"
                r"(static\s+)?"
                r"(final\s+)?"
                r"(void|int|double|float|long|short|byte|char|boolean|String)"
                r"\s+\w+\s*\([^)]*\)\s*$",
                line
            ):
                continue

        # C function declarations
        if language == "c":

            if re.match(
                r"^(int|void|char|float|double|long|short)\s+"
                r"\w+\s*\([^)]*\)\s*$",
                line
            ):
                continue

        # Statements that commonly require semicolon
        statement_patterns = [

            # Output
            r"^System\.out\.(println|print|printf)\s*\(",
            r"^printf\s*\(",
            r"^scanf\s*\(",

            # Variable declarations
            r"^(int|float|double|char|long|short|byte|boolean|String)\s+",
            r"^(unsigned|signed)\s+",

            # Assignment
            r"^\w+\s*=",
            r"^\w+\s*\+=\s*",
            r"^\w+\s*-=\s*",
            r"^\w+\s*\*=\s*",
            r"^\w+\s*/=\s*",

            # return / break / continue
            r"^return\b",
            r"^break\b",
            r"^continue\b",

            # Object creation
            r"^(new\s+)",
            r"^\w+\s+\w+\s*=\s*new\s+",

            # Method calls
            r"^\w+\.\w+\s*\(",

            # Function calls
            r"^\w+\s*\(",

            # C memory functions
            r"^malloc\s*\(",
            r"^free\s*\("
        ]

        for pattern in statement_patterns:

            if re.match(pattern, line):

                return make_diagnostic(
                    "missing_semicolon",
                    "Semicolon (;) is missing after this line.",
                    (
                        f"{LANGUAGES[language]['name']} expects a semicolon "
                        "at the end of this statement."
                    ),
                    f"Add ; after: {line}",
                    index + 1,
                    original_line
                )

    return None


# ============================================================
# PYTHON COLON CHECK
# ============================================================

def python_block_error(code):
    """
    Checks Python block statements for a missing colon.
    """

    lines = code.splitlines()

    block_patterns = [
        r"^\s*if\b.*\)\s*$",
        r"^\s*elif\b.*\)\s*$",
        r"^\s*else\s*$",
        r"^\s*for\b.*\s*$",
        r"^\s*while\b.*\s*$",
        r"^\s*def\s+\w+\s*\([^)]*\)\s*$",
        r"^\s*class\s+\w+.*$",
        r"^\s*try\s*$",
        r"^\s*except\b.*$",
        r"^\s*finally\s*$",
        r"^\s*with\b.*$"
    ]

    for index, original_line in enumerate(lines):

        line = original_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        # Correct block line
        if line.endswith(":"):
            continue

        for pattern in block_patterns:

            if re.match(pattern, line):

                return make_diagnostic(
                    "missing_colon",
                    "Colon (:) is missing after this Python statement.",
                    (
                        "Python uses a colon to start a block after "
                        "if, else, for, while, def, class, try, etc."
                    ),
                    f"Add : after: {line}",
                    index + 1,
                    original_line
                )

    return None


# ============================================================
# UNMATCHED QUOTES
# ============================================================

def check_unmatched_quotes(code):
    """
    Checks for basic unmatched quotation marks.
    """

    lines = code.splitlines()

    for index, original_line in enumerate(lines):

        line = original_line.strip()

        if not line:
            continue

        # Remove comments approximately
        code_part = line.split("//")[0]
        code_part = code_part.split("#")[0]

        double_quotes = code_part.count('"')
        single_quotes = code_part.count("'")

        if double_quotes % 2 != 0:

            return make_diagnostic(
                "unmatched_quote",
                "A double quote (\") is not closed.",
                (
                    "You opened a string with a double quote, "
                    "but another double quote is missing."
                ),
                f"Close the string with another \": {line}",
                index + 1,
                original_line
            )

        if single_quotes % 2 != 0:

            return make_diagnostic(
                "unmatched_quote",
                "A single quote (') is not closed.",
                (
                    "You opened a string with a single quote, "
                    "but another single quote is missing."
                ),
                f"Close the string with another ': {line}",
                index + 1,
                original_line
            )

    return None


# ============================================================
# JAVA CASE-SENSITIVITY CHECK
# ============================================================

def check_java_case_errors(code, language):

    if language != "java":
        return None

    lines = code.splitlines()

    for index, original_line in enumerate(lines):

        line = original_line.strip()

        # system.out instead of System.out
        if "system.out" in line:

            fixed = line.replace("system.out", "System.out")

            return make_diagnostic(
                "java_case_error",
                "Java is case-sensitive: use System.out.",
                (
                    "Java treats uppercase and lowercase letters "
                    "as different characters."
                ),
                f"Use: {fixed}",
                index + 1,
                original_line
            )

        # println spelling
        if "Println" in line:

            fixed = line.replace("Println", "println")

            return make_diagnostic(
                "java_case_error",
                "Java is case-sensitive: use println.",
                (
                    "The correct Java method name is println with "
                    "a lowercase p."
                ),
                f"Use: {fixed}",
                index + 1,
                original_line
            )

        # Java String typo
        if re.search(r"\bstring\b", line):

            fixed = re.sub(r"\bstring\b", "String", line)

            return make_diagnostic(
                "java_case_error",
                "Java uses String with a capital S.",
                (
                    "Java class names are case-sensitive. "
                    "The correct type is String."
                ),
                f"Use: {fixed}",
                index + 1,
                original_line
            )

    return None


# ============================================================
# BRACKET CHECK
# ============================================================

def check_brackets(code):
    """
    Performs a basic bracket balance check.
    """

    pairs = {
        ")": "(",
        "]": "[",
        "}": "{"
    }

    opening = set(pairs.values())

    stack = []

    lines = code.splitlines()

    for index, line in enumerate(lines):

        # Remove simple string contents to reduce false positives
        cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        cleaned = re.sub(r"'(?:\\.|[^'\\])*'", "''", cleaned)

        for char in cleaned:

            if char in opening:
                stack.append(char)

            elif char in pairs:

                if not stack or stack[-1] != pairs[char]:

                    return make_diagnostic(
                        "bracket_error",
                        f"Unexpected closing bracket: {char}",
                        (
                            "A closing bracket does not have a matching "
                            "opening bracket."
                        ),
                        "Check the brackets near this line.",
                        index + 1,
                        line
                    )

                stack.pop()

    if stack:

        expected = {
            "(": ")",
            "[": "]",
            "{": "}"
        }

        missing = expected.get(stack[-1], "")

        return make_diagnostic(
            "bracket_error",
            f"A closing bracket {missing} may be missing.",
            (
                "You opened a bracket but the matching closing "
                "bracket was not found."
            ),
            f"Add the matching closing bracket: {missing}",
            None,
            None
        )

    return None


# ============================================================
# PYTHON INDENTATION CHECK
# ============================================================

def check_python_indentation(code):

    if not code.strip():
        return None

    lines = code.splitlines()

    previous_requires_indent = False
    previous_indent = 0

    for index, original_line in enumerate(lines):

        if not original_line.strip():
            continue

        stripped = original_line.lstrip()

        if stripped.startswith("#"):
            continue

        current_indent = len(original_line) - len(stripped)

        if previous_requires_indent:

            if current_indent <= previous_indent:

                return make_diagnostic(
                    "indentation_error",
                    "Python indentation may be incorrect.",
                    (
                        "Python uses indentation to show which statements "
                        "belong inside a block."
                    ),
                    "Indent this line by 4 spaces.",
                    index + 1,
                    original_line
                )

        if stripped.endswith(":"):

            previous_requires_indent = True
            previous_indent = current_indent

        else:

            previous_requires_indent = False

    return None


# ============================================================
# GENERAL ERROR CHECK
# ============================================================

def common_error(code, language):

    # Check unmatched quotes
    quote_error = check_unmatched_quotes(code)

    if quote_error:
        return quote_error

    # Java case errors
    java_error = check_java_case_errors(code, language)

    if java_error:
        return java_error

    # Bracket check
    bracket_error = check_brackets(code)

    if bracket_error:
        return bracket_error

    # Python indentation
    if language == "python":

        indentation_error = check_python_indentation(code)

        if indentation_error:
            return indentation_error

    return None


# ============================================================
# ANALYZE CODE
# ============================================================

def analyze_code(code, language):

    diagnostics = []

    # --------------------------------------------------------
    # Missing semicolon
    # --------------------------------------------------------

    if language in ["java", "c"]:

        semicolon_error = missing_semicolon(
            code,
            language
        )

        if semicolon_error:
            diagnostics.append(semicolon_error)

    # --------------------------------------------------------
    # Python colon
    # --------------------------------------------------------

    if language == "python":

        colon_error = python_block_error(code)

        if colon_error:
            diagnostics.append(colon_error)

    # --------------------------------------------------------
    # Common errors
    # --------------------------------------------------------

    common = common_error(code, language)

    if common:

        # Avoid adding the same error twice
        duplicate = False

        for diagnostic in diagnostics:

            if diagnostic["type"] == common["type"]:

                duplicate = True
                break

        if not duplicate:
            diagnostics.append(common)

    return diagnostics


# ============================================================
# API: ANALYZE
# ============================================================

@app.route("/api/analyze", methods=["POST"])
def analyze():

    try:

        data = request.get_json(silent=True)

        if not data:

            return jsonify({
                "success": False,
                "message": "No code data was received."
            }), 400

        code = data.get("code", "")
        requested_language = data.get("language", "auto")

        if not isinstance(code, str):

            return jsonify({
                "success": False,
                "message": "Code must be text."
            }), 400

        if not code.strip():

            return jsonify({
                "success": False,
                "message": "Please enter some code first."
            }), 400

        # ----------------------------------------------------
        # Validate requested language
        # ----------------------------------------------------

        if requested_language not in [
            "java",
            "python",
            "c",
            "auto"
        ]:

            requested_language = "auto"

        # ----------------------------------------------------
        # Detect language
        # ----------------------------------------------------

        if requested_language == "auto":

            detected_language = detect_language(code)

        else:

            detected_language = requested_language

        # ----------------------------------------------------
        # Analyze
        # ----------------------------------------------------

        diagnostics = analyze_code(
            code,
            detected_language
        )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        if diagnostics:

            first_error = diagnostics[0]

            return jsonify({
                "success": True,
                "language": detected_language,
                "language_name": LANGUAGES[detected_language]["name"],
                "has_error": True,
                "diagnostics": diagnostics,
                "message": first_error["message"],
                "simple": first_error["simple"],
                "fix": first_error["fix"],
                "line": first_error["line"],
                "line_text": first_error["line_text"],
                "ran": False,
                "compiler_output": "",
                "execution_disabled": True
            })

        # ----------------------------------------------------
        # No detected error
        # ----------------------------------------------------

        return jsonify({
            "success": True,
            "language": detected_language,
            "language_name": LANGUAGES[detected_language]["name"],
            "has_error": False,
            "diagnostics": [],
            "message": "No common error was detected.",
            "simple": (
                "The basic checks passed. "
                "This does not guarantee that the program is completely correct."
            ),
            "fix": "No automatic fix is needed.",
            "line": None,
            "line_text": None,
            "ran": False,
            "compiler_output": "",
            "execution_disabled": True
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "message": "Something went wrong while analyzing the code.",
            "details": str(error)
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "online",
        "application": "CodeSense AI Error Tutor",
        "languages": [
            "Java",
            "Python",
            "C"
        ],
        "mode": "Static error analysis"
    })


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
