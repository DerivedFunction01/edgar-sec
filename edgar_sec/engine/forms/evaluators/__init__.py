"""Per-form stub and delegation evaluators.

Each module exposes one ``evaluate_*`` entry point taking a payload and
returning an ``EvaluatorDecision``. The plugin registry binds them lazily, so
importing the registry does not import this package.
"""
