"""One real text/image call to a local compatible server; not a model quality benchmark."""

import argparse
import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import SettingsStore, SettingsUpdate
from backend.app.llm import ModelClient
from backend.app.multimodal import image_bytes


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--model", default="qwen3-vl:8b-instruct")
    args = parser.parse_args()
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40)
    draw.multiline_text(
        (35, 40), "Software verification card\nDocument ID: MG-0801\nPage: 3", fill="black", font=font, spacing=18
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with tempfile.TemporaryDirectory() as folder:
        store = SettingsStore(folder)
        store.update(
            SettingsUpdate(
                provider="openai",
                cloud_base_url=args.base_url,
                cloud_model=args.model,
                vision_provider="openai",
                vision_base_url=args.base_url,
                vision_model=args.model,
                request_timeout=600,
                vision_timeout=600,
                vision_max_tokens=512,
            )
        )
        model = ModelClient(store)
        connection = await model.check()
        print("Connection:", connection["ok"], flush=True)
        if not connection["ok"]:
            raise RuntimeError(connection["message"])
        text = await model.json('只输出JSON对象 {"ready":true}。', "这是软件接口验收，请返回ready=true。")
        print("Text request returned JSON", flush=True)
        vision = await model.vision_json(
            "仅逐字读取图片，不进行推测，只输出JSON。",
            '读取图中全部文字，输出 {"text":"原图文字"}。',
            [image_bytes(buffer.getvalue())],
        )
        record = {
            "scope": "One non-clinical software card; functionality only, no medical/accuracy/performance claim",
            "backend": args.base_url,
            "model": args.model,
            "text": text,
            "vision": vision,
        }
        output = ROOT / ".runtime/upgrade-real-runtime.json"
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if not text.get("ready") or "0801" not in str(vision) or "3" not in str(vision):
            raise RuntimeError("The real runtime did not complete the simple software smoke check; see local report")
        print("Real text and vision calls passed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
