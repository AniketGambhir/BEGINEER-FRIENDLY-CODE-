// =====================================================
// STARTER CODE
// =====================================================

const starterCode = {

    java: `public class Main {
    public static void main(String[] args) {
        System.out.println("Hello CodeSense!");
    }
}`,

    python: `def main():
    print("Hello CodeSense!")

if __name__ == "__main__":
    main()`,

    c: `#include <stdio.h>

int main() {
    printf("Hello CodeSense!\\n");
    return 0;
}`

};


// =====================================================
// ERROR EXAMPLES
// =====================================================

const errorExamples = {

    java: `public class Main {
    public static void main(String[] args) {
        System.out.println("Hello CodeSense!")
    }
}`,

    python: `def main()
    print("Hello CodeSense!")

if __name__ == "__main__":
    main()`,

    c: `#include <stdio.h>

int main() {
    printf("Hello CodeSense!\\n")
    return 0;
}`

};


// =====================================================
// VARIABLES
// =====================================================

let selectedLanguage = "java";

const editor =
    document.getElementById("codeEditor");

const lineNumbers =
    document.getElementById("lineNumbers");

const detectedLanguage =
    document.getElementById("detectedLanguage");

const fileName =
    document.getElementById("fileName");

const fileIcon =
    document.getElementById("fileIcon");

const lineCount =
    document.getElementById("lineCount");

const charCount =
    document.getElementById("charCount");

const outputCard =
    document.getElementById("outputCard");

const outputStatus =
    document.getElementById("outputStatus");

const cursorGlow =
    document.querySelector(".cursor-glow");


// =====================================================
// LANGUAGE INFORMATION
// =====================================================

const languageInfo = {

    java: {
        name: "Java",
        file: "Main.java",
        icon: "JAVA"
    },

    python: {
        name: "Python",
        file: "main.py",
        icon: "PY"
    },

    c: {
        name: "C",
        file: "main.c",
        icon: "C"
    },

    auto: {
        name: "Auto Detect",
        file: "code.txt",
        icon: "AUTO"
    }

};


// =====================================================
// INITIALIZE
// =====================================================

editor.value =
    starterCode.java;

updateEditorInfo();


// =====================================================
// LANGUAGE BUTTONS
// =====================================================

document
    .querySelectorAll(".language-btn")
    .forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document
                    .querySelectorAll(".language-btn")
                    .forEach(btn =>
                        btn.classList.remove("active")
                    );

                button.classList.add("active");

                selectedLanguage =
                    button.dataset.language;

                changeLanguage();

            }
        );

    });


// =====================================================
// CHANGE LANGUAGE
// =====================================================

function changeLanguage() {

    const info =
        languageInfo[selectedLanguage];

    detectedLanguage.textContent =
        info.name;

    fileName.textContent =
        info.file;

    fileIcon.textContent =
        info.icon;

    if (selectedLanguage !== "auto") {

        editor.value =
            starterCode[selectedLanguage];

    }

    updateEditorInfo();

}


// =====================================================
// UPDATE EDITOR INFORMATION
// =====================================================

function updateEditorInfo() {

    const code =
        editor.value;

    const lines =
        code.split("\n");

    lineNumbers.innerHTML =
        lines
            .map((_, index) =>
                index + 1
            )
            .join("<br>");

    lineCount.textContent =
        `Lines: ${lines.length}`;

    charCount.textContent =
        `Characters: ${code.length}`;

}


// =====================================================
// EDITOR INPUT
// =====================================================

editor.addEventListener(
    "input",
    updateEditorInfo
);


// =====================================================
// TAB SUPPORT
// =====================================================

