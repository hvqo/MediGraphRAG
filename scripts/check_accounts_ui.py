"""Real browser account journeys against disposable data; no inference or public server."""

import argparse
from pathlib import Path
import sys
import tempfile
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.accounts import AccountPolicy
from backend.app.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-docs", action="store_true")
    capture = parser.parse_args().capture_docs
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(directory, personal=True, account_policy=AccountPolicy(required=True, secure_cookie=False))
        app.state.accounts.create("website_admin", "ui-admin-password-12345", "admin")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("Temporary account server did not start")
                time.sleep(0.05)
            base = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=False, args=["--headless=new"])
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                expect(page.get_by_role("heading", name="欢迎回来")).to_be_visible()
                if capture:
                    target = Path(__file__).resolve().parents[1] / "docs/images/account-login.png"
                    page.screenshot(path=str(target))
                page.get_by_role("button", name="还没有账号？创建一个").click()
                page.get_by_label("账号", exact=True).fill("ui_learner")
                page.get_by_label("密码", exact=True).fill("ui-password-12345")
                page.get_by_role("button", name="注册并进入", exact=True).click()
                expect(page.locator(".topbar")).to_contain_text("ui_learner")
                page.goto(base + "/#/account")
                expect(page.get_by_role("heading", name="账号与登录", exact=True)).to_be_visible()
                expect(page.get_by_role("heading", name="网站账号管理")).not_to_be_visible()
                page.goto(base + "/#/settings")
                expect(page.get_by_label("医学问题")).to_be_visible()
                session = context.request.get(base + "/api/auth/status").json()
                response = context.request.post(
                    base + "/api/documents/text",
                    data={"title": "账号隔离验收", "text": "这是一份仅用于软件测试的账号私有资料。"},
                    headers={"X-CSRF-Token": session["csrf_token"]},
                )
                assert response.status == 201, response.text()
                identifier = response.json()["id"]
                page.get_by_role("button", name="退出", exact=True).click()
                expect(page.get_by_role("heading", name="欢迎回来")).to_be_visible()
                assert context.request.get(base + "/api/documents").status == 401
                page.reload()
                page.get_by_label("账号", exact=True).fill("ui_learner")
                page.get_by_label("密码", exact=True).fill("ui-password-12345")
                page.get_by_role("button", name="登录", exact=True).click()
                expect(page.locator(".topbar")).to_contain_text("ui_learner")
                assert context.request.get(base + "/api/documents").json()[0]["id"] == identifier
                other = browser.new_context(viewport={"width": 390, "height": 844})
                admin = other.new_page()
                admin.on("pageerror", lambda error: errors.append(str(error)))
                admin.goto(base)
                expect(admin.get_by_role("heading", name="欢迎回来")).to_be_visible()
                assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile login overflows"
                admin.get_by_label("账号", exact=True).fill("website_admin")
                admin.get_by_label("密码", exact=True).fill("ui-admin-password-12345")
                admin.get_by_role("button", name="登录", exact=True).click()
                expect(admin.locator(".topbar")).to_contain_text("website_admin")
                assert other.request.get(base + "/api/documents").json() == []
                admin.goto(base + "/#/account")
                expect(admin.get_by_role("heading", name="网站账号管理")).to_be_visible()
                expect(admin.get_by_role("cell", name="ui_learner", exact=True)).to_be_visible()
                if capture:
                    admin.set_viewport_size({"width": 1440, "height": 1000})
                    admin.screenshot(path=str(target.with_name("account-management.png")), full_page=True)
                admin.goto(base + "/#/settings")
                expect(admin.get_by_role("button", name="保存设置", exact=True)).to_be_visible()
                assert not errors, errors
                browser.close()
                print(
                    "PASS: registration, login, logout, refresh persistence, isolated second account, admin access, mobile login; no JavaScript errors"
                )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError("Temporary account server did not stop")


if __name__ == "__main__":
    main()
