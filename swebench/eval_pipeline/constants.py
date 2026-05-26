LEVELS = [1, 2, 3]

# PRs.xlsx column names
COL_REPO = "Repo"
COL_PR_NUMBER = "PR Number"
COL_TITLE = "Title"
COL_URL = "URL"
COL_CATEGORY = "Category"
COL_ALGORITHM_NAME = "Algorithm Name"
COL_PAPER_REFERENCE = "Paper Reference"
COL_HAS_TEST = "Has Test"
COL_TEST_LINKS = "Test Links"

# Model limits (tokens)
MODEL_LIMITS = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
}

MODEL_COST_PER_INPUT = {
    "claude-sonnet-4-6": 0.000003,
    "claude-opus-4-7": 0.000015,
    "claude-haiku-4-5-20251001": 0.00000025,
    "claude-3-5-sonnet-20241022": 0.000003,
    "claude-3-5-haiku-20241022": 0.000001,
    "gpt-4o": 0.0000025,
    "gpt-4o-mini": 0.00000015,
    "gpt-4-turbo": 0.00001,
}

MODEL_COST_PER_OUTPUT = {
    "claude-sonnet-4-6": 0.000015,
    "claude-opus-4-7": 0.000075,
    "claude-haiku-4-5-20251001": 0.00000125,
    "claude-3-5-sonnet-20241022": 0.000015,
    "claude-3-5-haiku-20241022": 0.000005,
    "gpt-4o": 0.00001,
    "gpt-4o-mini": 0.0000006,
    "gpt-4-turbo": 0.00003,
}

PATCH_INSTRUCTION = (
    "Your task is to generate a single unified diff patch that, when applied with `git apply` "
    "to the repository at the base commit, implements the required change and makes the relevant tests pass.\n\n"
    "Respond ONLY with the patch in this exact format (no other text):\n"
    "<patch>\n"
    "--- a/path/to/file\n"
    "+++ b/path/to/file\n"
    "@@ ... @@\n"
    " context\n"
    "-removed line\n"
    "+added line\n"
    "</patch>"
)
