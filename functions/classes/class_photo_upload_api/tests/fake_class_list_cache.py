"""An in-memory ``ClassListCache`` for tests: no AWS."""

from functions.classes.class_photo_upload_api.class_list_cache import CacheUnavailable, ClassListRecord


class InMemoryClassListCache:
    """Keeps one record; counts calls; can be told to fail like a backend outage."""

    def __init__(self, record: ClassListRecord | None = None) -> None:
        self.record = record
        self.gets = 0
        self.puts: list[ClassListRecord] = []
        self.fail_get: str | None = None
        self.fail_put: str | None = None

    def get(self) -> ClassListRecord | None:
        self.gets += 1
        if self.fail_get is not None:
            raise CacheUnavailable(self.fail_get)
        return self.record

    def put(self, record: ClassListRecord) -> None:
        if self.fail_put is not None:
            raise CacheUnavailable(self.fail_put)
        self.puts.append(record)
        self.record = record
