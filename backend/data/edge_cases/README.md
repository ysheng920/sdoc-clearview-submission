# Edge cases — image extraction

Manual test set for the **extraction** stage (OCR / VLM) on scanned and
handwritten documents. **Deliberately excluded from `data/ground_truth.json`**
and from the benchmark gate — nothing here is scored by CI.

```
images/       the six source screenshots (*.webp) plus each panel cropped out
              on its own: edge_00N_{email,SI,BL}.png
scans/        each SI/BL crop wrapped in a single-page, image-only PDF
inbox/        edge_00N.json      -> the .txt attachments  (text path)
              edge_00N_scan.json -> the .pdf attachments  (VLM fallback path)
emails/       the same emails as plain text, for pasting into /api/simulate
attachments/  SI and BL transcriptions — what a PERFECT extractor should read
expected.json per-case expected extraction, comparison and verdict
```

### Pasting an email into the simulator

`emails/edge_00N.txt` holds one email with `Sender:` and `Subject:` on their own
lines and the body verbatim after a single `===== BODY =====` marker — the three
fields the simulate form asks for, kept apart so each is one copy. Each file also
lists which attachment pair to upload and the role to set. `emails/all_emails.txt`
is the six concatenated, when copying in one go beats opening six files.

These are generated from `inbox/*.json`; `check_edge_cases.py` fails if a sender,
subject or body drifts from the JSON it came from.

Run the whole folder through the pipeline by pointing the data dir at it — one
run covers 12 emails, the six text cases and their six scan twins:

```bash
SDOC_DATA_DIR=backend/data/edge_cases python -m app.main
```

### Testing the VLM fallback

`scans/*.pdf` carry no text layer, so `read_text()` raises `UnreadableDocument`
and `extract()` drops into `_read_visually()` — the real fallback path, no code
changes needed. Verified: `extract()` on `scans/edge_001_SI.pdf` reaches the
`vision` step and hands the model a 72 KB page image.

To hit a model directly instead, the bare crops are in `images/`:

```bash
python -c "from pathlib import Path; from app.engines.extract import extract; \
print(extract(Path('data/edge_cases/scans/edge_004_BL.pdf'))[0])"
```

Check that the transcriptions and `expected.json` still agree (no model, no network):

```bash
python backend/data/edge_cases/check_edge_cases.py
```

## The six cases

| Case | Hard part | Expected verdict |
|---|---|---|
| `edge_001` Malay | Malay email, photographed paper, chop over text | **MISMATCH** — containers 3→4 x 20'GP, weight 66,000→88,000 |
| `edge_002` Chinese | Chinese email, bilingual forms, shipper printed in Chinese only | **OK** — all seven agree |
| `edge_003` Tamil | Tamil email; weight split over two cargo rows with no total; SI states no container count | **NEEDS_REVIEW** — `container_count` absent from the SI |
| `edge_004` amended | Typed docs, handwritten overrides — the handwriting **creates** the mismatch | **MISMATCH** — `container_count` (SI 3, BL amended to 4) |
| `edge_005` handwritten | Both documents entirely cursive; 3-row container table; count written in words | **MISMATCH** — `notify_party`, `gross_weight_kg` (72,500 vs 72,300) |
| `edge_006` CN amended | Chinese forms, Chinese handwritten amendments — the handwriting **resolves** the mismatch | **OK** — all seven agree after the amendments |

`edge_004` and `edge_006` are the pair that matters: the same kind of
strikethrough leads to opposite answers. Ignore the handwriting in `004` and you
report a weight mismatch that isn't there while missing the container one;
ignore it in `006` and you raise two false discrepancies on a clean pair. Both
carry a `printed_only_variant` block in `expected.json` spelling out exactly what
a strikethrough-blind extractor would report instead.

`edge_005` has no email in its source image — `inbox/edge_005.json` carries a
synthetic covering note so the case can run end to end. It is marked
`"synthetic_email": true`.

## expected.json

Per case, per document, per field:

- `raw` — what a perfect extractor should read off the image. Where a printed
  value is struck through and replaced by hand, **the handwritten value wins**.
- `normalised` — that raw put through `app/engines/normalize.py`.
- `label_parser` — what the deterministic label parser actually gets out of the
  transcription today. Often less than `raw`; the gap is the finding.

Then `expected_comparison` (per-field verdict and the rule that produced it),
`expected_row` (the human-truth verdict for the case), and, where the current
code disagrees with that truth, `current_code_row` plus the reason.

## Gaps these cases already expose

Found by running the transcriptions through the real engines, not by inspection:

1. **`docs.py` `_LABEL_LINE` requires a label to start with `[A-Za-z]`.** A
   bilingual label written CJK-first (`发货人 / Shipper:`) never matches, so the
   deterministic parser returns **nothing at all** for `edge_002`, `005` and
   `006` — every field on those falls through to the model.
2. **`norm_entity()` / `norm_port()` strip all non-Latin characters.** A value
   printed only in Chinese normalises to `None` and is reported absent instead of
   compared. This alone turns `edge_002` and `edge_006` from OK into
   NEEDS_REVIEW.
3. **`norm_containers()` needs a leading digit.** `THREE (3) X 40HQ` on the
   `edge_005` BL normalises to `None`, so the count is called missing even though
   both documents say three.
4. **`field_for_label()` containment rule is too loose.** The `edge_004` SI has a
   `To :` addressee block; `to` is contained in the consignee alias
   `to the order of`, so the parser reads Sdoc Clearview's own address as the
   consignee.
5. **`extract.py:149` labels every page image `data:image/png`** regardless of
   what the PDF actually embeds. These scans embed JPEG, so the dashboard gets a
   data URI whose MIME type is wrong. Pre-existing — the existing scanned PDFs in
   `data/attachments/` hit it too; browsers sniff past it.

## What else to watch when testing the images

- Does the extractor pick the **handwritten** value or the struck-through
  printed one? (`004`, `005`, `006`)
- Multi-line cargo tables needing a **sum**, not a first-row read (`003`).
- Stamps and chops overlapping printed fields (`001`, `006`).
- Per-container rows vs the BL total (`005`) — the totals must reconcile.
- Physically absurd but *agreeing* figures: 20 x 40'GP at 22,000 KGS in `002`,
  4 x 40'HQ of palm oil at 22,500 KGS in `006`. Field comparison says match; a
  cargo plausibility check, if you add one, should fire.
- `edge_006`'s BL is stamped 草稿 (DRAFT) but its `提单种类` field says 正本
  (ORIGINAL), and the sender's domain (`greenpalmtrading.com`) does not match the
  issuing company (Ocean Palm Trading).
- `edge_001`'s BL voyage prints as `SB0S2` where the SI says `SB052` — a 0/O,
  5/S trap, though voyage is not one of the seven compared fields.
