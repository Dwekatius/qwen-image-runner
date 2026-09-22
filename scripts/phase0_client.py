#!/usr/bin/env python
"""Phase 0 client for local sd-server (robust: JSON via requests, no shell limits).

Usage:
  python scripts/phase0_client.py t2i  --prefix NAME [--size 1024] [--steps 40] [--seed 42] [--prompt "..."]
  python scripts/phase0_client.py edit --prefix NAME --refs a.png [b.png ...] [--prompt "..."] [--mask m.png]
  python scripts/phase0_client.py cancel_queued --prefix NAME [--size 1024 ...]
  python scripts/phase0_client.py cancel_active --prefix NAME --cancel-after 10 [--size 1024 ...]
"""
import argparse, base64, json, pathlib, sys, time
import requests

try:  # Windows consoles may default to cp437/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:1235"
OUT = pathlib.Path("test-artifacts/phase0")
IMAGES = pathlib.Path("outputs")


def b64(path: str) -> str:
    return "data:image/png;base64," + base64.b64encode(pathlib.Path(path).read_bytes()).decode()


def build_payload(a) -> dict:
    p = {
        "prompt": a.prompt,
        "width": a.size, "height": a.size,
        "seed": a.seed, "batch_count": 1,
        "embed_image_metadata": True,
        "output_format": "png",
        "sample_params": {
            "scheduler": "discrete", "sample_method": "euler",
            "sample_steps": a.steps, "guidance": {"txt_cfg": a.cfg},
        },
    }
    if a.mode == "edit" and a.refs:
        p["ref_images"] = [b64(x) for x in a.refs]
    if a.mask:
        p["mask_image"] = b64(a.mask)
    return p


def submit(p: dict) -> dict:
    r = requests.post(f"{BASE}/sdcpp/v1/img_gen", json=p, timeout=60)
    r.raise_for_status()
    return r.json()


def poll(job_id: str, t0: float, poll_s: int = 3) -> dict:
    while True:
        d = requests.get(f"{BASE}/sdcpp/v1/jobs/{job_id}", timeout=15).json()
        st = d.get("status", "?")
        print(f"[{time.time()-t0:.0f}s] {st}", flush=True)
        if st in ("completed", "failed", "cancelled", "error"):
            return d
        time.sleep(poll_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["t2i", "edit", "cancel_queued", "cancel_active"])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cfg", type=float, default=6.0)
    ap.add_argument("--prompt", default="a red apple on a wooden table, studio light, photorealistic")
    ap.add_argument("--refs", nargs="*", default=[])
    ap.add_argument("--mask", default=None)
    ap.add_argument("--cancel-after", type=int, default=10)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(exist_ok=True)

    if a.mode == "cancel_queued":
        j1 = submit(build_payload(a))
        a.seed += 1
        j2 = submit(build_payload(a))
        time.sleep(2)
        r = requests.post(f"{BASE}/sdcpp/v1/jobs/{j2['id']}/cancel", timeout=15)
        print("cancel queued HTTP:", r.status_code, "|", r.text[:200])
        (OUT / f"job-{a.prefix}-cancelqueued.json").write_text(
            json.dumps({"j1": j1, "j2": j2, "cancel_http": r.status_code, "cancel_body": r.text[:500]}, indent=2))
        return

    if a.mode == "cancel_active":
        j = submit(build_payload(a))
        print("job:", j["id"], flush=True)
        time.sleep(a.cancel_after)
        r = requests.post(f"{BASE}/sdcpp/v1/jobs/{j['id']}/cancel", timeout=15)
        print("cancel active HTTP:", r.status_code, "|", r.text[:300])
        d = requests.get(f"{BASE}/sdcpp/v1/jobs/{j['id']}", timeout=15).json()
        print("status after cancel:", d.get("status"))
        (OUT / f"job-{a.prefix}-cancelactive.json").write_text(
            json.dumps({"submit": j, "cancel_http": r.status_code, "cancel_body": r.text[:500], "after": d}, indent=2))
        return

    t0 = time.time()
    j = submit(build_payload(a))
    print("job:", j["id"], flush=True)
    d = poll(j["id"], t0)
    (OUT / f"job-{a.prefix}.json").write_text(json.dumps(d, indent=2))
    print("WALL: %.0fs" % (time.time() - t0))
    if d.get("status") == "completed":
        img = base64.b64decode(d["result"]["images"][0]["b64_json"])
        (IMAGES / f"phase0-{a.prefix}.png").write_bytes(img)
        print(f"saved outputs/phase0-{a.prefix}.png")
    else:
        print("FAILED:", d.get("error"))


if __name__ == "__main__":
    main()
