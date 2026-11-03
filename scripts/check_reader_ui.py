"""Real-browser PDF reader check; ephemeral non-clinical source, no model calls."""

import io
from pathlib import Path
import uuid
import httpx
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
from playwright.sync_api import sync_playwright, expect


def main():
    marker = "Reader software fixture " + uuid.uuid4().hex[:8]
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(300, 300)
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 10 Tf 10 200 Td ({marker}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(stream)
    base = "http://127.0.0.1:8000"
    with httpx.Client(base_url=base, trust_env=False) as client:
        response = client.post("/documents/upload", files={"file": ("reader-test.pdf", stream.getvalue())})
        response.raise_for_status()
        identifier = response.json()["id"]
        try:
            doc = client.get("/documents/" + identifier).json()
            chunk = doc["chunks"][0]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=False, args=["--headless=new"])
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.context.add_cookies(
                    [
                        {
                            "name": cookie.name,
                            "value": cookie.value,
                            "url": base,
                            "httpOnly": True,
                            "sameSite": "Strict",
                        }
                        for cookie in client.cookies.jar
                    ]
                )
                errors = []
                page.on("console", lambda m: print("PDF console:", m.text) if m.type in ("warning", "error") else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                from urllib.parse import urlencode

                page.goto(
                    base
                    + "/#/reader/"
                    + identifier
                    + "?"
                    + urlencode({"chunk": chunk["id"], "page": 2, "quote": marker})
                )
                try:
                    expect(page.get_by_text("已高亮匹配原文", exact=False)).to_be_visible(timeout=5000)
                except AssertionError:
                    print(
                        page.locator(".pdf-reader").inner_text(),
                        errors,
                        page.locator(".pdf-reader").get_attribute("data-stage"),
                        page.locator(".textLayer").inner_text(),
                        page.locator(".pdf-page canvas").get_attribute("width"),
                    )
                    raise
                expect(page.locator(".pdf-highlight")).to_have_count(1)
                expect(page.locator(".pdf-page canvas")).to_be_visible()
                box = page.locator(".pdf-highlight").bounding_box()
                assert box and box["width"] > 10 and box["height"] > 5, box
                page.get_by_text("资料出处与版本", exact=True).click()
                page.get_by_label("发布来源", exact=True).fill("软件界面验证")
                page.get_by_role("button", name="保存出处").click()
                expect(page.get_by_text("出处信息已保存。")).to_be_visible()
                folder = Path(".runtime/ui-check")
                folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / "reader-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (
                    "Reader mobile overflow"
                )
                assert not errors, errors
                browser.close()
            print("PDF reader passed: page 2, selectable text, visible quote highlight, metadata save, mobile layout.")
        finally:
            client.delete("/documents/" + identifier).raise_for_status()


if __name__ == "__main__":
    main()
