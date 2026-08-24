from __future__ import annotations

import random
import secrets
from dataclasses import dataclass

from toolvalue import EvalCase


@dataclass(frozen=True)
class PaperFixture:
    doi: str
    title: str
    year: int
    first_author: str
    venue: str

    @property
    def expected(self) -> dict[str, object]:
        return {
            "title": self.title,
            "year": self.year,
            "first_author": self.first_author,
        }


PAPERS = (
    PaperFixture(
        doi="10.18653/v1/N19-1423",
        title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        year=2019,
        first_author="Jacob Devlin",
        venue="NAACL-HLT",
    ),
    PaperFixture(
        doi="10.1109/CVPR.2016.90",
        title="Deep Residual Learning for Image Recognition",
        year=2016,
        first_author="Kaiming He",
        venue="CVPR",
    ),
    PaperFixture(
        doi="10.1371/journal.pone.0000308",
        title="Sharing Detailed Research Data Is Associated with Increased Citation Rate",
        year=2007,
        first_author="Heather A. Piwowar",
        venue="PLoS ONE",
    ),
    PaperFixture(
        doi="10.7554/eLife.00971",
        title="Complete dissection of transcription elongation reveals slow translocation of RNA polymerase II in a linear ratchet mechanism",
        year=2013,
        first_author="Manchuta Dangkulwanich",
        venue="eLife",
    ),
    PaperFixture(
        doi="10.1371/journal.pone.0029797",
        title="Ecological Guild Evolution and the Discovery of the World's Smallest Vertebrate",
        year=2012,
        first_author="Eric N. Rittmeyer",
        venue="PLoS ONE",
    ),
    PaperFixture(
        doi="10.1023/A:1010933404324",
        title="Random Forests",
        year=2001,
        first_author="Leo Breiman",
        venue="Machine Learning",
    ),
    PaperFixture(
        doi="10.1007/978-3-319-24574-4_28",
        title="U-Net: Convolutional Networks for Biomedical Image Segmentation",
        year=2015,
        first_author="Olaf Ronneberger",
        venue="MICCAI",
    ),
    PaperFixture(
        doi="10.1038/nature14539",
        title="Deep learning",
        year=2015,
        first_author="Yann LeCun",
        venue="Nature",
    ),
    PaperFixture(
        doi="10.1016/S0169-7552(98)00110-X",
        title="The anatomy of a large-scale hypertextual Web search engine",
        year=1998,
        first_author="Sergey Brin",
        venue="Computer Networks and ISDN Systems",
    ),
    PaperFixture(
        doi="10.1126/science.1225829",
        title="A Programmable Dual-RNA–Guided DNA Endonuclease in Adaptive Bacterial Immunity",
        year=2012,
        first_author="Martin Jinek",
        venue="Science",
    ),
    PaperFixture(
        doi="10.1038/s41586-021-03819-2",
        title="Highly accurate protein structure prediction with AlphaFold",
        year=2021,
        first_author="John Jumper",
        venue="Nature",
    ),
    PaperFixture(
        doi="10.1103/PhysRevLett.116.061102",
        title="Observation of Gravitational Waves from a Binary Black Hole Merger",
        year=2016,
        first_author="B. P. Abbott",
        venue="Physical Review Letters",
    ),
    PaperFixture(
        doi="10.1056/NEJMoa2034577",
        title="Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
        year=2020,
        first_author="Fernando P. Polack",
        venue="New England Journal of Medicine",
    ),
    PaperFixture(
        doi="10.1038/227680a0",
        title="Cleavage of Structural Proteins during the Assembly of the Head of Bacteriophage T4",
        year=1970,
        first_author="Ulrich K. Laemmli",
        venue="Nature",
    ),
    PaperFixture(
        doi="10.1145/279227.279229",
        title="The part-time parliament",
        year=1998,
        first_author="Leslie Lamport",
        venue="ACM Transactions on Computer Systems",
    ),
)


def paper_question(doi: str) -> str:
    return (
        f"Identify the peer-reviewed paper with DOI {doi}. Return its exact title, "
        "peer-reviewed publication year, and full first-author name."
    )


@dataclass(frozen=True)
class BlindPaperEvaluation:
    seed: int
    papers: tuple[PaperFixture, ...]
    cases: list[EvalCase]

    @property
    def reveal(self) -> list[dict[str, object]]:
        return [
            {
                "index": index,
                "doi": paper.doi,
                **paper.expected,
                "venue": paper.venue,
            }
            for index, paper in enumerate(self.papers, 1)
        ]


def generate_blind_evaluation(count: int, *, seed: int | None = None) -> BlindPaperEvaluation:
    if not 1 <= count <= len(PAPERS):
        raise ValueError(f"blind case count must be between 1 and {len(PAPERS)}")
    actual_seed = seed if seed is not None else secrets.randbits(63)
    selected = tuple(random.Random(actual_seed).sample(PAPERS, count))
    cases = [
        EvalCase(
            args=(paper.doi,),
            expected=paper.expected,
            metadata={"paper_index": index},
        )
        for index, paper in enumerate(selected, 1)
    ]
    return BlindPaperEvaluation(seed=actual_seed, papers=selected, cases=cases)
