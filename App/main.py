import os
import io
import json
import csv
import re
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import fitz
from openai import OpenAI
from openpyxl import Workbook

load_dotenv()

BASE = os.path.dirname(__file__)
STATIC = os.path.join(BASE, "static")

app = FastAPI(title="Paper Invoice Intelligence", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "20"))
MAX_PDF_IMAGE_PAGES = int(os.getenv("MAX_PDF_IMAGE_PAGES", "12"))
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "180000"))
MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def pdf_text(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    chunks = []
    for page in doc:
        chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


def pdf_images(data: bytes):
    doc = fitz.open(stream=data, filetype="pdf")
    images = []
    for i, page in enumerate(doc):
        if i >= MAX_PDF_IMAGE_PAGES:
            break
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        import base64
        b64 = base64.b64encode(pix.tobytes("jpeg")).decode()
        images.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    return images


def image_part(data: bytes, filename: str):
    import base64
    ext = filename.lower().rsplit(".", 1)[-1]
    mime = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","webp":"image/webp"}.get(ext, "image/jpeg")
    b64 = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def get_client():
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "OPENROUTER_API_KEY is not configured.")
    return OpenAI(
        api_key=key,
        base_url=BASE_URL,
        default_headers={
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost:8000"),
            "X-Title": "Paper Invoice Intelligence",
        },
    )


def clean_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


SYSTEM_PROMPT = """
You are an invoice and logistics document extraction engine.

Extract information ONLY when supported by the supplied documents. Never invent or guess.
The user can request fields in natural language.

Document rules:
- Invoice commercial fields normally come from invoices.
- Package count, net weight, gross weight and dimensions normally come from packing lists.
- If invoice and packing list both contain net weight, prefer the packing-list value and record its source.
- Match related documents using invoice number, packing-list number, PO, shipment/reference numbers,
  supplier, buyer, consignee and item descriptions.
- If documents conflict, keep the conflicting values visible and add a warning.
- Preserve original units and currencies.
- Missing values must be null.
- Confidence must reflect evidence quality, not certainty invented by the model.

Return valid JSON only using this shape:
{
  "records": [
    {
      "record_id": "1",
      "document_type": "invoice|packing_list|combined|other",
      "source_documents": ["filename.pdf"],
      "fields": {},
      "line_items": [],
      "confidence": 0.0,
      "warnings": [],
      "field_sources": {}
    }
  ],
  "summary": {
    "documents_processed": 0,
    "records_found": 0,
    "warnings": 0
  }
}
"""


def extract_with_ai(documents, request_text):
    client = get_client()

    content = [{
        "type": "text",
        "text": (
            SYSTEM_PROMPT
            + "\nUSER REQUEST:\n" + request_text
            + "\n\nDOCUMENTS:\n"
            "Each document below is identified by its filename. Extract across all documents."
        )
    }]

    for filename, data, kind in documents:
        content.append({"type": "text", "text": f"\n--- DOCUMENT: {filename} ({kind}) ---"})
        if kind == "pdf":
            text = pdf_text(data)
            if len(text) >= 80:
                content.append({"type": "text", "text": text[:MAX_TEXT_CHARS]})
            else:
                content.extend(pdf_images(data))
        else:
            content.append(image_part(data, filename))

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        result = clean_json(raw)
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)}")

    return reconcile(result)


def norm(v):
    if v is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(v).lower())


def find_field(fields, names):
    if not isinstance(fields, dict):
        return None
    wanted = {norm(x) for x in names}
    for k, v in fields.items():
        if norm(k) in wanted and v not in (None, ""):
            return v
    return None


def reconcile(result):
    records = result.get("records", [])
    packing = [r for r in records if r.get("document_type") == "packing_list"]
    invoices = [r for r in records if r.get("document_type") == "invoice"]

    for inv in invoices:
        inv_fields = inv.setdefault("fields", {})
        inv_keys = []
        for names in [
            ["invoice_number", "invoice_no", "invoice"],
            ["po_number", "po_no", "purchase_order"],
            ["shipment_reference", "reference", "ref_no"],
            ["supplier", "seller", "exporter"],
            ["buyer", "consignee", "customer"],
        ]:
            val = find_field(inv_fields, names)
            if val:
                inv_keys.append(norm(val))

        for pl in packing:
            pl_fields = pl.setdefault("fields", {})
            pl_keys = []
            for names in [
                ["invoice_number", "invoice_no", "invoice"],
                ["po_number", "po_no", "purchase_order"],
                ["shipment_reference", "reference", "ref_no"],
                ["supplier", "seller", "exporter"],
                ["buyer", "consignee", "customer"],
            ]:
                val = find_field(pl_fields, names)
                if val:
                    pl_keys.append(norm(val))

            matched = bool(set(inv_keys) & set(pl_keys))
            if not matched:
                continue

            pl_net = find_field(pl_fields, ["net_weight", "netweight", "net_wt"])
            if pl_net is not None:
                old = find_field(inv_fields, ["net_weight", "netweight", "net_wt"])
                inv_fields["net_weight"] = pl_net
                inv.setdefault("field_sources", {})["net_weight"] = pl.get("source_documents", ["packing list"])[0]
                if old not in (None, "", pl_net):
                    inv.setdefault("warnings", []).append(
                        f"Net weight differs between invoice ({old}) and packing list ({pl_net}); packing-list value used."
                    )

    result["summary"] = {
        "documents_processed": sum(len(r.get("source_documents", [])) for r in records),
        "records_found": len(records),
        "warnings": sum(len(r.get("warnings", [])) for r in records),
    }
    return result


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "provider": "openrouter",
        "model": MODEL,
        "api_key_configured": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@app.post("/api/extract")
async def extract(request: str = Form("Extract invoice number, date, supplier, buyer, currency, total amount, line items, package count, gross weight and net weight."),
                  files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Upload at least one document.")

    docs = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename}: file exceeds {MAX_FILE_MB} MB.")
        ext = (f.filename or "").lower().rsplit(".", 1)[-1]
        if ext == "pdf":
            kind = "pdf"
        elif ext in {"jpg", "jpeg", "png", "webp"}:
            kind = "image"
        else:
            raise HTTPException(400, f"Unsupported file type: {f.filename}")
        docs.append((f.filename, data, kind))

    result = extract_with_ai(docs, request)
    return JSONResponse(result)


@app.post("/api/export/xlsx")
async def export_xlsx(payload: dict):
    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Records"
    headers = ["Record ID", "Document Type", "Source Documents", "Confidence", "Warnings", "Fields", "Line Items"]
    ws.append(headers)

    for r in payload.get("records", []):
        ws.append([
            r.get("record_id"),
            r.get("document_type"),
            ", ".join(r.get("source_documents", [])),
            r.get("confidence"),
            " | ".join(r.get("warnings", [])),
            json.dumps(r.get("fields", {}), ensure_ascii=False),
            json.dumps(r.get("line_items", []), ensure_ascii=False),
        ])

    for col in ws.columns:
        width = min(max(len(str(cell.value or "")) for cell in col) + 2, 70)
        ws.column_dimensions[col[0].column_letter].width = width

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="invoice-extraction.xlsx"'},
    )
