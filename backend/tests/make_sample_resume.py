"""Generate a realistic text-based resume PDF for testing the extractor.

Run:  python tests/make_sample_resume.py
Writes tests/fixtures/sample_resume.pdf
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures" / "sample_resume.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

W, H = A4
LEFT = 0.85 * inch
RIGHT = W - 0.85 * inch


def build() -> None:
    c = canvas.Canvas(str(OUT), pagesize=A4)
    y = H - 0.9 * inch

    def name(text):
        nonlocal y
        c.setFont("Helvetica-Bold", 20)
        c.drawString(LEFT, y, text)
        y -= 20

    def contact(text):
        nonlocal y
        c.setFont("Helvetica", 9.5)
        c.drawString(LEFT, y, text)
        y -= 22

    def heading(text):
        nonlocal y
        y -= 6
        c.setFont("Helvetica-Bold", 12)
        c.drawString(LEFT, y, text.upper())
        y -= 4
        c.setStrokeColorRGB(0.6, 0.6, 0.6)
        c.line(LEFT, y, RIGHT, y)
        y -= 13

    def line(text, bold=False, indent=0.0):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(LEFT + indent, y, text)
        y -= 13

    def bullet(text, indent=12):
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(LEFT + indent, y, "• " + text)
        y -= 13

    name("Aarav Sharma")
    contact("aarav.sharma@example.com  |  +91 98xxx xxxxx  |  New Delhi, India  |  "
            "github.com/aaravsharma  |  linkedin.com/in/aaravsharma")

    heading("Summary")
    line("Final-year IT undergraduate focused on backend systems and applied machine")
    line("learning. Comfortable shipping end-to-end: data pipelines, APIs and deployment.")

    heading("Education")
    line("B.Tech, Information Technology", bold=True)
    line("Maharaja Surajmal Institute of Technology, GGSIPU    2022 - 2026    CGPA: 8.7")

    heading("Experience")
    line("Backend Engineering Intern, Nexora Labs    Jun 2025 - Aug 2025", bold=True)
    bullet("Built ingestion service handling 40k events/day using FastAPI and Celery.")
    bullet("Cut p95 API latency from 820ms to 210ms by adding Redis caching.")
    line("Machine Learning Intern, IIT Delhi    Jan 2025 - May 2025", bold=True)
    bullet("Trained YOLOv8 detector for aerial imagery; improved mAP50 from 0.71 to 0.84.")

    heading("Projects")
    line("MediTrack - Hospital Inventory System", bold=True)
    bullet("Built a website.")
    line("SignSpeak", bold=True)
    bullet("Real-time sign language recognition using MediaPipe and a small CNN.")
    line("Campus Event Portal", bold=True)
    bullet("Django app for managing college events with role-based access.")

    heading("Skills")
    line("Languages: Python, JavaScript, C++, SQL")
    line("Frameworks: FastAPI, Django, React, PyTorch")
    line("Tools: Docker, Git, PostgreSQL, Linux")

    heading("Certifications")
    bullet("AWS Certified Cloud Practitioner - 2025")
    bullet("DeepLearning.AI Machine Learning Specialization - 2024")

    heading("Achievements")
    bullet("Winner, Smart India Hackathon internal round 2025.")
    bullet("Merit scholarship recipient, 2023 and 2024.")

    c.showPage()
    c.save()
    print("wrote", OUT)


if __name__ == "__main__":
    build()
