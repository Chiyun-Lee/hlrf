import os

# Before app.db is imported: keep tests out of the real library.
os.environ["PAPERS_DB"] = ":memory:"
