from app import ranker
from helpers import COSMOLOGY, QUBITS, arxiv_paper


def corpus_and_papers():
    liked = [arxiv_paper(f"2610.1000{i}", t) for i, t in enumerate(COSMOLOGY)]
    rejected = [arxiv_paper(f"2610.2000{i}", t, category="quant-ph") for i, t in enumerate(QUBITS)]
    new = [
        arxiv_paper("2610.30001", "Galaxy clustering bispectrum analysis with the effective field theory"),
        arxiv_paper("2610.30002", "Transmon qubit error correction with superconducting couplers"),
    ]
    return ranker.Corpus(liked + rejected + new), liked, rejected, new


def test_too_few_likes_means_no_model():
    corpus, liked, rejected, new = corpus_and_papers()
    assert ranker.train(corpus, new, liked[:2], rejected) is None


def test_model_ranks_the_liked_topic_first():
    corpus, liked, rejected, new = corpus_and_papers()
    model = ranker.train(corpus, new, liked, rejected)
    scores = model.score(new)
    assert scores[0] > scores[1]
    why = model.reasons(new)[0]
    assert why["topics"] and all(t.lower() not in ranker.GENERIC_WORDS for t in why["topics"])


def test_reasons_skip_latex_and_name_authors():
    liked = [arxiv_paper(f"2610.1000{i}", f"Constraints on $f_{{\\rm NL}}$ from the bispectrum, part {i}", authors=["Ada Lovelace"]) for i in range(3)]
    other = [arxiv_paper(f"2610.2000{i}", f"Transmon qubits, part {i}", category="quant-ph") for i in range(3)]
    new = arxiv_paper("2610.30001", "Bispectrum $f_{\\rm NL}$ forecasts", authors=["Ada Lovelace", "B. Babbage"])
    model = ranker.train(ranker.Corpus(liked + other + [new]), other, liked, [])
    why = model.reasons([new])[0]
    assert "rm" not in why["topics"] and "nl" not in why["topics"]
    assert "Bispectrum" in why["topics"]  # as printed
    assert why["authors"] == ["Ada Lovelace"]  # as printed, not the lowercased token
