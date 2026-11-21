# forms

## Purpose

The form-domain scanners: `form_isolation` keeps one form's parsing code
from leaking into another form's surface, `form_vocabulary` keeps form
vocabulary homed in the form modules that own it, and
`tables_form_literals` keeps table code from carrying private form
literals. These are the scanners whose subject is the SEC form domain
itself rather than a general code rule.

## Contracts

- **Form surfaces stay isolated**: cross-form references resolve through
  the shared form modules, never by one form importing another's
  internals; the allowances are named inside the owning scanner.
- **Registration is central**: every module here registers only through
  `ALL_SCANNERS` in the parent package's `__init__.py`.
- **Support flows from the parent root**: modules import `Scanner`,
  discovery, and the text-rule helpers from the parent package's root
  modules (`base`, `files`, `lines`), never from a sibling subpackage.

## Deliberate gaps

- **Named forms only**: a form with no registered vocabulary or isolation
  entry is invisible to this family until its scanner entry is added.
