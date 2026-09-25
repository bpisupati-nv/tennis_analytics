"""
Tennis Distance Analytics
Usage:
    python -m tennis_analytics.main --input match.mp4 --output out.mp4

Court markings are detected automatically from several early video frames.
Both a full-court view and a half-court view (camera behind one baseline)
are recognised. Use --manual-court to click the four outer doubles-court
corners instead.

Options:
    --input        Path to input video (required)
    --output       Path to output video (default: <input>_tracked.mp4)
    --model        YOLO model weights (default: yolov8n.pt)
    --conf         Detection confidence threshold (default: 0.4)
    --players      Comma-separated track IDs to show (e.g. 1,2). If omitted,
                   the two tracks with the most detections are used.
    --manual-court Force interactive four-corner court calibration.
    --skip-court   Skip court calibration; use an approximate pixel scale.
    --court-debug  Save an image of the detected court geometry.
    --no-display   Don't show live preview window.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2

from .court import CourtMapper
from .distance import DistanceTracker
from .tracker import PlayerTracker
from .visualizer import draw_detections, draw_scoreboard


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tennis player distance analytics")
    p.add_argument("--input", required=True, help="Input video path")
    p.add_argument("--output", default=None, help="Output video path")
    p.add_argument("--model", default="yolov8n.pt", help="YOLO weights")
    p.add_argument("--conf", type=float, default=0.4, help="Detection confidence")
    p.add_argument("--players", default=None,
                   help="Comma-separated player track IDs (e.g. 1,2)")
    p.add_argument("--manual-court", action="store_true",
                   help="Force interactive four-corner court calibration")
    p.add_argument("--skip-court", action="store_true",
                   help="Skip court calibration (pixel-based estimation)")
    p.add_argument("--court-debug", default=None, metavar="PATH",
                   help="Save automatic court calibration overlay")
    p.add_argument("--no-display", action="store_true",
                   help="Disable live preview")
    return p.parse_args()


def _pixel_to_approx_world(foot_px, frame_w, frame_h):
    """
    Rough pixel → meters estimate when no court homography is available.
    Assumes the court fills ~70% of frame width (doubles: 10.97 m).
    """
    from tennis_analytics.court import COURT_WIDTH, COURT_LENGTH
    scale_x = COURT_WIDTH / (frame_w * 0.70)
    scale_y = COURT_LENGTH / (frame_h * 0.80)
    return foot_px[0] * scale_x, foot_px[1] * scale_y


def _auto_calibrate_from_video(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
) -> CourtMapper | None:
    """Try several early frames and keep the highest-scoring calibration."""
    search_end = min(
        max(total_frames - 1, 0),
        max(int(fps * 3), 1),
    )
    frame_indices = sorted({
        int(search_end * i / 5) for i in range(6)
    })
    best = None
    for frame_index in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        candidate = CourtMapper()
        if candidate.auto_calibrate(frame):
            if best is None or candidate.ranking_score > best.ranking_score:
                best = candidate
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return best


def run(args: argparse.Namespace) -> None:
    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        print(f"Error: cannot open video '{args.input}'", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    output_path = args.output or str(
        Path(args.input).with_name(Path(args.input).stem + "_tracked.mp4")
    )
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (frame_w, frame_h))

    # ── Court calibration ──────────────────────────────────────────────────
    court = CourtMapper()
    if not args.skip_court:
        if args.manual_court:
            ok, first_frame = cap.read()
            if not ok:
                print("Error: could not read first frame.", file=sys.stderr)
                sys.exit(1)
            print("Opening court calibration window...")
            print("Click: Top-Left → Top-Right → Bottom-Right → Bottom-Left")
            court.select_corners_interactive(first_frame)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            print("Manual court calibration complete.")
        else:
            print("Detecting court markings...")
            detected = _auto_calibrate_from_video(cap, fps, total_frames)
            if detected is not None:
                court = detected
                print(
                    "Automatic court calibration complete "
                    f"({court.model_name} court, "
                    f"confidence {court.auto_score:.2f})."
                )
                if court.model_name in ("near", "half"):
                    print(
                        "  Note: only one half of the court is visible. "
                        "Positions in the far half are extrapolated and are "
                        "less accurate than those in the calibrated half."
                    )
                if args.court_debug:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, debug_frame = cap.read()
                    if ok:
                        court.save_debug_overlay(debug_frame, args.court_debug)
                        print(f"Court overlay saved to: {args.court_debug}")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            elif args.no_display:
                print(
                    "Error: automatic court calibration failed. Retry without "
                    "--no-display and use --manual-court, or use --skip-court.",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                print(
                    "Automatic calibration failed; falling back to manual "
                    "corner selection."
                )
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, first_frame = cap.read()
                if not ok:
                    print("Error: could not read first frame.", file=sys.stderr)
                    sys.exit(1)
                print("Click: Top-Left → Top-Right → Bottom-Right → Bottom-Left")
                court.select_corners_interactive(first_frame)
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                print("Manual court calibration complete.")

    tracker = PlayerTracker(model_path=args.model, conf=args.conf)
    distance_tracker = DistanceTracker()

    # track_id -> detection count (for auto player selection)
    detection_counts: Counter = Counter()

    frame_idx = 0
    player_ids: set[int] | None = None
    if args.players:
        player_ids = {int(x.strip()) for x in args.players.split(",")}

    print(f"Processing {total_frames} frames...")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        detections = tracker.process_frame(frame)

        for det in detections:
            tid = det["track_id"]
            detection_counts[tid] += 1

            if court.ready:
                world_pos = court.to_world(det["foot"])
            else:
                world_pos = _pixel_to_approx_world(det["foot"], frame_w, frame_h)

            distance_tracker.update(tid, world_pos)

        # After first 150 frames, auto-pick the 2 most-seen tracks if not set
        if player_ids is None and frame_idx == 150:
            top2 = [tid for tid, _ in detection_counts.most_common(2)]
            player_ids = set(top2)
            print(f"Auto-selected players: {sorted(player_ids)}")

        elapsed = frame_idx / fps
        distances = distance_tracker.all_distances()

        vis = draw_detections(frame, detections, distances, player_ids)
        vis = draw_scoreboard(vis, distances, player_ids, elapsed)

        writer.write(vis)

        if not args.no_display:
            cv2.imshow("Tennis Analytics", vis)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("Interrupted by user.")
                break

        frame_idx += 1
        if frame_idx % 100 == 0:
            pct = frame_idx / max(total_frames, 1) * 100
            print(f"  {frame_idx}/{total_frames} frames ({pct:.1f}%)")

    cap.release()
    writer.release()
    if not args.no_display:
        cv2.destroyAllWindows()

    # ── Final report ───────────────────────────────────────────────────────
    print("\n=== Distance Summary ===")
    final_distances = distance_tracker.all_distances()
    ids_to_report = player_ids if player_ids else set(final_distances.keys())
    for tid in sorted(ids_to_report):
        d = final_distances.get(tid, 0.0)
        print(f"  Player {tid}: {d:.2f} m  ({d / 1000:.3f} km)")
    print(f"\nOutput saved to: {output_path}")


def main():
    run(parse_args())


if __name__ == "__main__":
    main()
