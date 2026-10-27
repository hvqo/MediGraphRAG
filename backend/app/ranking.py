"""Reusable inverted lexical index and literal mention graph; no generated medical assertions."""

from collections import Counter, defaultdict
import math
import re

STOP = set(
    "about above after again against also among because before being between both could does during each from further have into itself more most other over same should some such than that their them then there these they this those through under until very were what when where which while with would your study studies results conclusion patients effects effect using used shown show associated association compared based".split()
)


class LexicalIndex:
    def __init__(self, texts, tokenize):
        self.tokenize = tokenize
        self.postings = defaultdict(dict)
        self.lengths = []
        for index, text in enumerate(texts):
            terms = Counter(tokenize(text))
            self.lengths.append(sum(terms.values()))
            for term, count in terms.items():
                self.postings[term][index] = count
        self.n = len(texts)
        self.average = sum(self.lengths) / max(1, self.n) or 1

    def rank(self, query, limit=30):
        scores = defaultdict(float)
        for term in set(self.tokenize(query)):
            posting = self.postings.get(term, {})
            inverse = math.log(1 + (self.n - len(posting) + 0.5) / (len(posting) + 0.5))
            for index, count in posting.items():
                scores[index] += (
                    inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * self.lengths[index] / self.average))
                )
        return sorted(scores.items(), key=lambda p: (-p[1], p[0]))[:limit]


class MentionGraph:
    """Document -> exact terms -> other documents, a retrieval hint rather than a clinical fact graph."""

    def __init__(self, titles):
        self.docs = []
        self.postings = defaultdict(set)
        for index, title in enumerate(titles):
            terms = {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in STOP}
            for word in re.findall(r"[\u4e00-\u9fff]+", title):
                terms.update(word[i : i + 3] for i in range(max(0, len(word) - 2)))
            self.docs.append(terms)
            for term in terms:
                self.postings[term].add(index)

    def rank(self, query, limit=30):
        terms = {w for w in re.findall(r"[a-z]{4,}", query.lower()) if w not in STOP and w in self.postings}
        for word in re.findall(r"[\u4e00-\u9fff]+", query):
            terms.update(word[i : i + 3] for i in range(max(0, len(word) - 2)) if word[i : i + 3] in self.postings)
        terms = sorted(terms, key=lambda w: (len(self.postings[w]), w))[:6]
        score = defaultdict(float)
        for term in terms:
            for doc in self.postings[term]:
                score[doc] += 1 / math.log2(2 + len(self.postings[term]))
        seeds = sorted(score, key=lambda i: (-score[i], i))[:5]
        for doc in seeds:
            for term in sorted(self.docs[doc] - set(terms), key=lambda t: (len(self.postings[t]), t))[:3]:
                for other in self.postings[term]:
                    score[other] += 0.15 / math.log2(2 + len(self.postings[term]))
        return sorted(score.items(), key=lambda p: (-p[1], p[0]))[:limit]


def reciprocal_fusion(*rankings, limit=30):
    score = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            score[item[0]] += 1 / (60 + rank)
    return sorted(score.items(), key=lambda p: (-p[1], p[0]))[:limit]
