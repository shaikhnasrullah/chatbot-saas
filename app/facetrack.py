"""Face tracking (OpenCV Haar cascade) used to keep the speaker inside a 9:16 crop."""


def sample_face_centers(src, start, dur, step=0.5):
    """Return [(t_relative_to_clip_start, face_center_x_in_pixels or None)]."""
    import logging

    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():  # some OpenCV builds ship without the model file
        logging.getLogger("clipper.facetrack").warning(
            "Haar cascade not found; falling back to a centered crop."
        )
        return []
    cap = cv2.VideoCapture(str(src))
    out, t = [], 0.0
    try:
        while t < dur:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            scale = 480.0 / frame.shape[1] if frame.shape[1] > 480 else 1.0
            small = cv2.resize(frame, None, fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                out.append((t, (x + w / 2.0) / scale))
            else:
                out.append((t, None))
            t += step
    finally:
        cap.release()
    return out
