"""Made-up restricted-source terms for the offline tests. The real ones are in the git-ignored
history/source/terms.json and are never written in this repository. These have the same shape: a detection-report
word, a position tool (also a restricted word, and it may break across a line), and an exercise word."""
TERMS = {
    "restricted": r"\bZQDETECT\b|QQ ?VIEW|\bDRILLX\b",
    "restricted_url": r"\.restricted\.example\b|qqview",
    "position_tool": r"QQ ?VIEW",
}
