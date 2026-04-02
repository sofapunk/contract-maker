"""Contract Maker – FastAPI app that copies a Google Doc template and fills placeholders."""

import logging
import os
import re
import traceback
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TEMPLATE_DOC_ID = "1X4RLC9_HYT7_cWR6GXMrkt60VLJIHVwYIbaHKZZjIAg"

SERVICE_ACCOUNT_PATH = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_PATH",
    "../../.secrets/creative-strategy-clode-f15c21f08fd2.json",
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

# ---------------------------------------------------------------------------
# Google API clients
# ---------------------------------------------------------------------------

def _get_credentials():
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=SCOPES
    )

def _drive_service():
    return build("drive", "v3", credentials=_get_credentials())

def _docs_service():
    return build("docs", "v1", credentials=_get_credentials())

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(title="Contract Maker")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        return templates.TemplateResponse(request=request, name="index.html")
    except Exception as e:
        logger.error("Template error: %s\n%s", e, traceback.format_exc())
        return HTMLResponse(f"<pre>Error: {e}\n{traceback.format_exc()}</pre>", status_code=500)


@app.post("/create")
async def create_contract(
    creator_name: str = Form(...),
    creator_address: str = Form(...),
    creator_city: str = Form(...),
    deadline: str = Form(...),
    briefings: str = Form(...),
    payment: str = Form(...),
    buyout_type: str = Form(...),         # "unlimited" | "limited"
    buyout_duration: str = Form(""),       # e.g. "3 Monate", "26 Wochen"
):
    """Copy template, fill placeholders, return link."""
    steps = []

    try:
        drive = _drive_service()
        docs = _docs_service()

        # --- 1. Find parent folder of template ---
        steps.append("🔍 Finding template folder …")
        template_meta = drive.files().get(
            fileId=TEMPLATE_DOC_ID, fields="parents",
            supportsAllDrives=True,
        ).execute()
        parent_folder = template_meta.get("parents", [None])[0]
        steps.append(f"✅ Template folder: {parent_folder}")

        # --- 2. Copy template ---
        briefing_short = briefings.replace("\n", ", ").strip()
        new_title = f"Content-Creator Contract {creator_name} {briefing_short}"
        steps.append(f"📋 Copying template as '{new_title}' …")

        copy_body = {"name": new_title}
        if parent_folder:
            copy_body["parents"] = [parent_folder]

        copied = drive.files().copy(
            fileId=TEMPLATE_DOC_ID, body=copy_body,
            supportsAllDrives=True,
        ).execute()
        new_doc_id = copied["id"]
        steps.append(f"✅ Copy created: {new_doc_id}")

        # --- 3. Build replacement requests ---
        today = date.today().strftime("%d.%m.%Y")

        # Fix 1: [Content-Creator Adresse] = full name + address
        full_address = f"{creator_name}\n{creator_address}"

        replacements = {
            "[Content-Creator Name]": creator_name,
            "[Content-Creator Adresse]": full_address,
            "[Content-Creator Stadt]": creator_city,
            "[Deadline]": deadline,
            "[briefing name]": briefings,
            "[payment]": payment,
            "[datum]": today,
        }

        requests = []
        for placeholder, value in replacements.items():
            requests.append({
                "replaceAllText": {
                    "containsText": {
                        "text": placeholder,
                        "matchCase": True,
                    },
                    "replaceText": value,
                }
            })
        steps.append("✏️ Replacing placeholders …")

        # --- 4. Handle buyout variants ---
        # Template uses markers: [unbefristet]...[unbefristet] and [befristet]...[befristet]
        # Read the copied doc to get the exact text between markers, then delete
        # the unwanted variant (incl. markers) and strip markers from the kept one.

        doc_content = docs.documents().get(documentId=new_doc_id).execute()
        full_text = ""
        for elem in doc_content.get("body", {}).get("content", []):
            for pe in elem.get("paragraph", {}).get("elements", []):
                full_text += pe.get("textRun", {}).get("content", "")
            for row in elem.get("table", {}).get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for ce in cell.get("content", []):
                        for pe in ce.get("paragraph", {}).get("elements", []):
                            full_text += pe.get("textRun", {}).get("content", "")

        if buyout_type == "unlimited":
            # Delete everything from [befristet] to [befristet] (inclusive)
            match = re.search(r'\[befristet\].*?\[befristet\]', full_text, re.DOTALL)
            if match:
                requests.append({
                    "replaceAllText": {
                        "containsText": {"text": match.group(), "matchCase": True},
                        "replaceText": "",
                    }
                })
            # Remove the [unbefristet] markers, keep the text between them
            requests.append({
                "replaceAllText": {
                    "containsText": {"text": "[unbefristet]", "matchCase": True},
                    "replaceText": "",
                }
            })
            steps.append("📝 Buyout: unbefristet")
        else:
            # Delete everything from [unbefristet] to [unbefristet] (inclusive)
            match = re.search(r'\[unbefristet\].*?\[unbefristet\]', full_text, re.DOTALL)
            if match:
                requests.append({
                    "replaceAllText": {
                        "containsText": {"text": match.group(), "matchCase": True},
                        "replaceText": "",
                    }
                })
            # Remove the [befristet] markers, keep the text between them
            requests.append({
                "replaceAllText": {
                    "containsText": {"text": "[befristet]", "matchCase": True},
                    "replaceText": "",
                }
            })
            # Replace [zeitraum nutzung] with the selected duration
            requests.append({
                "replaceAllText": {
                    "containsText": {"text": "[zeitraum nutzung]", "matchCase": True},
                    "replaceText": buyout_duration,
                }
            })
            steps.append(f"📝 Buyout: befristet, {buyout_duration}")

        # --- 5. Execute all replacements ---
        docs.documents().batchUpdate(
            documentId=new_doc_id,
            body={"requests": requests},
        ).execute()
        steps.append("✅ All placeholders replaced")

        # --- 6. Export as PDF and save to same folder ---
        steps.append("📄 Exporting PDF …")
        pdf_content = drive.files().export(
            fileId=new_doc_id, mimeType="application/pdf"
        ).execute()

        pdf_metadata = {
            "name": f"{new_title}.pdf",
            "mimeType": "application/pdf",
        }
        if parent_folder:
            pdf_metadata["parents"] = [parent_folder]

        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(pdf_content, mimetype="application/pdf")
        pdf_file = drive.files().create(
            body=pdf_metadata, media_body=media,
            supportsAllDrives=True,
        ).execute()
        pdf_url = f"https://drive.google.com/file/d/{pdf_file['id']}/view"
        steps.append(f"✅ PDF saved: {new_title}.pdf")

        # --- 7. Build links ---
        doc_url = f"https://docs.google.com/document/d/{new_doc_id}/edit"
        steps.append("🔗 Done! Document and PDF ready.")

        return JSONResponse({
            "success": True,
            "url": doc_url,
            "pdf_url": pdf_url,
            "title": new_title,
            "steps": steps,
        })

    except Exception as e:
        steps.append(f"❌ Error: {e}")
        return JSONResponse(
            {"success": False, "error": str(e), "steps": steps},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
