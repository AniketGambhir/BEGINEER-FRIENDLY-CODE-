from flask import Flask, render_template, request, jsonify
import re
import subprocess
import tempfile
import os
import shutil

app = Flask(__name__)

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


# ---------------------------------------------------------
# LANGUAGE DETECTION
# ---------------------------------------------------------

def detect_language(code):
    """
    Automatically detect whether the code is Java, Python or C.
    """

    java_patterns = [
        r"\bpublic\s+class\b",
        r"\bprivate\s+class\b",
        r"\bSystem\.out\.",
        r"\bpublic\s+static\s+void\s+main\b",
        r"\bimport\s+java\.",
        r"\bString\s*\[\]"
    ]

    python_patterns = [
        r"\bdef\s+\w+\s*\(",
        r"\bimport\s+\w+",
        r"\bfrom\s+\w+\s+import\b",
        r"\bprint\s*\(",
        r"\bif\s+.*:",
        r"\b__name__\b",
        r"\bfor\s+\w+\s+in\s+"
    ]

    c_patterns = [
        r"#include\s*<stdio\.h>",
        r"#include\s*<stdlib\.h>",
        r"\bint\s+main\s*\(",
        r"\bprintf\s*\(",
        r"\bscanf\s*\(",
        r"\bmalloc\s*\(",
        r"\bchar\s+\w+\s*\["
    ]

    java_score = sum(
        bool(re.search(pattern, code))
        for pattern in java_patterns
    )

    python_score = sum(
        bool(re.search(pattern, code))
        for pattern in python_patterns
    )

    c_score = sum(
        bool(re.search(pattern, code))
        for pattern in c_patterns
    )

    scores = {
        "java": java_score,
        "python": python_score,
        "c": c_score
    }

    detected = max(scores, key=scores.get)

    if scores[detected] == 0:
        return "unknown"

    return detected


# ---------------------------------------------------------
# MISSING SEMICOLON CHECK
# ---------------------------------------------------------

def check_missing_semicolon(code, language):
    """
    Detect common missing semicolon errors in Java and C.
    """

    if language not in ["java", "c"]:
        return None

    lines = code.splitlines()

    ignored_starts = (
        "if ",
        "if(",
        "for ",
        "for(",
        "while ",
        "while(",
        "switch ",
        "switch(",
        "else",
        "try",
        "catch",
        "finally",
        "class ",
        "public class",
        "private class",
        "protected class",
        "static class",
        "{",
        "}",
        "//",
        "/*",
        "*"
    )

    for index, original_line in enumerate(lines):

        line = original_line.strip()

        if not line:
            continue

        if line.startswith(ignored_starts):
            continue

        if line.endswith(("{", "}", ";", ":")):
            continue

        # Java / C common statements
        patterns = [
            r"System\.out\.print",
            r"System\.out\.println",
            r"printf\s*\(",
            r"scanf\s*\(",
            r"\breturn\b",
            r"\bint\s+\w+\s*=",
            r"\bfloat\s+\w+\s*=",
            r"\bdouble\s+\w+\s*=",
            r"\bchar\s+\w+\s*=",
            r"\bString\s+\w+\s*=",
            r"\w+\s*=\s*.+",
        ]

        for pattern in patterns:
            if re.search(pattern, line):

                return {
                    "type": "missing_semicolon",
                    "line": index + 1,
                    "message": "Semicolon (;) is missing after this line.",
                    "simple": (
                        f"{LANGUAGES[language]['name']} expects a semicolon "
                        "at the end of this statement."
                    ),
                    "fix": line + ";"
                }

    return None


# ---------------------------------------------------------
# PYTHON COLON CHECK
# ---------------------------------------------------------

def check_python_colon(code):
    """
    Detect missing colon after common Python blocks.
    """

    lines = code.splitlines()

    block_patterns = [
        r"^\s*if\b.*[^:]\s*$",
        r"^\s*elif\b.*[^:]\s*$",
        r"^\s*else\s*$",
        r"^\s*for\b.*[^:]\s*$",
        r"^\s*while\b.*[^:]\s*$",
        r"^\s*def\b.*\)\s*$",
        r"^\s*class\b.*[^:]\s*$",
        r"^\s*try\s*$",
        r"^\s*except\b.*[^:]\s*$",
        r"^\s*finally\s*$"
    ]

    for index, line in enumerate(lines):

        stripped = line.strip()

        if not stripped:
            continue

        for pattern in block_patterns:

            if re.match(pattern, line) and not stripped.endswith(":"):

                return {
                    "type": "missing_colon",
                    "line": index + 1,
                    "message": "Colon (:) is missing.",
                    "simple": (
                        "Python needs a colon at the end of this block statement."
                    ),
                    "fix": stripped + ":"
                }

    return None


