import time
import re
import os
import random
import requests
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageDraw, ImageFont
from google import genai

# ===== 環境變數 =====
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.environ.get("IG_ACCOUNT_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ========== 字元檢查 ==========
def has_unsupported_chars(text, font_size=40):
    try:
        font = ImageFont.truetype("漢字之美仿宋.ttf", font_size)
    except Exception as e:
        print(f"字體載入失敗：{e}")
        return list(text)

    unsupported = []
    test_img = Image.new("RGB", (200, 200))
    test_draw = ImageDraw.Draw(test_img)

    for char in text:
        if char in " \n，。？！、「」《》…：":
            continue
        try:
            bbox = test_draw.textbbox((0, 0), char, font=font)
            if bbox[2] - bbox[0] == 0:
                unsupported.append(char)
        except OSError:
            # 辰宇落雁體會觸發 too many function definitions，直接跳過
            break

    return unsupported



# ========== Notion 狀態更新 ==========
def update_notion_status_failed(page_id, error_msg):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "狀態": {"status": {"name": "失敗"}},
            "備註": {
                "rich_text": [{"text": {"content": error_msg}}]
            }
        }
    }
    requests.patch(url, headers=NOTION_HEADERS, json=payload)


def update_status_publishing(page_id):
    """先鎖定這筆，防止排程重複抓到同一筆"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "狀態": {"status": {"name": "進行中"}}
        }
    }
    requests.patch(url, headers=NOTION_HEADERS, json=payload)
    print(f"已將狀態改為發布中，page_id：{page_id}")


def update_status_published(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "狀態": {"status": {"name": "已發"}}
        }
    }
    res = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    print(f"Notion 狀態更新結果：{res.status_code} / {res.json()}")


# ========== 圖片生成 ==========
def create_image(text, output_path="output.png"):
    bg = Image.open("back.png").convert("RGBA")
    width, height = bg.size
    draw = ImageDraw.Draw(bg)

    watermark_font_size = int(width * 0.03)

    lines = text.strip().split("\n")
    lines = [line.strip() for line in lines if line.strip()]

    margin = int(width * 0.10)
    max_text_width = width - (margin * 2)

    letter_spacing = 6

    def get_line_width(line, font, spacing):
        total = 0
        for char in line:
            bbox = draw.textbbox((0, 0), char, font=font)
            total += (bbox[2] - bbox[0]) + spacing
        return total - spacing

    font_size = 62

    main_font = ImageFont.truetype("漢字之美仿宋.ttf", font_size)
    watermark_font = ImageFont.truetype("漢字之美仿宋.ttf", watermark_font_size)

    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=main_font)
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = int(font_size * 0.5)
    total_text_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    start_y = (height - total_text_height) // 2

    current_y = start_y
    for i, line in enumerate(lines):
        line_w = get_line_width(line, main_font, letter_spacing)
        x = (width - line_w) // 2

        cursor_x = x
        for char in line:
            draw.text(
                (cursor_x, current_y),
                char,
                font=main_font,
                fill="white"
            )
            char_bbox = draw.textbbox((0, 0), char, font=main_font)
            cursor_x += (char_bbox[2] - char_bbox[0]) + letter_spacing

        current_y += line_heights[i] + line_spacing

    watermark = "@angus061855"
    wm_bbox = draw.textbbox((0, 0), watermark, font=watermark_font)
    wm_width = wm_bbox[2] - wm_bbox[0]
    wm_x = (width - wm_width) // 2
    wm_y = height - int(height * 0.08)
    draw.text((wm_x, wm_y), watermark, font=watermark_font, fill=(180, 180, 180))

    bg.convert("RGB").save(output_path, "PNG")
    print(f"圖片已生成：{output_path}")
    return output_path


# ========== 文案生成 ==========
def create_caption(topic_text):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""你是一位專業的 Instagram/Threads 文案寫手。

根據以下主題文字，撰寫一篇強而有力的文案：

主題：{topic_text}

規則：
- 第一句必須能獨立成立，吸引滑手機的人停下來
- 不要在開場就給答案，保持神秘感
- 禁止用「——」
- 禁止用「他笑著搖搖頭」「我愣住了」等 AI 感用語
- 要有一句總結性金句
- 結尾拋出一個開放式問題引發討論
- 語言自然，像在跟朋友聊天
- 使用全形標點符號（，。？：）
- 不要加任何引用來源符號
- 不要加 hashtag
- 文案長度控制在 150-300 字
- 每句話單獨一行
- 每行不超過 18 個字
- 段落之間空一行
- 請直接輸出文案，不要加任何前綴說明。
"""

    attempt = 0
    while True:
        attempt += 1
        try:
            print(f"第 {attempt} 次嘗試生成文案...")
            response = client.models.generate_content(
                model="gemma-4-31b-it",
                contents=prompt
            )
            caption = response.text.strip()
            print("文案生成成功")
            return caption
        except Exception as e:
            print(f"失敗：{e}")
            print("10 秒後重試...")
            time.sleep(10)


