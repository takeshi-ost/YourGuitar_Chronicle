# Local authentication image experiment

Browser Console → Authentication Test accepts a serial close-up and a guitar overview,
both with the same challenge paper. Enter the expected challenge and serial, then select
Analyze images. Generate produces test text only: this experiment does not issue a
persisted, expiring, single-use ownership challenge.

## Installation

In the existing Python virtual environment, from `app`:

```sh
python -m pip install -e '.[authentication-test]'
```

Install the separate Tesseract executable with English language data. On macOS:

```sh
brew install tesseract
```

On Debian/Ubuntu use `sudo apt install tesseract-ocr tesseract-ocr-eng`.
On Windows install Tesseract and add its executable directory to PATH.
Restart the local Web UI after installing. Without the Python extra the endpoint
returns an installation instruction; without Tesseract other image measurements
still run and OCR is explicitly unavailable. There is no cloud API or API key.

## Measurements and limits

- Tesseract sparse-text OCR supplies recognized words, coordinates and OCR confidence.
  Challenge text must be read in both images; the serial is checked in the close-up.
  Comparison normalizes case and separators, but does not guess ambiguous characters.
  A failed reading is `not_read`, not proof of a fraudulent submission.
- OpenCV/NumPy measure non-text grayscale entropy and locally flat areas. This flags
  extremely simple images; it cannot certify photographs or detect all pasted text.
- DCT perceptual hash similarity helps inspect near-duplicate photographs.
- SIFT feature matching and RANSAC homography supply matched-feature counts and the
  percentage of keypoints geometrically supported. These are whole-image diagnostics:
  paper, text and backgrounds can match. They are not calibrated individual identity
  probabilities. Low feature counts are reported as insufficient.
- Optional Reference guitar ID compares up to five readable, locally stored positive
  Claim images. Remote Reverb images are not fetched. No reference means no existing
  guitar comparison. Upload-to-upload comparison alone cannot prove individual identity.
- Automatic guitar isolation, calibrated individual identification and TruFor/AI
  forgery detection are not implemented; their results explicitly say so.

Both uploads are limited to 12 MB and 20 megapixels. Images are resized to at most
2000 pixels per side for bounded processing. Tesseract has a 20-second per-image timeout.
The administrator-only endpoint uses the existing local Browser Console token.
Upload bytes are held for the request; OCR uses a temporary directory deleted afterward.
No images, results, users, Claims, Evidence or ownership changes are persisted.

This is an isolated measurement tool. Connecting results to Claim Evidence, approvals
or the Observation evaluator requires a separate implementation and validated thresholds.
