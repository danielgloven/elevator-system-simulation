"""Reading the request CSV input."""

import csv

from .models import Request


def load_requests(path: str) -> list[Request]:
    """Load requests from a CSV with header ``time,id,source,dest``.

    Rows are returned sorted by time so the engine can release them in order;
    the engine itself still only ever reads requests for the current tick.
    """
    requests: list[Request] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"time", "id", "source", "dest"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"input {path} missing columns: {sorted(missing)}")
        for row in reader:
            requests.append(
                Request(
                    time=int(row["time"]),
                    id=row["id"].strip(),
                    source=int(row["source"]),
                    dest=int(row["dest"]),
                )
            )
    requests.sort(key=lambda r: r.time)
    return requests