# ========== Notion 查詢 ==========
def get_pending_posts():
    """抓所有待發，最多 100 筆"""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "狀態",
            "status": {"equals": "待發"}
        },
        "page_size": 100
    }
    res = requests.post(url, headers=NOTION_HEADERS, json=payload)
    data = res.json()
    results = data.get("results", [])
    print(f"找到 {len(results)} 筆待發文章")
    return results


def get_text_from_page(page):
    text_prop = page["properties"].get("文字", {})
    rich_texts = text_prop.get("rich_text", [])
    return "".join([rt["plain_text"] for rt in rich_texts])


def upload_to_cloudinary(image_path):
    result = cloudinary.uploader.upload(image_path)
    return result["secure_url"]


def update_notion_page(page_id, image_url, caption):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "圖片網址": {"url": image_url},
            "文案": {
                "rich_text": [{"text": {"content": caption[:2000]}}]
            }
        }
    }
    requests.patch(url, headers=NOTION_HEADERS, json=payload)


# ========== IG 發布 ==========
def post_to_instagram(image_url, caption):
    create_url = f"https://graph.facebook.com/v19.0/{IG_ACCOUNT_ID}/media"
    create_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN
    }
    res = requests.post(create_url, data=create_payload)
    creation_id = res.json().get("id")

    if not creation_id:
        print(f"IG 建立媒體失敗：{res.json()}")
        return False

    check_url = f"https://graph.facebook.com/v19.0/{creation_id}"
    check_params = {
        "fields": "status_code",
        "access_token": IG_ACCESS_TOKEN
    }

    for attempt in range(10):
        time.sleep(5)
        check_res = requests.get(check_url, params=check_params)
        status = check_res.json().get("status_code")
        print(f"第 {attempt+1} 次確認狀態：{status}")

        if status == "FINISHED":
            break
        elif status == "ERROR":
            print("IG 圖片處理失敗")
            return False
    else:
        print("等待超時，圖片一直沒準備好")
        return False

    publish_url = f"https://graph.facebook.com/v19.0/{IG_ACCOUNT_ID}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": IG_ACCESS_TOKEN
    }
    pub_res = requests.post(publish_url, data=publish_payload)
    print(f"IG 發布結果：{pub_res.json()}")
    return pub_res.json().get("id") is not None



# ========== Facebook 粉專發布 ==========
def facebook_error(res, data):
    error = data.get("error", {})
    detail = {key: error.get(key) for key in (
        "code", "error_subcode", "message", "error_user_title", "error_user_msg"
    ) if error.get(key) is not None}
    safe = str(detail)
    for value in (os.environ.get("FB_PAGE_ACCESS_TOKEN"), IG_ACCESS_TOKEN):
        if value:
            safe = safe.replace(value, "[REDACTED]")
    print("Facebook HTTP:", res.status_code,
          re.sub(r"EAA[A-Za-z0-9]+", "[REDACTED]", safe))


def facebook_page_token():
    token = os.environ["FB_PAGE_ACCESS_TOKEN"]
    def get(path, fields):
        res = requests.get(f"https://graph.facebook.com/v27.0/{path}",
                           headers={"Authorization": f"Bearer {token}"},
                           params={"fields": fields}, timeout=30)
        data = res.json()
        if not res.ok:
            facebook_error(res, data)
            raise SystemExit(1)
        return data
    identity = get("me", "id,name")
    if identity.get("id") != "1393144653886528":
        # An authorized user token must be exchanged for this Page's token.
        page = get("1393144653886528", "id,name,access_token")
        token = page.get("access_token")
        if not token:
            raise SystemExit("No Page token returned. No post was sent.")
        identity = get("me", "id,name")
    if identity.get("id") != "1393144653886528":
        raise SystemExit("Unexpected Page identity. No post was sent.")
    print("Facebook publishing identity:", identity["id"], identity["name"])
    return token


