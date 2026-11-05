"""Publish a stored Notion image and caption to Facebook only."""
import os
import re
import requests

NOTION_HEADERS = {
    "Authorization": f"Bearer {os.environ.get('NOTION_API_KEY', '')}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def facebook_error(res, data):
    error = data.get("error", {})
    detail = {key: error.get(key) for key in (
        "code", "error_subcode", "message", "error_user_title", "error_user_msg"
    ) if error.get(key) is not None}
    safe = str(detail)
    for value in (os.environ.get("FB_PAGE_ACCESS_TOKEN"), os.environ.get("RESOLVED_FB_TOKEN")):
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
    os.environ["RESOLVED_FB_TOKEN"] = token
    return token


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



def notion(method, path, **kwargs):
    res = requests.request(method, f"https://api.notion.com/v1/{path}",
                           headers=NOTION_HEADERS, timeout=30, **kwargs)
    if not res.ok:
        raise SystemExit(f"Notion HTTP {res.status_code}: 請確認 Facebook 資料庫已連接原本的 Notion 整合。")
    return res.json()


def patch_page(page_id, properties):
    return notion("PATCH", f"pages/{page_id}", json={"properties": properties})


def main():
    import random
    from datetime import datetime, timezone
    from uuid import UUID
    database_id = str(UUID(os.environ["FB_NOTION_DATABASE_ID"]))
    database = notion("GET", f"databases/{database_id}")
    schema = database["properties"]
    for name, kind in {"文字": "rich_text", "狀態": "status", "文案": "rich_text",
                       "圖片網址": "url", "備註": "rich_text", "發文時間": "date"}.items():
        if schema.get(name, {}).get("type") != kind:
            raise SystemExit(f"Facebook 資料庫缺少欄位或類型不符：{name}")
    print("Facebook Notion 資料庫：", database_id,
          "".join(t.get("plain_text", "") for t in database.get("title", [])))
    posts = notion("POST", f"databases/{database_id}/query", json={
        "filter": {"property": "狀態", "status": {"equals": "待發"}}, "page_size": 100
    })["results"]
    print("Facebook 待發文章：", len(posts))
    if os.environ.get("PUBLISH_MODE", "facebook_check") == "facebook_check":
        facebook_page_token()
        print("資料庫與粉專連線檢查成功；未發布、未修改文章。")
        return
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if page_id:
        page = notion("GET", f"pages/{str(UUID(page_id))}")
        if str(UUID(page.get("parent", {}).get("database_id", ""))) != database_id:
            raise SystemExit("文章不在 Facebook 專用資料庫，停止。")
    elif posts:
        page = random.choice(posts)
    else:
        print("Facebook 沒有待發文章。")
        return
    props = page["properties"]
    if props["狀態"]["status"]["name"] != "待發":
        raise SystemExit("只處理待發文章；補發前請先確認粉專沒有重複內容。")
    page_id = page["id"]
    image_url = props["圖片網址"]["url"]
    caption = "".join(t["plain_text"] for t in props["文案"]["rich_text"])
    text = "".join(t["plain_text"] for t in props["文字"]["rich_text"])
    if (not image_url or not caption) and not text:
        raise SystemExit("缺少文字，無法產生圖片或文案。")
    # Reuse only the image/caption helpers; never invoke Instagram.main or its publisher.
    from Instagram import create_image, upload_to_cloudinary, create_caption
    if not image_url:
        image_url = upload_to_cloudinary(create_image(text, "facebook-output.png"))
    if not caption:
        caption = create_caption(text)
    patch_page(page_id, {
        "圖片網址": {"url": image_url},
        "文案": {"rich_text": [{"text": {"content": caption[:2000]}}]},
        "狀態": {"status": {"name": "進行中"}},
    })
    success = post_to_facebook(image_url, caption)
    properties = {
        "備註": {"rich_text": [{"text": {"content":
            "Facebook 發布成功。" if success else "Facebook 未確認成功；請檢查粉專及執行紀錄，確認沒有貼文後再改回待發。"}}]},
    }
    if success:
        properties["狀態"] = {"status": {"name": "已發"}}
        properties["發文時間"] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}
    patch_page(page_id, properties)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
