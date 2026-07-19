"""Message-handler domain modules (split plan).

P0: shared helpers live in ``_common``. Domain modules (peeks, social, …)
will be extracted in later PRs without changing the public
``network.message_handler`` API.
"""
