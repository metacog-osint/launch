"""Offline stand-in for the GitHub API reads tools/launch.py makes when a release download answers 404
(release_get): the release listing and the repository. `assets` is what the listing shows."""
import json

API = "https://api.github.com/repos/metacog-osint/launch"


def answer(url: str, assets=()) -> bytes | None:
    """The API's reply for `url` (the repository seen, every release listed with `assets`), or None when `url` is not
    one of these API reads."""
    if url == API:
        return json.dumps({"full_name": "metacog-osint/launch"}).encode()
    if url.startswith(API + "/releases/tags/"):
        tag = url.rsplit("/", 1)[1]
        return json.dumps({"tag_name": tag, "assets": [{"name": n} for n in assets]}).encode()
    return None