# ---------------------------------------------------------
# COMMON SYNTAX CHECKS
# ---------------------------------------------------------

def check_common_errors(code, language):

    # Unclosed double quote
    for index, line in enumerate(code.splitlines()):

        quote_count = line.count('"')

        if quote_count % 2 != 0:

            return {
                "type": "unclosed_string",
                "line": index + 1,
                "message": "A string quotation mark is not closed.",
                "simple": (
                    "You started a string with a double quote (\") "
                    "but did not close it."
                ),
                "fix": 'Add the missing " at the end of the string.'
            }

    # Java case sensitivity
    if language == "java":

        if re.search(r"\bsystem\.out", code):
            return {
                "type": "java_case_error",
                "line": None,
                "message": "Java is case-sensitive.",
                "simple": (
                    "Use System.out instead of system.out."
                ),
                "fix": "Replace system.out with System.out."
            }

        if re.search(r"\bSystem\.out\.Println", code):
            return {
                "type": "java_case_error",
                "line": None,
                "message": "Java method names are case-sensitive.",
                "simple": (
                    "The correct method is println with a small p."
                ),
                "fix": "Use System.out.println(...);"
            }

    return None


# ---------------------------------------------------------
# ERROR EXPLANATION
# ---------------------------------------------------------

def explain_compiler_error(error_text, language):

    if not error_text:
        return None

    text = error_text.lower()

    # Missing semicolon
    if "expected ';'" in text or "expected ;" in text:
        return {
            "type": "missing_semicolon",
            "message": "Semicolon (;) is missing.",
            "simple": (
                f"{LANGUAGES.get(language, {}).get('name', 'The language')} "
                "expects a semicolon at the end of this statement."
            ),
            "fix": "Add ; at the end of the statement."
        }

    # Java cannot find symbol
    if "cannot find symbol" in text:

        return {
            "type": "unknown_symbol",
            "message": "The program cannot find the name you used.",
            "simple": (
                "Check the variable, method or class name. "
                "Make sure it is declared and spelled correctly."
            ),
            "fix": "Check spelling and declaration."
        }

    # Java incompatible types
    if "incompatible types" in text:

        return {
            "type": "type_error",
            "message": "The data types do not match.",
            "simple": (
                "You are trying to put one type of value "
                "into another incompatible type."
            ),
            "fix": "Check the variable type and assigned value."
        }

    # Python syntax error
    if "syntaxerror" in text:

        return {
            "type": "syntax_error",
            "message": "Python found a syntax error.",
            "simple": (
                "Check brackets, colons, quotation marks, "
                "indentation and spelling."
            ),
            "fix": "Check the line mentioned in the Python error."
        }

    # C undeclared identifier
    if "undeclared" in text:

        return {
            "type": "undeclared",
            "message": "A variable was used before it was declared.",
            "simple": (
                "Declare the variable before using it."
            ),
            "fix": "Add a variable declaration."
        }

    return {
        "type": "compiler_error",
        "message": "The compiler found an error.",
        "simple": (
            "Read the compiler message and check the line mentioned."
        ),
        "fix": "Check the syntax around the reported line."
    }


# ---------------------------------------------------------
# RUN JAVA
# ---------------------------------------------------------

def run_java(code):

    temp_dir = tempfile.mkdtemp()

    try:

        java_file = os.path.join(temp_dir, "Main.java")

        with open(java_file, "w", encoding="utf-8") as file:
            file.write(code)

        compile_process = subprocess.run(
            ["javac", java_file],
            capture_output=True,
            text=True,
            timeout=8
        )

        if compile_process.returncode != 0:

            return {
                "success": False,
                "output": compile_process.stderr
            }

        run_process = subprocess.run(
            ["java", "-cp", temp_dir, "Main"],
            capture_output=True,
            text=True,
            timeout=8
        )

        return {
            "success": run_process.returncode == 0,
            "output": (
                run_process.stdout
                if run_process.returncode == 0
                else run_process.stderr
            )
        }

    except FileNotFoundError:

        return {
            "success": False,
            "output": "Java/JDK is not installed or not available in PATH."
        }

    except subprocess.TimeoutExpired:

        return {
            "success": False,
            "output": "Program took too long to run."
        }

    finally:

        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------
# RUN C
# ---------------------------------------------------------

