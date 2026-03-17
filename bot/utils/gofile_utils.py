import os
from hashlib import sha256
from time import time

import aiohttp

from bot.config import conf
from bot.utils.log_utils import logger

USER_AGENT = "Mozilla/5.0"


def _generate_website_token(user_agent, account_token):
    """
    Generates the dynamic X-Website-Token required by GoFile API.
    Based on https://github.com/ltsdw/gofile-downloader
    """
    time_slot = int(time()) // 14400
    raw = f"{user_agent}::en-US::{account_token}::{time_slot}::gf2026x"
    return sha256(raw.encode()).hexdigest()


def _get_session_headers():
    return {
        "Accept-Encoding": "gzip",
        "User-Agent": USER_AGENT,
        "Connection": "keep-alive",
        "Accept": "*/*",
        "Origin": "https://gofile.io",
        "Referer": "https://gofile.io/",
    }


async def _create_guest_account(session):
    """Create a guest account and update session headers with auth token."""
    wt = _generate_website_token(USER_AGENT, "")
    async with session.post(
        "https://api.gofile.io/accounts",
        headers={"X-Website-Token": wt, "X-BL": "en-US"},
    ) as acc_resp:
        if acc_resp.status == 200:
            acc_data = await acc_resp.json()
            if acc_data.get("status") == "ok":
                token = acc_data["data"]["token"]
                session.headers.update({"Authorization": f"Bearer {token}"})
                session.cookie_jar.update_cookies({"accountToken": token})
                return token
    return None


async def _fetch_content(session, content_id, account_token, password=None):
    """Fetch content metadata from GoFile API."""
    url = (
        f"https://api.gofile.io/contents/{content_id}"
        f"?cache=true&sortField=createTime&sortDirection=1"
    )
    if password:
        url = f"{url}&password={sha256(password.encode()).hexdigest()}"

    wt = _generate_website_token(USER_AGENT, account_token or "")
    headers = {"X-Website-Token": wt, "X-BL": "en-US"}

    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        if data.get("status") != "ok":
            return None
        return data["data"]


async def _collect_files(session, content_id, account_token, parent_dir, password=None):
    """Recursively collect files from GoFile content tree (mirrors upstream behavior)."""
    data = await _fetch_content(session, content_id, account_token, password)
    if not data:
        return []

    if "password" in data and data.get("passwordStatus") != "passwordOk":
        return []

    if data["type"] != "folder":
        return [{"path": parent_dir, "filename": data["name"], "link": data["link"]}]

    files = []
    folder_dir = os.path.join(parent_dir, data["name"])
    os.makedirs(folder_dir, exist_ok=True)

    for child in data.get("children", {}).values():
        if child["type"] == "folder":
            files.extend(
                await _collect_files(
                    session, child["id"], account_token, folder_dir, password
                )
            )
        else:
            files.append(
                {
                    "path": folder_dir,
                    "filename": child["name"],
                    "link": child["link"],
                    "size": child.get("size", 0),
                }
            )
    return files


async def get_gofile_server():
    async with aiohttp.ClientSession(headers=_get_session_headers()) as session:
        try:
            async with session.get("https://api.gofile.io/servers") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data["status"] == "ok":
                        servers = data["data"]["servers"]
                        if servers:
                            return servers[0]["name"]
        except Exception as e:
            await logger(e)
    return "store1"


async def upload_to_gofile(filepath):
    server = await get_gofile_server()
    url = f"https://{server}.gofile.io/contents/uploadfile"

    async with aiohttp.ClientSession(headers=_get_session_headers()) as session:
        data = aiohttp.FormData()
        try:
            with open(filepath, "rb") as f:
                data.add_field("file", f, filename=os.path.basename(filepath))
                async with session.post(url, data=data) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        if res_json["status"] in ["ok", "success"]:
                            return res_json["data"]["downloadPage"]
        except Exception as e:
            await logger(e)
            return None
    return None


async def get_gofile_name(url):
    try:
        content_id = url.split("/")[-1]

        async with aiohttp.ClientSession(headers=_get_session_headers()) as session:
            token = None
            try:
                token = await _create_guest_account(session)
            except Exception:
                pass

            data = await _fetch_content(session, content_id, token)
            if not data:
                return None

            if data["type"] == "folder":
                children = data.get("children", {})
                for child in children.values():
                    if child["type"] == "file":
                        return child["name"]
                return data["name"]
            return data["name"]

    except Exception as e:
        await logger(e)
    return None


async def download_from_gofile(
    url, output_dir, progress_callback=None, progress_args=None
):
    try:
        content_id = url.split("/")[-1]

        async with aiohttp.ClientSession(headers=_get_session_headers()) as session:
            token = None
            try:
                token = await _create_guest_account(session)
            except Exception:
                pass

            files_to_download = await _collect_files(
                session, content_id, token, output_dir
            )

            if not files_to_download:
                return False

            for file_info in files_to_download:
                download_link = file_info["link"]
                filename = os.path.basename(file_info["filename"])
                filepath = os.path.join(file_info["path"], filename)
                file_size = file_info.get("size", 0)

                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    if os.path.getsize(filepath) == file_size:
                        continue

                tmp_file = f"{filepath}.part"
                headers = {}
                part_size = 0
                if os.path.isfile(tmp_file):
                    part_size = os.path.getsize(tmp_file)
                    headers = {"Range": f"bytes={part_size}-"}

                async with session.get(download_link, headers=headers) as r:
                    if r.status not in (200, 206):
                        await logger(
                            f"GoFile download failed for {filename}: HTTP {r.status}"
                        )
                        continue

                    downloaded = part_size
                    with open(tmp_file, "ab") as f:
                        async for chunk in r.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and file_size > 0 and progress_args:
                                try:
                                    await progress_callback(
                                        downloaded, file_size, *progress_args
                                    )
                                except Exception:
                                    pass

                if os.path.isfile(tmp_file):
                    if file_size == 0 or os.path.getsize(tmp_file) == file_size:
                        os.replace(tmp_file, filepath)

            return True

    except Exception as e:
        await logger(e)
        return False
