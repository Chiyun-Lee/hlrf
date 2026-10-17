"""Ranks a day's arXiv papers for you, along the lines of benty-fields' published engine
(github.com/fbeutler/benty_fields_ML_model).

A logistic regression on TF-IDF words, two-word phrases and author names. Positives are papers you wrote, liked,
opened or saved to the library; negatives are papers you rejected plus random stored papers (unlabelled, so half
weight). Word and author weights come from every stored paper rather than only yours, which ranks better when you've
liked only a handful.
"""

import random
import re
from dataclasses import dataclass

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from .schemas import ArxivPaper

MIN_POSITIVES = 3  # papers you like before your model replaces newest-first
IMPLICIT_NEGATIVE_WEIGHT = 0.5
# reasons() skips words in at least this fraction of papers (once there are enough papers to tell), and these words.
REASON_MAX_DF = 0.2
REASON_MIN_CORPUS = 50
GENERIC_WORDS = frozenset(
    "new using used use based show shows shown find finds found result results present presents presented paper "
    "work study studies approach method methods analysis known test tests free constructed allow allows provide "
    "provides obtain obtained recent recently different large small high low fast accurate robust simple general "
    "propose proposed demonstrate including given effects effect data model models framework question questions "
    "improve improves improved".split()
)


def text(p: ArxivPaper) -> str:
    return f"{p.title}. {p.abstract}"


def author_tokens(authors: list[str]) -> list[str]:
    return [a.lower() for a in authors]


class Corpus:
    """Word and author weights over every stored paper, shared by all rankings until the corpus grows."""

    def __init__(self, papers: list[ArxivPaper]):
        self.n = len(papers)
        self.words = TfidfVectorizer(
            stop_words="english",
            sublinear_tf=True,
            ngram_range=(1, 2),
            min_df=2 if self.n >= 50 else 1,
            token_pattern=r"(?u)\b[^\W\d_]{2,}\b",  # words of two or more letters: no numbers or single letters
        ).fit([text(p) for p in papers])
        self.authors = TfidfVectorizer(analyzer=author_tokens).fit([p.authors for p in papers])

    def features(self, papers: list[ArxivPaper]):
        return hstack([self.words.transform([text(p) for p in papers]), self.authors.transform([p.authors for p in papers])]).tocsr()


@dataclass
class Model:
    corpus: Corpus
    classifier: LogisticRegression

    def score(self, papers: list[ArxivPaper]) -> np.ndarray:
        """Probability that you'd find each paper relevant."""
        return self.classifier.predict_proba(self.corpus.features(papers))[:, 1] if papers else np.array([])

    def reasons(self, papers: list[ArxivPaper], top: int = 3) -> list[dict[str, list[str]]]:
        """Per paper, the words and authors that raised its score most: {"topics": [...], "authors": [...]}."""
        if not papers:
            return []
        words = self.corpus.words.get_feature_names_out()
        names = np.concatenate([words, self.corpus.authors.get_feature_names_out()])
        # Words in a fifth or more of the corpus ("cosmological", "dark") drive scores but explain nothing.
        # Document frequency from smooth IDF: idf = ln((1 + n) / (1 + df)) + 1.
        n = self.corpus.n
        common = ((1 + n) / np.exp(self.corpus.words.idf_ - 1) - 1) / n >= REASON_MAX_DF if n >= REASON_MIN_CORPUS else np.zeros(len(words), bool)
        contributions = self.corpus.features(papers).multiply(self.classifier.coef_[0]).tocsr()
        result = []
        for paper, row in zip(papers, contributions):
            prose = re.sub(r"\$[^$]*\$", " ", text(paper))  # words inside $...$ are LaTeX commands, not topics
            printed_names = {a.lower(): a for a in paper.authors}
            topics: list[str] = []
            people: list[str] = []
            order = np.argsort(-row.data)
            for value, column in zip(row.data[order], row.indices[order]):
                if value <= 0 or len(topics) + len(people) == top:
                    break
                term = str(names[column])
                if column >= len(words):
                    people.append(printed_names.get(term, term))
                    continue
                if common[column] or term in GENERIC_WORDS or len(term) < 3:
                    continue
                # As printed ("BAO", "dark-energy"), with any hyphenated first part ("large-scale structure").
                printed = re.search(r"\b(?:\w+-)?" + r"[\s-]+".join(map(re.escape, term.split())) + r"\b", prose, re.I)
                if printed and not any(term in t.lower() or t.lower() in term for t in topics):
                    topics.append(printed.group(0))
            result.append({"topics": topics, "authors": people})
        return result


def train(corpus: Corpus, everything: list[ArxivPaper], positives: list[ArxivPaper], negatives: list[ArxivPaper]) -> Model | None:
    """Your model, or None until you've liked MIN_POSITIVES papers. `everything` supplies the random negatives."""
    if len(positives) < MIN_POSITIVES:
        return None
    seen = {p.id for p in positives + negatives}
    pool = [p for p in everything if p.id not in seen]
    # A fixed seed, so the same signals always give the same order.
    unlabelled = random.Random(0).sample(pool, min(len(pool), max(len(positives) - len(negatives), 0)))
    if not (negatives or unlabelled):
        return None
    papers = positives + negatives + unlabelled
    labels = np.array([1] * len(positives) + [0] * (len(negatives) + len(unlabelled)))
    weights = np.array([1.0] * (len(positives) + len(negatives)) + [IMPLICIT_NEGATIVE_WEIGHT] * len(unlabelled))
    classifier = LogisticRegression(class_weight="balanced", max_iter=1000)
    classifier.fit(corpus.features(papers), labels, sample_weight=weights)
    return Model(corpus, classifier)
