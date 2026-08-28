"""Authorization-only helpers for the sealed NFL EDGE holdout.

Nothing in this package authorizes reading sealed data by itself.  The canonical
entrypoint in ``scripts/task05g_2025_holdout_one_shot_v1.py`` must verify the
Master authorization gate before any real 2025 input is opened.

Development runners remain sealed at 2024; holdout adapters live here so their
existence cannot weaken those development firewalls.
"""
