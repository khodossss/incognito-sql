"""The sets' inputs: their questions, the SecureSQL samples, each marked database's file."""

from pathlib import Path

from bench.external import sources
from bench.external.marking import Marking
from bench.external.sets import Question, Record, bird, read, securesql, spider

DATABASES = {"spider": sources.SPIDER_DATABASES, "bird": sources.BIRD_DATABASES}
Archives = dict[str, Path]  # set -> its downloaded archive


def load() -> tuple[Archives, list[Question], list[Record]]:
    """Fetch the sets; return the archives, every question and every SecureSQL sample."""
    spider_zip, bird_zip = sources.fetch(sources.SPIDER), sources.fetch(sources.BIRD)
    questions = spider(read(sources.member(spider_zip, sources.SPIDER_QUESTIONS)))
    questions += bird(read(sources.member(bird_zip, sources.BIRD_QUESTIONS)))
    records = securesql(read(sources.fetch(sources.SECURESQL)))
    return {"spider": spider_zip, "bird": bird_zip}, questions, records


def database(archives: Archives, marking: Marking) -> Path:
    """Return the file of the marked database, out of its set's archive."""
    name = f"{DATABASES[marking.source]}/{marking.db}/{marking.db}.sqlite"
    return sources.member(archives[marking.source], name)