def run_c(code):

    temp_dir = tempfile.mkdtemp()

    try:

        c_file = os.path.join(temp_dir, "main.c")
        exe_file = os.path.join(temp_dir, "main.exe")

        with open(c_file, "w", encoding="utf-8") as file:
            file.write(code)

        compile_process = subprocess.run(
            ["gcc", c_file, "-o", exe_file],
            capture_output=True,
            text=True,
            timeout=8
        )

        if compile_process.returncode != 0:

            return {
                "success": False,
                "output": compile_process.stderr
            }

        run_process = subprocess.run(
            [exe_file],
            capture_output=True,
            text=True,
            timeout=8
        )

        return {
            "success": run_process.returncode == 0,
            "output": (
                run_process.stdout
                if run_process.returncode == 0
                else run_process.stderr
            )
        }

    except FileNotFoundError:

        return {
            "success": False,
            "output": "GCC is not installed or not available in PATH."
        }

    except subprocess.TimeoutExpired:

        return {
            "success": False,
            "output": "Program took too long to run."
        }

    finally:

        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------
# RUN PYTHON
# ---------------------------------------------------------

def run_python(code):

    temp_dir = tempfile.mkdtemp()

    try:

        python_file = os.path.join(temp_dir, "main.py")

        with open(python_file, "w", encoding="utf-8") as file:
            file.write(code)

        run_process = subprocess.run(
            ["python", python_file],
            capture_output=True,
            text=True,
            timeout=8
        )

        return {
            "success": run_process.returncode == 0,
            "output": (
                run_process.stdout
                if run_process.returncode == 0
                else run_process.stderr
            )
        }

    except FileNotFoundError:

        return {
            "success": False,
            "output": "Python is not installed or not available in PATH."
        }

    except subprocess.TimeoutExpired:

        return {
            "success": False,
            "output": "Program took too long to run."
        }

    finally:

        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------
# RUN PROGRAM
# ---------------------------------------------------------

def run_program(code, language):

    if language == "java":
        return run_java(code)

    if language == "python":
        return run_python(code)

    if language == "c":
        return run_c(code)

    return {
        "success": False,
        "output": "Unsupported programming language."
    }


# ---------------------------------------------------------
# MAIN ANALYSIS API
# ---------------------------------------------------------

@app.route("/api/analyze", methods=["POST"])
def analyze():

    data = request.get_json()

    code = data.get("code", "")
    language = data.get("language", "auto")
    execute = data.get("execute", True)

    if not code.strip():

        return jsonify({
            "success": False,
            "message": "Please enter some code."
        })

    # Auto detection
    if language == "auto":

        language = detect_language(code)

    if language not in LANGUAGES:

        return jsonify({
            "success": False,
            "message": "Could not detect the programming language.",
            "suggestion": (
                "Select Java, Python or C manually."
            )
        })

    diagnostics = []

    # Check missing semicolon
    semicolon_error = check_missing_semicolon(
        code,
        language
    )

    if semicolon_error:
        diagnostics.append(semicolon_error)

    # Python colon
    colon_error = None

    if language == "python":

        colon_error = check_python_colon(code)

        if colon_error:
            diagnostics.append(colon_error)

    # Common errors
    common_error = check_common_errors(
        code,
        language
    )

    if common_error:
        diagnostics.append(common_error)

    compiler_output = ""
    ran = False

    # Execute code
    if execute:

        result = run_program(
            code,
            language
        )

        ran = True
        compiler_output = result["output"]

        if not result["success"]:

            compiler_explanation = explain_compiler_error(
                compiler_output,
                language
            )

            if compiler_explanation:
                diagnostics.append(
                    compiler_explanation
                )

    # Remove duplicate errors
    unique_diagnostics = []

    seen = set()

    for diagnostic in diagnostics:

        key = (
            diagnostic.get("type"),
            diagnostic.get("line"),
            diagnostic.get("message")
        )

        if key not in seen:

            seen.add(key)
            unique_diagnostics.append(
                diagnostic
            )

    return jsonify({
        "success": True,
        "language": language,
        "language_name": LANGUAGES[language]["name"],
        "diagnostics": unique_diagnostics,
        "compiler_output": compiler_output,
        "ran": ran
    })


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ---------------------------------------------------------
# START FLASK SERVER
# ---------------------------------------------------------

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("       CodeSense AI Error Tutor")
    print("=" * 60)
    print()
    print("Website running at:")
    print("http://127.0.0.1:5000")
    print()
    print("Supported languages:")
    print("1. Java")
    print("2. Python")
    print("3. C")
    print()
    print("=" * 60)

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
