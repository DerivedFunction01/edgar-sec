"""SGML envelope unpacking and ASCII-PRE discrimination.
An EDGAR bundle concatenates every attachment; this package unwraps it into sub-documents and
answers the question the rest of the engine branches on: real HTML, or ASCII inside `<PRE>`?
"""
