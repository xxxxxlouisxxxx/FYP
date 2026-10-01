"""HKTDC Hidden Opportunity Discovery Platform (HOP).

Three layers, with imports flowing strictly downwards:

* ``hop.platform``   - reusable, domain-agnostic enterprise AI platform services.
* ``hop.products``   - products built on the platform (Opportunity Intelligence).
* ``domain_packs/``  - validated configuration (YAML) installed into a product; no Python code.

``hop.bootstrap`` and the CLI / API / dashboard entry points are the only composition roots.
"""

__version__ = "0.1.0"
