"""Generate a LinkedIn-export-style PDF that deliberately CONTRADICTS the résumé.

Used to prove source precedence end to end: the résumé says the degree ends in
2026, this says 2027, and the fused profile must keep 2026 because the résumé
outranks LinkedIn.

Run:  python tests/make_sample_linkedin.py
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures" / "sample_linkedin.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = A4
LEFT = 0.85 * inch


def build() -> None:
    c = canvas.Canvas(str(OUT), pagesize=A4)
    y = H - 0.9 * inch

    def line(text, size=10, bold=False, gap=14, indent=0.0):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(LEFT + indent, y, text)
        y -= gap

    def heading(text):
        nonlocal y
        y -= 8
        c.setFont("Helvetica-Bold", 12)
        c.drawString(LEFT, y, text)
        y -= 15

    line("Kashika Malhotra", size=18, bold=True, gap=18)
    line("Software Engineer | AI/ML", size=10, gap=20)

    # Real LinkedIn exports carry the person's "About" text under a Summary
    # heading. It is the strongest available signal for voice and positioning,
    # so the fixture has to include one for the About-section path to be tested.
    heading("Summary")
    line("I build AI systems that people actually use. Most of my work sits at the")
    line("intersection of computer vision and everyday problems - helping a")
    line("physiotherapy patient check their own form, or spotting a forged")
    line("certificate before a human has to. I care about the part after the model")
    line("works: shipping it, and making it understandable to whoever depends on it.")

    heading("Top Skills")
    line("Python")
    line("JS")                      # alias of JavaScript -> tests canonicalisation
    line("Docker")

    heading("Education")
    line("Maharaja Surajmal Institute of Technology", bold=True)
    # Deliberately contradicts any résumé it is paired with: 2028 is later than
    # both the synthetic fixture (2026) and a real résumé (2027), so a conflict
    # always fires and precedence has to keep the résumé's year.
    line("Bachelor of Technology - Information Technology, 2021 - 2028")

    heading("Experience")
    line("Software Engineer Intern", bold=True)
    line("Nexora Labs, Jun 2025 - Aug 2025")

    heading("Certifications")
    line("Google Data Analytics Certificate")

    c.showPage()
    c.save()
    print("wrote", OUT)


if __name__ == "__main__":
    build()
