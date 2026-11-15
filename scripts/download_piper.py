import os
import sys
import io
import urllib.request
import zipfile

def setup_piper(dest_dir: str):
    os.makedirs(dest_dir, exist_ok=True)
    piper_exe = os.path.join(dest_dir, "piper.exe")
    if os.path.exists(piper_exe) and os.path.getsize(piper_exe) > 100000:
        print(f"Piper already installed at {dest_dir}")
        return True

    url = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
    print(f"Downloading Piper Windows binary from {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()

    print("Extracting Piper...")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.infolist():
            filename = member.filename
            if filename.startswith("piper/"):
                filename = filename[6:]
            if not filename:
                continue
            target = os.path.join(dest_dir, filename)
            if member.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(z.read(member))

    print(f"Piper extracted successfully to {dest_dir}")
    return True

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "piper")
    setup_piper(target_dir)
