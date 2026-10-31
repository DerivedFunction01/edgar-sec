"""Layer 3 engine: transformation of SEC payloads. The transformation packages
(`document`, `tables`, `reflow`, `forms`, `submissions`) are pure; `selection` and
`company_family` are the exceptions, reading and writing through `infra/storage`.
"""
