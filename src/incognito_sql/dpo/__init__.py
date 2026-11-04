"""`report`: what the model may learn of each column and what it asked, for a DPO.

Read from files only: the declaration, an `assess` report if one is given, and the audit
log. Nothing is asked of the database. The report holds counts, names, classes,
profiles and refusal reasons, never a value nor a query.
"""
