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

### Guitar-region detection and similarity

Install the additional local model runtime from `app`:

```sh
python -m pip install -e '.[authentication-test,guitar-detection]'
python -m ygc.guitar_image_analysis --download-model
```

The second command downloads the official `CIDAS/clipseg-rd64-refined` model at pinned
revision `999e0328d9e10b484360c477313983f9afdd7050`, using safetensors rather than pickle
weights. It saves model files under `YGC_DATA_DIR/models/clipseg-guitar` (default:
`app/data/models/clipseg-guitar`). Prepare with the same `YGC_DATA_DIR` as the Web UI.
The download requires internet access; uploaded photographs are never sent to the
model provider. Subsequent detection runs on CPU and loads local files only.
Missing runtime or weights yields an explicit unavailable result without affecting
the original OCR/photo checks. Allow several hundred MB for model weights, plus the
PyTorch runtime. Model loading is cached and inference is serialized locally.

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
- A separate Guitar Region Detection and Similarity result segments the largest
  guitar candidate with CLIPSeg, shows its masked preview, coordinates and area,
  and compares only detected guitar regions. Candidate masks use response >= 0.5
  and exclude implausibly small/whole-image regions. This is a segmentation heuristic,
  not proof that a guitar exists, and can miss a partial guitar or include background.
- Appearance similarity is cosine similarity of CLIP image embeddings of masked crops,
  displayed as a percentage. Same-model guitars can score highly. Local feature support
  uses masked SIFT features with one-to-one matches and RANSAC homography, helping inspect
  details such as wood grain or scratches. Feature scarcity is reported as insufficient.
  These percentages are neither calibrated identity probabilities nor approval thresholds.
- Compare the close-up and overview separately from comparisons of the overview against
  optional locally stored reference images. No detected guitar means no similarity score;
  there is no fallback to the whole-image diagnostics. Without references the result cannot
  assess a match to an existing guitar. A single mask is used: photos containing several
  guitars require special review. 3D viewpoint changes, low resolution and modifications
  can prevent useful correspondence.
- Calibrated individual identification and TruFor/AI forgery detection remain unimplemented.

Both uploads are limited to 12 MB and 20 megapixels. Images are resized to at most
2000 pixels per side for bounded processing. Tesseract has a 20-second per-image timeout.
The administrator-only endpoint uses the existing local Browser Console token.
Upload bytes are held for the request; OCR uses a temporary directory deleted afterward.
No images, results, users, Claims, Evidence or ownership changes are persisted.

This is an isolated measurement tool. Connecting results to Claim Evidence, approvals
or the Observation evaluator requires a separate implementation and validated thresholds.
