"""Tests for the LaTeX syntax validator."""

from resume_agent.tools.latex_syntax import check_latex


def test_balanced_braces():
    source = r"""
\documentclass{article}
\begin{document}
Hello \textbf{world}
\end{document}
"""
    result = check_latex(source)
    # Should not report brace errors for this balanced source
    brace_errors = [e for e in result.errors if "brace" in e.lower()]
    assert len(brace_errors) == 0


def test_unbalanced_open_brace():
    source = r"""
\documentclass{article}
\begin{document}
Hello \textbf{world
\end{document}
"""
    result = check_latex(source)
    assert not result.ok
    assert any("brace" in e.lower() or "unclosed" in e.lower() for e in result.errors)


def test_mismatched_environments():
    source = r"""
\documentclass{article}
\begin{document}
\begin{itemize}
  \item hello
\end{enumerate}
\end{document}
"""
    result = check_latex(source)
    assert not result.ok
    assert any("itemize" in e or "enumerate" in e for e in result.errors)


def test_unclosed_environment():
    source = r"""
\documentclass{article}
\begin{document}
\begin{itemize}
  \item hello
\end{document}
"""
    result = check_latex(source)
    assert not result.ok
    assert any("itemize" in e for e in result.errors)


def test_valid_complex_source():
    source = r"""
\documentclass[10pt]{article}
\usepackage{geometry}
\begin{document}
\section{Experience}
\begin{itemize}
  \item Led a team of 5 engineers
  \item Built distributed systems at scale
\end{itemize}
\section{Skills}
\begin{tabular}{ll}
  Python & Go \\
  Docker & Kubernetes \\
\end{tabular}
\end{document}
"""
    result = check_latex(source)
    assert result.ok
