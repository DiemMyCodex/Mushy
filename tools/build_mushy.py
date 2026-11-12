#!/usr/bin/env python3
import os
import sys
import ssl
import time
import json
import zipfile
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_token():
    token = os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    token_file = "/data/user/0/com.antigravity.app/files/home/.github_token"
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return f.read().strip()
    return ""

GH_TOKEN = get_token()
REPO = "DiemMyCodex/Mushy"
PROJECT_DIR = "/storage/emulated/0/Documents/AntiGravity/projects/Mushy"
DOWNLOAD_TARGET = "/storage/emulated/0/Download/Mushy.apk"
DOCS_TARGET = "/storage/emulated/0/Documents/AntiGravity/Mushy.apk"
CA_FILE = "/data/user/0/com.antigravity.app/files/usr/etc/tls/cert.pem"

ctx = ssl.create_default_context(cafile=CA_FILE)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def run_git(cmd):
    env = os.environ.copy()
    env["GIT_EXEC_PATH"] = "/data/user/0/com.antigravity.app/files/usr/libexec/git-core"
    env["SSL_CERT_FILE"] = CA_FILE
    env["CURL_CA_BUNDLE"] = CA_FILE
    env["GIT_SSL_CAINFO"] = CA_FILE
    sh_bin = "/data/user/0/com.antigravity.app/files/usr/bin/sh"
    res = subprocess.run(cmd, shell=True, executable=sh_bin, cwd=PROJECT_DIR, env=env, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def gh_api(endpoint):
    url = f"https://api.github.com/{endpoint}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    })
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return None

def main():
    print("=" * 50)
    print("  MUSHY FAST CLOUD BUILD (3-4 MIN)")
    print("=" * 50)

    # 1. Check git status
    code, out, err = run_git("git status --porcelain")
    if out:
        print("[1/4] Phat hien thay doi chua commit, dang tu dong commit & push...")
        run_git("git add .")
        commit_msg = sys.argv[1] if len(sys.argv) > 1 else "feat: update Mushy build"
        run_git(f'git commit -m "{commit_msg}"')
    else:
        print("[1/4] Codebase da sach, kiem tra commit moi nhat...")

    code, out, err = run_git("git push origin master")
    print(f"       Push git: {out if out else 'OK'}")

    # 2. Get the triggered run
    print("[2/4] Dang ket noi toi GitHub Actions runner...")
    time.sleep(4)
    
    run_id = None
    for _ in range(15):
        data = gh_api(f"repos/{REPO}/actions/runs?per_page=3")
        if data and "workflow_runs" in data and len(data["workflow_runs"]) > 0:
            latest = data["workflow_runs"][0]
            if latest["status"] in ["queued", "in_progress"]:
                run_id = latest["id"]
                print(f"       Run ID: {run_id} ({latest['name']}) dang chay...")
                break
            elif latest["status"] == "completed" and (time.time() - time.mktime(time.strptime(latest["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))) < 120:
                run_id = latest["id"]
                break
        time.sleep(3)

    if not run_id:
        print("Khong tim thay Run moi, lay Run gan nhat de theo doi...")
        data = gh_api(f"repos/{REPO}/actions/runs?per_page=1")
        run_id = data["workflow_runs"][0]["id"]

    # 3. Poll run until completed
    start_t = time.time()
    last_status = ""
    while True:
        run_info = gh_api(f"repos/{REPO}/actions/runs/{run_id}")
        if not run_info:
            time.sleep(5)
            continue
        status = run_info["status"]
        conclusion = run_info.get("conclusion")
        elapsed = int(time.time() - start_t)

        if status != last_status:
            print(f"       Trang thai: {status} (da chay {elapsed}s)...")
            last_status = status

        if status == "completed":
            if conclusion == "success":
                print(f"[3/4] Build thanh cong trong {elapsed}s! Dang lay artifact...")
                break
            else:
                print(f"Build that bai: conclusion = {conclusion}")
                sys.exit(1)
        time.sleep(10)

    # 4. Download artifact
    print("[4/4] Dang tai APK toi uu ve dien thoai...")
    artifacts = gh_api(f"repos/{REPO}/actions/runs/{run_id}/artifacts")
    if not artifacts or not artifacts.get("artifacts"):
        print("Loi: Khong tim thay artifact nao!")
        sys.exit(1)

    artifact_id = artifacts["artifacts"][0]["id"]
    artifact_size = artifacts["artifacts"][0]["size_in_bytes"]
    print(f"       Dung luong goi APK: {artifact_size / (1024*1024):.2f} MB")

    # Get Blob redirect URL
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), NoRedirect)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}
    )
    blob_url = None
    try:
        opener.open(req)
    except urllib.error.HTTPError as e:
        blob_url = e.headers.get("Location")

    if not blob_url:
        print("Loi: Khong lay duoc link Azure blob!")
        sys.exit(1)

    tmp_zip = "/tmp/Mushy-APK.zip" if os.path.exists("/tmp") else os.path.join(PROJECT_DIR, "Mushy-APK.zip")
    with open(tmp_zip, "wb") as f:
        f.truncate(artifact_size)

    CHUNK_SIZE = 3 * 1024 * 1024
    chunks = [(s, min(s + CHUNK_SIZE - 1, artifact_size - 1)) for s in range(0, artifact_size, CHUNK_SIZE)]

    import threading
    write_lock = threading.Lock()

    def fetch_chunk(c):
        s, e = c
        req = urllib.request.Request(blob_url, headers={"Range": f"bytes={s}-{e}"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
                    d = r.read()
                    if len(d) == (e - s + 1):
                        with write_lock:
                            with open(tmp_zip, "r+b") as f:
                                f.seek(s)
                                f.write(d)
                        return True
            except:
                time.sleep(0.5)
        return False

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(fetch_chunk, c) for c in chunks]
        for fut in as_completed(futures):
            if not fut.result():
                print("Loi khi tai chunk!")
                sys.exit(1)

    # Unpack APK
    with zipfile.ZipFile(tmp_zip, "r") as zf:
        apk_files = [n for n in zf.namelist() if n.endswith(".apk")]
        if not apk_files:
            print("Khong co file APK nao trong artifact!")
            sys.exit(1)
        
        zf.extract(apk_files[0], "/storage/emulated/0/Documents/AntiGravity")
        extracted_path = os.path.join("/storage/emulated/0/Documents/AntiGravity", apk_files[0])
        
        # Copy to targets
        import shutil
        shutil.copy2(extracted_path, DOWNLOAD_TARGET)
        shutil.copy2(extracted_path, DOCS_TARGET)

    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)

    final_size = os.path.getsize(DOWNLOAD_TARGET) / (1024*1024)
    print("=" * 50)
    print(f" HOAN TAT XUAT SAC! APK SAN SANG ({final_size:.2f} MB)")
    print(f"  1. {DOWNLOAD_TARGET}")
    print(f"  2. {DOCS_TARGET}")
    print("=" * 50)
    print("Mày mo thu muc Tai ve (Download) de cai dat Mushy.apk ngay nhe!")

if __name__ == "__main__":
    main()
