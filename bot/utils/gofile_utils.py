import aiohttp
import os
import asyncio
from bot.utils.log_utils import logger
from bot.config import conf

# Token for public access (found in common public scripts, susceptible to change)
# Ideally this should be in config but for now we define it here as a constant or fallback
GOFILE_WT = "4fd6sg89d7s6"

async def get_gofile_server():
    async with aiohttp.ClientSession() as session:
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

    async with aiohttp.ClientSession() as session:
        data = aiohttp.FormData()
        # Open file in binary mode
        try:
            with open(filepath, 'rb') as f:
                data.add_field('file', f, filename=os.path.basename(filepath))
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
        api_url = f"https://api.gofile.io/contents/{content_id}?wt={GOFILE_WT}&cache=true"

        async with aiohttp.ClientSession() as session:
            # Create guest account
            try:
                async with session.post("https://api.gofile.io/accounts") as acc_resp:
                    if acc_resp.status == 200:
                         acc_data = await acc_resp.json()
                         if acc_data["status"] == "ok":
                            token = acc_data["data"]["token"]
                            session.headers.update({"Authorization": f"Bearer {token}"})
            except Exception:
                pass

            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data["status"] == "ok":
                        item = data["data"]
                        if item["type"] == "folder":
                            children = item.get("children", {})
                            for child in children.values():
                                if child["type"] == "file":
                                    return child["name"]
                            return item["name"]
                        return item["name"]
            return None

    except Exception as e:
        await logger(e)
    return None

async def download_from_gofile(url, output_dir, progress_callback=None, progress_args=None):
    try:
        content_id = url.split("/")[-1]
        api_url = f"https://api.gofile.io/contents/{content_id}?wt={GOFILE_WT}&cache=true"

        async with aiohttp.ClientSession() as session:
            # Create guest account
            try:
                async with session.post("https://api.gofile.io/accounts") as acc_resp:
                    if acc_resp.status == 200:
                        acc_data = await acc_resp.json()
                        if acc_data["status"] == "ok":
                            token = acc_data["data"]["token"]
                            session.headers.update({"Authorization": f"Bearer {token}"})
            except Exception:
                pass

            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if data["status"] != "ok":
                    return False

                item = data["data"]
                files_to_download = []

                if item["type"] == "folder":
                    children = item.get("children", {})
                    for child in children.values():
                        if child["type"] == "file":
                            files_to_download.append(child)
                else:
                    files_to_download.append(item)

                if not files_to_download:
                    return False

                # Download files
                for file_info in files_to_download:
                    download_link = file_info["link"]
                    # Sanitize filename
                    filename = os.path.basename(file_info["name"])
                    filepath = os.path.join(output_dir, filename)

                    # Check if exists and size matches?
                    # Gofile metadata has 'size'
                    file_size = file_info.get("size", 0)

                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        # Maybe check size?
                        if os.path.getsize(filepath) == file_size:
                            continue

                    # Download
                    async with session.get(download_link) as r:
                        if r.status != 200:
                            continue

                        downloaded = 0
                        with open(filepath, 'wb') as f:
                            async for chunk in r.content.iter_chunked(8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress_callback and file_size > 0:
                                    # Call progress callback if provided
                                    # Expecting same signature as pyrogram progress: current, total, ...
                                    # But we need to handle the args.
                                    # The downloader calls it like: progress_for_pyrogram(current, total, *progress_args)
                                    if progress_args:
                                         # The args in download.py are: (pyro, media_mssg, e, ttt)
                                         # But we are inside utils, we don't know the exact args.
                                         # We just pass what we got.
                                         # Wait, asyncio.create_task or await?
                                         try:
                                             await progress_callback(downloaded, file_size, *progress_args)
                                         except Exception:
                                             pass
            return True

    except Exception as e:
        await logger(e)
        return False
