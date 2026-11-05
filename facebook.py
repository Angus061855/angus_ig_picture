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



def main():
    if os.environ.get("PUBLISH_MODE") == "facebook_check":
        facebook_page_token()
        return
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if not page_id:
        raise SystemExit("No Notion page selected; nothing was published.")
    res = requests.get(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=NOTION_HEADERS, timeout=30)
    res.raise_for_status()
    props = res.json()["properties"]
    note = "".join(t["plain_text"] for t in props.get("備註", {}).get("rich_text", []))
    if "Facebook 發布成功" in note or "Facebook 補發成功" in note:
        print("Facebook already published this record; skipped.")
        return
    if props["狀態"]["status"]["name"] != "已發":
        raise SystemExit("IG has not marked this record published; stopped.")
    image_url = props["圖片網址"]["url"]
    caption = "".join(t["plain_text"] for t in props["文案"]["rich_text"])
    if not image_url or not caption:
        raise SystemExit("Missing image or caption; stopped.")
    success = post_to_facebook(image_url, caption)
    note = ("IG 已發；Facebook 發布成功。" if success else
            "IG 已發；Facebook 未確認成功，請檢查粉專後單獨補發 Facebook，勿重跑 IG。")
    res = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                         headers=NOTION_HEADERS, timeout=30,
                         json={"properties": {"備註": {"rich_text": [
                             {"text": {"content": note}}
                         ]}}})
    res.raise_for_status()
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
