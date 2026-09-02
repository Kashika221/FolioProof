"""Skill canonicalisation.

Resume says "JS", GitHub reports "JavaScript", LinkedIn lists "ES6". Without
this step the merged profile shows all three as separate skills and the
"fusion" claim is hollow. Aliases map to a canonical display name; unknown
skills pass through with light normalisation so nothing is silently dropped.
"""
from __future__ import annotations

import re

# canonical name -> aliases (all compared lowercased/stripped)
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "JavaScript": ("js", "java script", "es6", "ecmascript", "vanilla js"),
    "TypeScript": ("ts",),
    "Python": ("python3", "py", "python 3"),
    "C++": ("cpp", "c plus plus", "cxx"),
    "C#": ("csharp", "c sharp"),
    "React": ("react.js", "reactjs", "react js"),
    "Next.js": ("nextjs", "next js", "next"),
    "Node.js": ("nodejs", "node js", "node"),
    "Express": ("express.js", "expressjs"),
    "Vue": ("vue.js", "vuejs"),
    "Angular": ("angular.js", "angularjs"),
    "PostgreSQL": ("postgres", "psql", "postgre sql"),
    "MongoDB": ("mongo",),
    "MySQL": ("my sql",),
    "scikit-learn": ("sklearn", "scikit learn"),
    "PyTorch": ("torch", "py torch"),
    "TensorFlow": ("tf", "tensor flow"),
    "OpenCV": ("cv2", "open cv"),
    "Machine Learning": ("ml",),
    "Deep Learning": ("dl",),
    "Natural Language Processing": ("nlp",),
    "Computer Vision": ("cv",),
    "Amazon Web Services": ("aws",),
    "Google Cloud Platform": ("gcp", "google cloud"),
    "Kubernetes": ("k8s", "kube"),
    "Docker": ("docker engine", "containerisation", "containerization"),
    "REST APIs": ("rest", "restful", "rest api", "restful apis", "api development"),
    "HTML": ("html5",),
    "CSS": ("css3",),
    "Tailwind CSS": ("tailwind", "tailwindcss"),
    "Git": ("git version control", "version control"),
    "Jupyter Notebook": ("jupyter", "jupyter notebooks", "ipynb"),
    "FastAPI": ("fast api",),
    "Django": ("django rest framework", "drf"),
    "Flask": ("flask api",),
    "SQL": ("structured query language",),
    "Linux": ("gnu/linux", "unix"),
}

# Things GitHub's linguist reports that are not really portfolio skills.
NON_SKILL_LANGUAGES = {"makefile", "dockerfile", "batchfile", "shell", "roff",
                       "procfile", "hcl", "cmake", "m4", "gnuplot"}

_LOOKUP: dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    _LOOKUP[canonical.lower()] = canonical
    for alias in aliases:
        _LOOKUP[alias] = canonical

_CLEAN_RE = re.compile(r"^[\s\-•*]+|[\s.,;:]+$")


def canonical_skill(raw: str) -> str | None:
    """Map a raw skill string to its canonical name, or None if it is junk."""
    if not raw:
        return None
    s = _CLEAN_RE.sub("", " ".join(raw.split()))
    if not s or len(s) > 40:
        return None

    low = s.lower()
    if low in NON_SKILL_LANGUAGES:
        return None
    # Strip proficiency noise: "Python (Advanced)" -> "Python"
    low = re.sub(r"\s*\((?:basic|intermediate|advanced|expert|proficient)\)\s*$", "", low).strip()

    if low in _LOOKUP:
        return _LOOKUP[low]

    # Preserve the source's own capitalisation for unknown skills, but title-case
    # obviously lowercase words so "docker compose" doesn't sit next to "Docker".
    return s if any(c.isupper() for c in s) else s.title()


CATEGORIES: dict[str, tuple[str, ...]] = {
    "Languages": ("Python", "JavaScript", "TypeScript", "C++", "C#", "Java", "Go",
                  "Rust", "SQL", "C", "R", "Kotlin", "Swift", "PHP", "Ruby", "Dart"),
    "Frontend": ("React", "Next.js", "Vue", "Angular", "HTML", "CSS", "Tailwind CSS",
                 "Framer Motion", "Redux", "Svelte", "Bootstrap"),
    "Backend": ("FastAPI", "Django", "Flask", "Node.js", "Express", "Spring", "REST APIs",
                "GraphQL", "gRPC", "Celery"),
    "Machine Learning": ("PyTorch", "TensorFlow", "scikit-learn", "OpenCV", "Keras",
                         "Machine Learning", "Deep Learning", "Natural Language Processing",
                         "Computer Vision", "Pandas", "NumPy", "LangChain", "Hugging Face"),
    "Data & Cloud": ("PostgreSQL", "MongoDB", "MySQL", "Redis", "SQLite", "Amazon Web Services",
                     "Google Cloud Platform", "Azure", "Firebase", "Supabase", "Elasticsearch"),
    "Tools & DevOps": ("Docker", "Kubernetes", "Git", "Linux", "CI/CD", "GitHub Actions",
                       "Jupyter Notebook", "Postman", "Nginx", "Terraform"),
}

_CATEGORY_OF = {skill: cat for cat, skills in CATEGORIES.items() for skill in skills}


def categorise(skill: str) -> str:
    return _CATEGORY_OF.get(skill, "Other")


def group_skills(skills: list[str]) -> dict[str, list[str]]:
    """Bucket canonical skills into display categories, preserving order."""
    grouped: dict[str, list[str]] = {}
    for s in skills:
        grouped.setdefault(categorise(s), []).append(s)

    ordered = [*CATEGORIES.keys(), "Other"]
    return {c: grouped[c] for c in ordered if grouped.get(c)}
