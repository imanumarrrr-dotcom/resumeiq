"""The 'smart' engine: PDF text extraction, cleaning and match scoring."""
import re
from collections import Counter

from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TFIDF_WEIGHT = 0.7      # overall wording similarity
SKILL_WEIGHT = 0.3      # share of required skills found in the resume


def extract_text(pdf_path):
    reader = PdfReader(pdf_path)
    return " ".join((page.extract_text() or "") for page in reader.pages)


def clean(text):
    """Lowercase and strip basic punctuation."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _skills(skills_csv):
    out = []
    for s in skills_csv.split(","):
        s = clean(s)
        if s and s not in out:
            out.append(s)
    return out


def top_terms(resume_text, n=6):
    """Most-used meaningful words in the resume, as (word, 0-100 relative weight)."""
    words = [w for w in clean(resume_text).split()
             if len(w) > 2 and not w.isdigit() and w not in ENGLISH_STOP_WORDS]
    common = Counter(words).most_common(n)
    peak = common[0][1] if common else 1
    return [(w, round(c / peak * 100)) for w, c in common]


def analyse(resume_text, job_description, required_skills):
    """Return score (0-100), matched/missing skills and the two parts of the score."""
    resume = clean(resume_text)
    skills = _skills(required_skills)
    if not resume:
        return {"score": 0.0, "tfidf": 0.0, "skill_pct": 0.0, "matched": [],
                "missing": skills, "terms": []}

    reference = clean(job_description + " " + required_skills.replace(",", " "))
    matrix = TfidfVectorizer(stop_words="english").fit_transform([resume, reference])
    tfidf = float(cosine_similarity(matrix[0], matrix[1])[0][0])

    matched = [s for s in skills if re.search(r"\b" + re.escape(s) + r"\b", resume)]
    missing = [s for s in skills if s not in matched]
    skill_share = len(matched) / len(skills) if skills else 0.0
    score = TFIDF_WEIGHT * tfidf + SKILL_WEIGHT * skill_share if skills else tfidf
    return {"score": round(min(score, 1.0) * 100, 2), "tfidf": round(tfidf * 100, 1),
            "skill_pct": round(skill_share * 100, 1), "matched": matched,
            "missing": missing, "terms": top_terms(resume_text)}
