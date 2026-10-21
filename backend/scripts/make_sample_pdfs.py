"""Make the sample PDF statements in sample_data/ (used by the tests and for trying the upload).

    pip install reportlab
    python -m scripts.make_sample_pdfs

These are made-up example statements, not real broker documents.
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[2] / "sample_data"

ROWS = [
    ("INFY", 40, "1,420.50"), ("TCS", 12, "3,350.00"), ("HDFCBANK", 80, "880.25"),
    ("ICICIBANK", 45, "1,210.00"), ("RELIANCE", 60, "1,290.75"), ("ITC", 250, "395.10"),
    ("SUNPHARMA", 25, "1,540.00"), ("BHARTIARTL", 30, "1,610.40"), ("LT", 10, "3,420.00"),
    ("MARUTI", 3, "11,800.00"),
]


def table_statement():
    """A ruled table that continues onto a second page, with the header repeated."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT / "holdings_statement_table.pdf"), pagesize=A4, title="Sample holdings statement")
    header = ["Symbol", "ISIN", "Qty.", "Avg. cost", "LTP"]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)])
    page1 = [header] + [[s, "INE000000000", str(q), p, "-"] for s, q, p in ROWS[:6]]
    page2 = [header] + [[s, "INE000000000", str(q), p, "-"] for s, q, p in ROWS[6:]]
    story = [
        Paragraph("Sample Broker Ltd. - Equity Holdings Statement", styles["Title"]),
        Paragraph("Client: Demo User (example document, not a real statement)", styles["Normal"]),
        Spacer(1, 12), Table(page1, style=grid), PageBreak(),
        Paragraph("Holdings (continued)", styles["Heading2"]), Table(page2, style=grid),
        Spacer(1, 12), Paragraph("Total holdings value: see your broker app.", styles["Normal"]),
    ]
    doc.build(story)


def text_statement():
    """No table at all: holdings written as sentences. Only the AI step can read this."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT / "holdings_statement_text.pdf"), pagesize=A4, title="Sample portfolio letter")
    story = [
        Paragraph("Quarterly portfolio letter (example document)", styles["Title"]),
        Paragraph("Dear investor, here is a summary of the shares in your demat account.", styles["Normal"]),
        Spacer(1, 8),
        Paragraph("You hold 40 shares of Infosys Ltd, bought at an average price of Rs 1,420.50 per share.", styles["Normal"]),
        Paragraph("Your position in HDFC Bank Ltd is 80 shares with an average cost of Rs 880.25.", styles["Normal"]),
        Paragraph("You also own 250 shares of ITC Ltd at an average of Rs 395.10.", styles["Normal"]),
        Spacer(1, 8),
        Paragraph("Your cash balance is Rs 12,000. Thank you for investing with us.", styles["Normal"]),
    ]
    doc.build(story)


if __name__ == "__main__":
    table_statement()
    text_statement()
    print("Wrote sample PDFs to", OUT)