editor.addEventListener(
    "keydown",
    event => {

        if (event.key === "Tab") {

            event.preventDefault();

            const start =
                editor.selectionStart;

            const end =
                editor.selectionEnd;

            editor.value =
                editor.value.substring(
                    0,
                    start
                ) +
                "    " +
                editor.value.substring(
                    end
                );

            editor.selectionStart =
                editor.selectionEnd =
                    start + 4;

            updateEditorInfo();

        }


        // Ctrl + Enter
        if (
            event.ctrlKey &&
            event.key === "Enter"
        ) {

            event.preventDefault();

            analyzeCode();

        }

    }
);


// =====================================================
// RUN & EXPLAIN
// =====================================================

document
    .getElementById("runBtn")
    .addEventListener(
        "click",
        analyzeCode
    );


// =====================================================
// ANALYZE CODE
// =====================================================

async function analyzeCode() {

    const code =
        editor.value.trim();

    if (!code) {

        showMessage(
            "Please enter some code first."
        );

        return;
    }

    outputStatus.textContent =
        "ANALYZING...";

    outputCard.innerHTML = `

        <div class="empty-output">

            <div class="empty-icon">
                ⟳
            </div>

            <h3>
                Analyzing your code...
            </h3>

            <p>
                Checking syntax, compiler errors
                and possible fixes.
            </p>

        </div>

    `;


    try {

        const response =
            await fetch(
                "/api/analyze",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        language:
                            selectedLanguage,

                        code:
                            code,

                        execute:
                            true

                    })

                }
            );


        const result =
            await response.json();


        if (!result.success) {

            showMessage(
                result.message ||
                "Unable to analyze code."
            );

            return;

        }


        // Update detected language
        detectedLanguage.textContent =
            result.language_name;

        renderResult(result);


    } catch (error) {

        outputStatus.textContent =
            "ERROR";

        outputCard.innerHTML = `

            <div class="diagnostic">

                <h3>
                    Connection Error
                </h3>

                <p>
                    The website could not connect
                    to the Flask backend.
                </p>

                <div class="fix-box">
                    Make sure python app.py is running.
                </div>

            </div>

        `;

    }

}


// =====================================================
// DISPLAY RESULT
// =====================================================

function renderResult(result) {

    const diagnostics =
        result.diagnostics || [];

    const compilerOutput =
        result.compiler_output || "";


    // No error
    if (
        diagnostics.length === 0 &&
        result.ran
    ) {

        outputStatus.textContent =
            "SUCCESS";

        outputCard.innerHTML = `

            <div class="result-header">

                <span class="success-badge">
                    ✓ CODE RUN SUCCESSFULLY
                </span>

                <span>
                    ${escapeHtml(
                        result.language_name
                    )}
                </span>

            </div>

            <div class="diagnostic"
                style="
                    border-color:
                    rgba(57,255,136,0.2);
                    background:
                    rgba(57,255,136,0.03);
                "
            >

                <h3
                    style="
                        color:
                        #39ff88;
                    "
                >
                    No major error detected
                </h3>

                <p>
                    Your code compiled and ran
                    successfully.
                </p>

                ${
                    compilerOutput
                        ? `
                        <div class="fix-box">
                            ${escapeHtml(
                                compilerOutput
                            )}
                        </div>
                        `
                        : ""
                }

            </div>

        `;

        return;
    }


    outputStatus.textContent =
        diagnostics.length
            ? "ERROR FOUND"
            : "CHECK COMPLETE";


    let html = "";


    diagnostics.forEach(
        (diagnostic, index) => {

            html += `

                <div class="diagnostic">

                    <div class="result-header">

                        <span class="error-badge">
                            ⚠
                            ${escapeHtml(
                                diagnostic.type
                                    .replaceAll("_", " ")
                                    .toUpperCase()
                            )}
                        </span>

                        ${
                            diagnostic.line
                                ? `
                                <span>
                                    LINE
                                    ${diagnostic.line}
                                </span>
                                `
                                : ""
                        }

                    </div>


                    <h3>
                        ${escapeHtml(
                            diagnostic.message
                        )}
                    </h3>


                    <p>
                        <strong>
                            Simple English:
                        </strong>

                        ${escapeHtml(
                            diagnostic.simple ||
                            "Check the code around this error."
                        )}
                    </p>


                    ${
                        diagnostic.fix
                            ? `
                            <div class="fix-box">

                                <strong>
                                    Suggested Fix:
                                </strong>

                                <br><br>

                                ${escapeHtml(
                                    diagnostic.fix
                                )}

                            </div>
                            `
                            : ""
                    }

                </div>

            `;

        }
    );


    if (compilerOutput) {

        html += `

            <div class="diagnostic">

                <h3>
                    Compiler / Runtime Message
                </h3>

                <div class="fix-box">
                    ${escapeHtml(
                        compilerOutput
                    )}
                </div>

            </div>

        `;

    }


    outputCard.innerHTML =
        html;

}


