import os
import sys
import time
import queue
import shutil
import argparse
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

msg_queue = queue.Queue()

def update_worker(pid, source_dir, target_dir, target_exe):
    try:
        msg_queue.put(("progress", ("Closing previous session...", 15)))

        # Wait for old PID to exit
        if pid and pid > 0:
            for _ in range(12):
                res = subprocess.run(
                    ["tasklist", "/fi", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
                if str(pid) not in res.stdout:
                    break
                time.sleep(0.3)
            else:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    creationflags=0x08000000
                )
                time.sleep(0.5)

        time.sleep(0.5)

        msg_queue.put(("progress", ("Preparing update files...", 30)))

        files_to_copy = []
        for root_dir, _, files in os.walk(source_dir):
            for f in files:
                src_f = os.path.join(root_dir, f)
                rel = os.path.relpath(src_f, source_dir)
                dst_f = os.path.join(target_dir, rel)
                files_to_copy.append((src_f, dst_f))

        total = len(files_to_copy)
        msg_queue.put(("progress", ("Installing application files...", 40)))

        this_exe = os.path.abspath(sys.executable).lower()

        for idx, (src_f, dst_f) in enumerate(files_to_copy):
            # Skip replacing running updater executable itself
            if os.path.abspath(dst_f).lower() == this_exe:
                continue

            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            copied = False
            for _ in range(5):
                try:
                    shutil.copy2(src_f, dst_f)
                    copied = True
                    break
                except (PermissionError, OSError):
                    try:
                        old_name = dst_f + f".old_{int(time.time())}"
                        if os.path.exists(dst_f):
                            os.rename(dst_f, old_name)
                        shutil.copy2(src_f, dst_f)
                        copied = True
                        break
                    except Exception:
                        time.sleep(0.2)

            pct = 40 + int((idx / max(total, 1)) * 55)
            msg_queue.put(("progress", ("Installing application files...", pct)))

        # Clean up old leftover files
        for root_dir, _, files in os.walk(target_dir):
            for f in files:
                if ".old_" in f:
                    try:
                        os.remove(os.path.join(root_dir, f))
                    except Exception:
                        pass

        msg_queue.put(("progress", ("Update complete! Restarting...", 100)))
        time.sleep(0.8)

        # Launch target executable with proper working directory
        if os.path.exists(target_exe):
            subprocess.Popen(
                [target_exe],
                cwd=target_dir,
                creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
                close_fds=True
            )

        time.sleep(0.4)
        msg_queue.put(("done", None))

    except Exception as e:
        msg_queue.put(("error", str(e)))

def main():
    parser = argparse.ArgumentParser(description="TTS Live Studio Updater")
    parser.add_argument("--pid", type=int, default=0, help="PID of previous app to terminate/wait for")
    parser.add_argument("--source", type=str, required=True, help="Extracted source folder")
    parser.add_argument("--target", type=str, required=True, help="Target application folder")
    parser.add_argument("--exe", type=str, required=True, help="Target executable path")
    parser.add_argument("--version", type=str, default="", help="Target version string")
    args = parser.parse_args()

    root = tk.Tk()
    root.title("TTS Live Studio - Update")
    root.geometry("440x210")
    root.resizable(False, False)
    root.configure(bg="#000000")

    # Center window
    root.update_idletasks()
    w, h = 440, 210
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

    ver_str = f" to {args.version}" if args.version else ""
    lbl_title = tk.Label(
        root,
        text=f"Updating TTS Live Studio{ver_str}",
        font=("Segoe UI", 12, "bold"),
        fg="#f1f5f9",
        bg="#000000"
    )
    lbl_title.pack(pady=(24, 6))

    status_var = tk.StringVar(value="Initializing update...")
    lbl_status = tk.Label(
        root,
        textvariable=status_var,
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#0b0f19"
    )
    lbl_status.pack(pady=(0, 14))

    p_frame = tk.Frame(root, bg="#0b0f19")
    p_frame.pack(fill="x", padx=36, pady=(0, 8))

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
        length=310,
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

    lbl_note = tk.Label(
        root,
        text="Please wait while the update finishes installing.",
        font=("Segoe UI", 8),
        fg="#64748b",
        bg="#0b0f19"
    )
    lbl_note.pack(pady=(8, 0))

    def poll_queue():
        try:
            while not msg_queue.empty():
                mtype, mdata = msg_queue.get_nowait()
                if mtype == "progress":
                    st, pct = mdata
                    status_var.set(st)
                    pct_var.set(f"{pct}%")
                    progress_var.set(pct)
                elif mtype == "done":
                    root.destroy()
                    sys.exit(0)
                elif mtype == "error":
                    status_var.set(f"Update failed: {mdata}")
                    pct_var.set("Error")
                    root.after(3500, lambda: (root.destroy(), sys.exit(1)))
                    return
        except Exception:
            pass
        root.after(50, poll_queue)

    worker_thread = threading.Thread(
        target=update_worker,
        args=(args.pid, args.source, args.target, args.exe),
        daemon=True
    )
    worker_thread.start()

    root.after(50, poll_queue)
    root.mainloop()

if __name__ == "__main__":
    main()
