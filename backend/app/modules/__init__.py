"""Domain modules.

Every module owns one slice of the API and follows the same shape: ``types`` for
the vocabulary, ``schemas`` for the wire contract, ``service`` for the rules,
``dependencies`` for what other modules may reuse, and ``router`` for the HTTP
surface. Nothing outside a module reaches past its ``__init__``.
"""
