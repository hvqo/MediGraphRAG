"""Exercise the local UI with a temporary, clearly labelled software-test document.

Requires Playwright and an installed Chrome browser; never calls paid model APIs.
Start the backend first, then run this script from the repository root.
"""

import json
from pathlib import Path
import uuid
import sys
import httpx
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import SettingsStore
from backend.app.storage import Database
from backend.app.questions import QuestionStore, Question

base = "http://127.0.0.1:8000"
folder = Path(".runtime/ui-check")
folder.mkdir(parents=True, exist_ok=True)
document_id = None
question_id = None
question_store = QuestionStore(Database(SettingsStore().directory))
with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
    document = client.post(
        "/documents/text",
        json={
            "title": "界面验收测试资料（非医学知识）",
            "text": f"本段仅用于软件验收，不提供医学知识。糖尿病、血糖、高血压是用于测试检索与图谱的词。验收编号：{uuid.uuid4().hex}。",
        },
    )
    document.raise_for_status()
    document_id = document.json()["id"]
    try:
        detail = client.get("/documents/" + document_id).json()
        chunk = detail["chunks"][0]
        marker = uuid.uuid4().hex[:8]
        question_id = question_store.save(
            Question(
                topic=f"浏览器验收测试 {marker}：哪个选项是测试标签？",
                options={"A": "软件测试标签", "B": "测试选项乙", "C": "测试选项丙", "D": "测试选项丁"},
                answer=["A"],
                analysis="这是用于页面操作验收的软件测试解析，不提供医学知识。",
                citations=[{"evidence_id": chunk["id"], "quote": chunk["text"]}],
            )
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=False, args=["--headless=new"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            expect(page.get_by_role("heading", name="从原文出发，理解医学知识")).to_be_visible()
            page.get_by_label("医学问题").fill("糖尿病")
            page.get_by_role("button", name="只查原文").click()
            expect(page.get_by_text("界面验收测试资料（非医学知识）", exact=True)).to_be_visible()
            page.screenshot(path=str(folder / "ask-desktop.png"), full_page=True)
            page.get_by_role("button", name="医学资料库", exact=True).click()
            page.get_by_role("button", name="查看原文", exact=True).first.click()
            expect(page.get_by_role("heading", name="界面验收测试资料（非医学知识） · 原文片段")).to_be_visible()
            page.screenshot(path=str(folder / "documents-desktop.png"), full_page=True)
            for navigation, heading in [
                ("智能出题", "围绕考点，生成有据可审的题目"),
                ("题库与审核", "把好题，留在题库里"),
                ("知识图谱", "沿着关联，回到知识来源"),
                ("模型与设置", "选择适合你的模型"),
            ]:
                page.get_by_role("button", name=navigation, exact=True).click()
                expect(page.get_by_role("heading", name=heading)).to_be_visible()
                if navigation == "题库与审核":
                    card = page.locator(".question-card").filter(has_text=marker)
                    card.get_by_role("button", name="审核通过", exact=True).click()
                    expect(card.get_by_text("已通过", exact=True)).to_be_visible()
                    card.get_by_role("button", name="编辑", exact=True).click()
                    page.get_by_label("题干", exact=True).fill(f"浏览器验收测试 {marker}：编辑后哪个选项是测试标签？")
                    page.get_by_role("button", name="保存并重新待审", exact=True).click()
                    expect(card.get_by_text("待审核", exact=True)).to_be_visible()
                    card.get_by_role("button", name="查看操作记录").click()
                    expect(card.locator(".event-list")).to_contain_text("编辑重审")
                    page.screenshot(path=str(folder / "bank-desktop.png"), full_page=True)
                if navigation == "知识图谱":
                    expect(page.locator("canvas")).to_be_visible()
                    page.screenshot(path=str(folder / "graph-desktop.png"), full_page=True)
            page.get_by_role("radio", name="云端模型").check()
            expect(page.get_by_label("API 密钥", exact=True)).to_be_visible()
            page.get_by_role("radio", name="本地 Ollama").check()
            page.screenshot(path=str(folder / "settings-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="依据问答", exact=True).click()
            expect(page.get_by_role("button", name="只查原文")).to_be_visible()
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            assert not overflow, "Mobile page overflows the viewport"
            page.screenshot(path=str(folder / "ask-mobile.png"), full_page=True)
            assert not errors, errors
            browser.close()
        (folder / "result.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "pages": 6,
                    "browser_errors": errors,
                    "mobile_overflow": overflow,
                    "review_edit_history": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            "UI check passed: six pages, source lookup, graph, provider fields, question review/edit/history, mobile viewport; no browser errors."
        )
    finally:
        if question_id:
            with question_store.db.connect() as connection:
                connection.execute("DELETE FROM question_events WHERE question_id=?", (question_id,))
                connection.execute("DELETE FROM question_meta WHERE question_id=?", (question_id,))
                connection.execute("DELETE FROM questions WHERE id=?", (question_id,))
        if document_id:
            client.delete("/documents/" + document_id).raise_for_status()