def facebook_existing_post(mode):
    # Only the already-published IG trial; never create another IG post.
    facebook_page_token()
    if mode == "facebook_check":
        return
    page_id = "33a11a31-6c9e-8183-9a35-e3ab7a8968fc"
    res = requests.get(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=NOTION_HEADERS, timeout=30)
    res.raise_for_status()
    props = res.json()["properties"]
    notes = "".join(t["plain_text"] for t in props["備註"]["rich_text"])
    if "Facebook 補發成功" in notes:
        print("This post has already been repaired; no post was sent.")
        return
    if props["狀態"]["status"]["name"] != "已發":
        raise SystemExit("Expected an already-published IG post; stopped.")
    image_url = props["圖片網址"]["url"]
    caption = "".join(t["plain_text"] for t in props["文案"]["rich_text"])
    if not image_url or not caption:
        raise SystemExit("Missing original image or caption; stopped.")
    if not post_to_facebook(image_url, caption):
        raise SystemExit(1)
    res = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                         headers=NOTION_HEADERS, timeout=30,
                         json={"properties": {"備註": {"rich_text": [
                             {"text": {"content": "IG 已發；Facebook 補發成功。"}}
                         ]}}})
    res.raise_for_status()


def post_to_facebook(image_url, caption):
    try:
        token = facebook_page_token()
        res = requests.post(
            "https://graph.facebook.com/v27.0/1393144653886528/photos",
            headers={"Authorization": f"Bearer {token}"},
            data={"url": image_url, "message": caption},
            timeout=60,
        )
        data = res.json()
        if res.ok and data.get("post_id"):
            print(f"Facebook 發布成功：{data['post_id']}")
            return True
        facebook_error(res, data)
    except (requests.RequestException, ValueError):
        print("Facebook 回應異常，請先檢查粉專是否已發文，勿直接重跑。")
    return False


def send_telegram_notification(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, json=payload)


# ========== 主程式 ==========
def main():
    posts = get_pending_posts()
    if not posts:
        print("沒有待發文章")
        return

    # ✅ 隨機挑一筆
    page = random.choice(posts)
    page_id = page["id"]
    text = get_text_from_page(page)

    if not text:
        print("文字欄位為空，跳過")
        return

    print(f"隨機選中：{text[:30]}...")

    # ✅ 立刻鎖定這筆，防止重複發文
    update_status_publishing(page_id)

    # Step 1: 生成圖片
    unsupported = has_unsupported_chars(text)
    if unsupported:
        error_msg = f"字型不支援以下字元：{''.join(set(unsupported))}"
        print(f"❌ {error_msg}")
        update_notion_status_failed(page_id, error_msg)
        send_telegram_notification(f"❌ 發布失敗（字型問題）\n{error_msg}\n\n文字：{text[:50]}...")
        return

    image_path = create_image(text, "output.png")
    image_url = upload_to_cloudinary(image_path)
    print(f"圖片上傳成功：{image_url}")

    # Step 2: 生成文案
    caption = create_caption(text)
    print(f"文案生成完成：{caption[:50]}...")

    # Step 3: 更新 Notion
    update_notion_page(page_id, image_url, caption)

    # Step 4: 發布 IG
    success = post_to_instagram(image_url, caption)

    if success:
        update_status_published(page_id)
        if os.environ.get("FB_PAGE_ACCESS_TOKEN"):
            if not post_to_facebook(image_url, caption):
                # IG 已發布，保留「已發」避免補發時重複發到 IG。
                note = "IG 已發；Facebook 未確認成功，請檢查粉專後手動補發，勿改回待發。"
                requests.patch(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    headers=NOTION_HEADERS,
                    json={"properties": {"備註": {
                        "rich_text": [{"text": {"content": note}}]
                    }}},
                    timeout=30,
                )
                send_telegram_notification(f"⚠️ {note}\n\n{text[:50]}...")
                raise SystemExit(1)
            send_telegram_notification(f"✅ IG 與 Facebook 語錄圖片發布成功！\n\n{text[:50]}...")
        else:
            send_telegram_notification(f"✅ angus IG 語錄圖片 發布成功！\n\n{text[:50]}...")
        print("發布成功！")
    else:
        update_notion_status_failed(page_id, "IG 發布失敗")
        send_telegram_notification(f"❌ angus IG 語錄圖片 發布失敗\n\n{text[:50]}...")
        print("發布失敗")


if __name__ == "__main__":
    mode = os.environ.get("PUBLISH_MODE", "normal") or "normal"
    if mode in ("facebook_check", "facebook_retry"):
        facebook_existing_post(mode)
    elif mode == "normal":
        main()
    else:
        raise SystemExit("Unknown publishing mode")