// =====================================================
// MESSAGE
// =====================================================

function showMessage(message) {

    outputStatus.textContent =
        "READY";

    outputCard.innerHTML = `

        <div class="empty-output">

            <div class="empty-icon">
                !
            </div>

            <h3>
                ${escapeHtml(message)}
            </h3>

        </div>

    `;

}


// =====================================================
// SAMPLE BUTTON
// =====================================================

document
    .getElementById("sampleBtn")
    .addEventListener(
        "click",
        () => {

            if (
                selectedLanguage === "auto"
            ) {

                editor.value =
                    starterCode.java;

            } else {

                editor.value =
                    starterCode[selectedLanguage];

            }

            updateEditorInfo();

        }
    );


// =====================================================
// CLEAR BUTTON
// =====================================================

document
    .getElementById("clearBtn")
    .addEventListener(
        "click",
        () => {

            editor.value = "";

            updateEditorInfo();

            outputStatus.textContent =
                "READY";

            outputCard.innerHTML = `

                <div class="empty-output">

                    <div class="empty-icon">
                        ✦
                    </div>

                    <h3>
                        Editor cleared
                    </h3>

                    <p>
                        Enter your code to begin.
                    </p>

                </div>

            `;

        }
    );


// =====================================================
// COPY BUTTON
// =====================================================

document
    .getElementById("copyBtn")
    .addEventListener(
        "click",
        async () => {

            try {

                await navigator.clipboard.writeText(
                    editor.value
                );

                const button =
                    document.getElementById(
                        "copyBtn"
                    );

                button.textContent =
                    "Copied!";

                setTimeout(
                    () => {
                        button.textContent =
                            "Copy";
                    },
                    1200
                );

            } catch {

                alert(
                    "Unable to copy code."
                );

            }

        }
    );


// =====================================================
// ERROR EXAMPLE
// =====================================================

document
    .getElementById("errorExampleBtn")
    .addEventListener(
        "click",
        () => {

            if (
                selectedLanguage === "auto"
            ) {

                selectedLanguage =
                    "java";

                document
                    .querySelectorAll(
                        ".language-btn"
                    )
                    .forEach(
                        btn =>
                            btn.classList.remove(
                                "active"
                            )
                    );

                document
                    .querySelector(
                        '[data-language="java"]'
                    )
                    .classList.add(
                        "active"
                    );

                changeLanguage();

            }

            editor.value =
                errorExamples[
                    selectedLanguage
                ];

            updateEditorInfo();

            analyzeCode();

        }
    );


// =====================================================
// CURSOR GLOW
// =====================================================

document.addEventListener(
    "mousemove",
    event => {

        cursorGlow.style.left =
            `${event.clientX}px`;

        cursorGlow.style.top =
            `${event.clientY}px`;

    }
);


// =====================================================
// HTML ESCAPE
// =====================================================

function escapeHtml(value) {

    return String(value)

        .replaceAll("&", "&amp;")

        .replaceAll("<", "&lt;")

        .replaceAll(">", "&gt;")

        .replaceAll('"', "&quot;")

        .replaceAll(
            "'",
            "&#039;"
        );

}
