import os
import sys
import time
import shutil
import argparse
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

def run_update(pid, source_dir, target_dir, target_exe, version, status_var, pct_var, progress_var, root):
    def update_task():
        try:
            # Step 1: Wait for main app process to close
            status_var.set("Closing previous session...")
            pct_var.set("15%")
            progress_var.set(15)
            root.update_idletasks()

            if pid and pid > 0:
                for _ in range(10):
                    res = subprocess.run(
                        ["tasklist", "/fi", f"PID eq {pid}"],
                        capture_output=True,
                        text=True,
                        creationflags=0x08000000  # CREATE_NO_WINDOW
                    )
                    if str(pid) not in res.stdout:
                        break
                    time.sleep(0.4)
                else:
                    # Force kill lingering process if needed
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        creationflags=0x08000000
                    )
                    time.sleep(0.8)

            # Wait for file handles to be released
            time.sleep(0.8)

            # Step 2: Discover all files to copy
            status_var.set("Preparing update files...")
            pct_var.set("30%")
            progress_var.set(30)
            root.update_idletasks()

            files_to_copy = []
            for root_dir, _, files in os.walk(source_dir):
                for f in files:
                    src_f = os.path.join(root_dir, f)
                    rel = os.path.relpath(src_f, source_dir)
                    dst_f = os.path.join(target_dir, rel)
                    files_to_copy.append((src_f, dst_f))

            total = len(files_to_copy)

            # Step 3: Copy files with locked-file fallback
            status_var.set("Installing application files...")
            root.update_idletasks()

            for idx, (src_f, dst_f) in enumerate(files_to_copy):
                os.makedirs(os.path.dirname(dst_f), exist_ok=True)
                copied = False
                for attempt in range(5):
                    try:
                        shutil.copy2(src_f, dst_f)
                        copied = True
                        break
                    except (PermissionError, OSError):
                        try:
                            # Windows allows renaming locked running executables/DLLs
                            old_path = dst_f + f".old_{int(time.time())}"
                            if os.path.exists(dst_f):
                                os.rename(dst_f, old_path)
                            shutil.copy2(src_f, dst_f)
                            copied = True
                            break
                        except Exception:
                            time.sleep(0.3)

                pct = 30 + int((idx / max(total, 1)) * 60)
                progress_var.set(pct)
                pct_var.set(f"{pct}%")
                if idx % 8 == 0 or idx == total - 1:
                    root.update_idletasks()

            # Step 4: Cleanup obsolete .old files
            for root_dir, _, files in os.walk(target_dir):
                for f in files:
                    if ".old_" in f:
                        try:
                            os.remove(os.path.join(root_dir, f))
                        except Exception:
                            pass

            # Step 5: Finalize and restart
            status_var.set("Update complete! Restarting...")
            pct_var.set("100%")
            progress_var.set(100)
            root.update_idletasks()
            time.sleep(1.0)

            # Relaunch the application
            if os.path.exists(target_exe):
                subprocess.Popen(
                    [target_exe],
                    creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                    close_fds=True
                )

            time.sleep(0.4)
            root.destroy()
            sys.exit(0)

        except Exception as e:
            status_var.set(f"Update failed: {e}")
            pct_var.set("Error")
            root.update_idletasks()
            time.sleep(4.0)
            root.destroy()
            sys.exit(1)

    t = threading.Thread(target=update_task, daemon=True)
    t.start()

def main():
    parser = argparse.ArgumentParser(description="TikTok Live TTS Studio Updater")
    parser.add_argument("--pid", type=int, default=0, help="PID of previous app to terminate/wait for")
    parser.add_argument("--source", type=str, required=True, help="Extracted source folder")
    parser.add_argument("--target", type=str, required=True, help="Target application folder")
    parser.add_argument("--exe", type=str, required=True, help="Target executable path")
    parser.add_argument("--version", type=str, default="", help="Target version string")
    args = parser.parse_args()

    root = tk.Tk()
    root.title("TikTok Live TTS Studio - Update")
    root.geometry("450x220")
    root.resizable(False, False)
    root.configure(bg="#0b0f19")

    # Center window
    root.update_idletasks()
    w = 450
    h = 220
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")

    try:
        icon_path = os.path.join(args.target, "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = "icon.ico"
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
    except Exception:
        pass

    # Header Card
    ver_str = f" to {args.version}" if args.version else ""
    title_lbl = tk.Label(
        root,
        text=f"🎙️ Updating TikTok Live TTS Studio{ver_str}",
        font=("Segoe UI", 12, "bold"),
        fg="#f1f5f9",
        bg="#0b0f19"
    )
    title_lbl.pack(pady=(26, 6))

    # Status Label
    status_var = tk.StringVar(value="Initializing update...")
    status_lbl = tk.Label(
        root,
        textvariable=status_var,
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#0b0f19"
    )
    status_lbl.pack(pady=(0, 14))

    # Custom Progress Bar Frame
    p_frame = tk.Frame(root, bg="#0b0f19")
    p_frame.pack(fill="x", padx=40, pady=(0, 8))

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor="#1e293b",
        background="#06b6d4",
        bordercolor="#0b0f19",
        lightcolor="#38bdf8",
        darkcolor="#0891b2",
        thickness=10
    )

    progress_var = tk.DoubleVar(value=5)
    progress_bar = ttk.Progressbar(
        p_frame,
        variable=progress_var,
        maximum=100,
        length=320,
        style="Modern.Horizontal.TProgressbar"
    )
    progress_bar.pack(side="left", fill="x", expand=True)

    pct_var = tk.StringVar(value="5%")
    pct_lbl = tk.Label(
        p_frame,
        textvariable=pct_var,
        font=("Segoe UI", 9, "bold"),
        fg="#38bdf8",
        bg="#0b0f19",
        width=5,
        anchor="e"
    )
    pct_lbl.pack(side="right", padx=(8, 0))

    # Note footer
    note_lbl = tk.Label(
        root,
        text="Please wait while the update is verified and installed.",
        font=("Segoe UI", 8),
        fg="#64748b",
        bg="#0b0f19"
    )
    note_lbl.pack(pady=(8, 0))

    run_update(args.pid, args.source, args.target, args.exe, args.version, status_var, pct_var, progress_var, root)
    root.mainloop()

if __name__ == "__main__":
    main()
