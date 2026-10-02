"""SGML envelope unpacking and ASCII-PRE discrimination.

An EDGAR submission arrives as one `.txt`/`.nc` bundle concatenating every
attachment. This package unwraps that envelope into discrete sub-documents and
answers the representation question the rest of the engine depends on: is this
payload real HTML, or is it ASCII that merely happens to be wrapped in a
`<PRE>` transport element?
"""
