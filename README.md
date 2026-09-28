# CodeSense AI Error Tutor

CodeSense is a beginner-friendly programming error tutor.

It supports:

- Java
- Python
- C

## Features

1. Java/Python/C language selection
2. Automatic language detection
3. Syntax error detection
4. Missing semicolon detection
5. Missing Python colon detection
6. Java case-sensitive error detection
7. Compiler error explanation
8. Runtime error display
9. Suggested correction
10. Local Java execution
11. Local Python execution
12. Local C execution
13. Neon black user interface
14. Beginner-friendly explanations

## Project Structure

CodeSense_AI_Error_Tutor/

    app.py
    requirements.txt
    README.md

    templates/
        index.html

    static/
        style.css
        app.js

## Installation

Open the project folder in VS Code.

Open:

Terminal → New Terminal

Create virtual environment:

python -m venv venv

Activate it:

venv\Scripts\activate

Install Flask:

pip install -r requirements.txt

## Check Java

java -version

javac -version

## Check Python

python --version

## Check C

gcc --version

## Run

python app.py

Open:

http://127.0.0.1:5000

## Example

Java:

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello")
    }
}

CodeSense should explain:

Semicolon (;) is missing.

Simple English:

Java expects a semicolon at the end of this statement.

Suggested Fix:

System.out.println("Hello");

## Important

This project is designed for local educational use.

Do not expose arbitrary code execution to the public internet without proper sandboxing and security controls.
