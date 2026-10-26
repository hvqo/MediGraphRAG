"""Isolated browser integration check using a labelled HTTP model stub, no clinical claims.

Starts temporary application/model servers and deletes their temporary data on exit.
Does not change the user's saved provider, sources, question bank or learner statistics.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import httpx
import uvicorn
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.main import create_app
from backend.app.config import SettingsUpdate


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(directory)
        source = app.state.documents.add(
            "软件测试.txt",
            "软件验收规定：测试标签甲关联测试标签乙。此段只供软件测试，不是医学知识。".encode(),
            "V2界面验收资料",
        )
        evidence = app.state.documents.get(source["id"])["chunks"][0]
        citation = {"evidence_id": evidence["id"], "quote": evidence["text"]}
        question = {
            "topic": "软件验收中哪个标签与测试标签乙关联？",
            "options": dict(zip("ABCD", ["测试标签甲", "测试标签丙", "测试标签丁", "测试标签戊"])),
            "answer": ["A"],
            "analysis": "根据软件测试原文，标签甲关联标签乙。此解析不提供医学知识。",
            "citations": [citation],
            "question_type": "single_choice",
            "difficulty": "medium",
        }
        review = {
            "supported": True,
            "answer_valid": True,
            "ambiguous": False,
            "leaks_answer": False,
            "reason": "HTTP软件验收桩",
            "options": {
                k: {"correct": k == "A", "reason": "依据软件测试声明逐项核对。", "citations": [citation]}
                for k in "ABCD"
            },
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = payload["messages"][-1]["content"]
                result = review if "独立审题环节" in prompt else question
                output = json.dumps(
                    {
                        "message": {"content": json.dumps(result, ensure_ascii=False)},
                        "prompt_eval_count": 123,
                        "eval_count": 45,
                    },
                    ensure_ascii=False,
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)

        model_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
        model_thread.start()
        app.state.settings.update(
            SettingsUpdate(
                ollama_base_url=f"http://127.0.0.1:{model_server.server_port}", ollama_model="HTTP-software-stub"
            )
        )
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("Temporary UI server did not start")
                time.sleep(0.05)
            base = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
            with httpx.Client(base_url=base, trust_env=False) as client, sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=False, args=["--headless=new"])
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + "/#/relations")
                page.get_by_label("来源资料", exact=True).select_option(source["id"])
                page.get_by_label("主体", exact=True).fill("测试标签甲")
                page.get_by_label("关系", exact=True).fill("关联")
                page.get_by_label("客体", exact=True).fill("测试标签乙")
                page.get_by_label("逐字引句", exact=True).fill(evidence["text"])
                page.get_by_label("适用条件与否定信息").fill("仅限软件验收声明")
                page.get_by_role("button", name="保存候选关系", exact=True).click()
                page.get_by_role("button", name="确认关系并通过", exact=True).click()
                expect(page.locator("span.tag").filter(has_text="已通过")).to_be_visible()
                page.get_by_placeholder("输入实体名称").fill("测试标签甲")
                page.get_by_role("button", name="查找路径", exact=True).click()
                expect(page.locator(".reader-layout > section").nth(1).locator("article.chunk")).to_have_count(1)

                page.get_by_role("button", name="蓝图与病例", exact=True).click()
                page.get_by_label("病例材料标题").fill("软件验收共享情境")
                page.get_by_label("统一情境").fill("虚构教学情境：测试标签甲与乙用于软件验收。")
                page.get_by_label("病例依据资料").select_option(source["id"])
                page.get_by_label("支持情境的逐字原句").fill(evidence["text"])
                page.get_by_role("button", name="保存待审病例", exact=True).click()
                page.get_by_role("button", name="确认情境与原文一致", exact=True).click()
                expect(page.get_by_text("软件验收共享情境 · approved")).to_be_visible()
                case_id = client.get("/cases").json()[0]["id"]
                page.get_by_label("蓝图名称").fill("软件验收蓝图")
                page.get_by_label("知识点", exact=True).fill("标签关联")
                page.get_by_label("检索与出题要求").fill("测试标签甲")
                page.get_by_label("共享病例", exact=True).select_option(case_id)
                page.get_by_role("button", name="保存蓝图", exact=True).click()
                page.get_by_role("button", name="按蓝图生成整卷", exact=True).click()
                expect(page.get_by_text("已排队 1 个分布任务", exact=False)).to_be_visible()
                deadline = time.monotonic() + 10
                while not client.get("/questions").json():
                    if time.monotonic() > deadline:
                        raise AssertionError(client.get("/jobs").json())
                    time.sleep(0.05)
                qid = client.get("/questions").json()[0]["id"]
                page.get_by_role("button", name="题库与审核", exact=True).click()
                page.get_by_text("逐项自动审查意见", exact=True).click()
                expect(page.get_by_role("heading", name="B · 判断为干扰项")).to_be_visible()
                page.get_by_role("button", name="审核通过", exact=True).click()
                expect(page.locator("span.tag").filter(has_text="已通过")).to_be_visible()

                page.get_by_role("button", name="练习与复习", exact=True).click()
                page.get_by_label("本机学习档案").fill("隔离界面测试学习者")
                page.get_by_role("button", name="使用此档案", exact=True).click()
                page.get_by_label("练习题目").select_option(qid)
                page.locator('input[name="exercise-answer"]').nth(1).check()
                page.get_by_role("button", name="提交并查看解析", exact=True).click()
                expect(page.get_by_role("heading", name="这道题需要再复习", exact=False)).to_be_visible()
                page.get_by_role("button", name="错题与知识点", exact=True).click()
                expect(page.get_by_role("heading", name="标签关联", exact=True)).to_be_visible()
                expect(page.get_by_text("1 次练习，1 次需要复习")).to_be_visible()
                page.get_by_role("button", name="教师统计", exact=True).click()
                expect(page.get_by_text("样本不足").first).to_be_visible()

                page.get_by_role("button", name="效果评测", exact=True).click()
                page.get_by_label("评测集名称").fill("软件验收固定问题集")
                page.get_by_label("从资料选择预期证据").select_option(source["id"])
                page.get_by_label("固定问题").fill("测试标签甲")
                page.get_by_label("预期依据（可多选）").select_option([evidence["id"]])
                page.get_by_role("button", name="保存评测集", exact=True).click()
                page.get_by_role("button", name="确认问题和预期证据", exact=True).click()
                page.get_by_label("vector", exact=True).check()
                page.get_by_role("button", name="运行检索对照", exact=True).click()
                expect(page.get_by_role("cell", name="keyword / keyword", exact=True)).to_be_visible()
                expect(page.get_by_role("cell", name="vector / unavailable", exact=True)).to_be_visible()
                page.get_by_text("测试标签甲 · keyword · 核对检索与人工评价", exact=True).click()
                page.get_by_role("button", name="填写人工评价", exact=True).click()
                page.get_by_label("证据是否支持问题").select_option(label="支持")
                page.get_by_role("button", name="保存人工评价", exact=True).click()

                page.get_by_role("button", name="运行与回放", exact=True).click()
                page.get_by_role("button", name="检查调用", exact=True).first.click()
                expect(page.get_by_role("heading", name="HTTP-software-stub · option-review-v2")).to_be_visible()
                page.get_by_role("button", name="用原配置再次调用", exact=True).click()
                expect(page.get_by_text("回放不会写入正式题库", exact=False)).to_be_visible()
                expect(page.locator("pre").last).to_contain_text("supported")
                assert len(client.get("/questions").json()) == 1

                folder = Path(".runtime/ui-check")
                folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / "v2-traces.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                for name in [
                    "医学资料库",
                    "资料阅读器",
                    "依据问答",
                    "知识图谱",
                    "关系与出处",
                    "智能出题",
                    "蓝图与病例",
                    "题库与审核",
                    "练习与复习",
                    "效果评测",
                    "运行与回放",
                    "模型与设置",
                ]:
                    page.get_by_role("button", name=name, exact=True).click()
                    page.wait_for_timeout(150)
                    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                    if overflow:
                        print(
                            page.evaluate(
                                '[...document.querySelectorAll("main *")].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>[e.tagName,e.className,e.getBoundingClientRect().width])'
                            )
                        )
                    assert not overflow, name + " mobile overflow"
                assert not errors, errors
                browser.close()
                report = {
                    "passed": True,
                    "pages": 12,
                    "model": "labelled local HTTP stub",
                    "browser_errors": errors,
                    "flows": [
                        "relation approval/path",
                        "case approval",
                        "blueprint generation/coverage",
                        "per-option review",
                        "practice/wrong point",
                        "evaluation modes/manual rating",
                        "trace/replay",
                    ],
                    "production_data_modified": False,
                }
                (folder / "v2-result.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    "V2 isolated UI check passed: 12 pages, seven complete flows, mobile layout, no browser errors; HTTP stub only."
                )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            model_server.shutdown()
            model_server.server_close()


if __name__ == "__main__":
    main()
