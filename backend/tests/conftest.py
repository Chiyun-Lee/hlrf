import os

# Before the app is imported: keep tests out of the real library, and on the API path whatever backend/.env says.
os.environ["PAPERS_DB"] = ":memory:"
os.environ["LLM_BACKEND"] = "api"
