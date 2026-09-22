# Decision Model Benchmark

Generated: 2026-09-21T16:36:15.644552+00:00

Dataset: 520 labelled shipping emails. Shared task: five-class email routing.

| Model | Accuracy | Macro F1 | Median batch | Effective time/email | Input tokens | Output tokens | Reported cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jev | 98.85% | 0.9821 | 738 ms | 25.3 ms | 319,107 | 32,947 | $0.013402 |
| Gemini | 99.81% | 0.9987 | 1797 ms | 59.0 ms | 172,044 | 17,262 | Not returned |

## Scope

This is a routing benchmark because classification is the capability shared by both models. It does not compare OCR, image understanding, field extraction, or reply generation; Jev does not generate open-ended text.

The models received the same subject, sender, email body (capped at 3,000 characters), and attachment file names. Attachment contents were not sent. Calls used batches and deterministic settings where supported.

Reported confidence is stored for inspection but should not be compared as if it were the same measurement: Jev returns a probability-derived confidence, while Gemini self-reports confidence in generated JSON.

## Jev confidence routing

| Threshold | Auto coverage | Accuracy of auto cases | Fallback cases |
|---:|---:|---:|---:|
| 0.60 | 98.85% | 99.61% | 6 |
| 0.70 | 98.65% | 99.81% | 7 |
| 0.80 | 98.46% | 99.80% | 8 |
| 0.90 | 97.31% | 100.00% | 14 |

## Jev category results

| Category | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| BL_COMPARISON | 100.00% | 100.00% | 1.0000 | 220 |
| SI_REQUEST | 100.00% | 100.00% | 1.0000 | 125 |
| INVOICE_QUERY | 100.00% | 92.00% | 0.9583 | 75 |
| GENERAL | 90.91% | 100.00% | 0.9524 | 60 |
| SPAM | 100.00% | 100.00% | 1.0000 | 40 |

## Gemini category results

| Category | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| BL_COMPARISON | 100.00% | 99.55% | 0.9977 | 220 |
| SI_REQUEST | 99.21% | 100.00% | 0.9960 | 125 |
| INVOICE_QUERY | 100.00% | 100.00% | 1.0000 | 75 |
| GENERAL | 100.00% | 100.00% | 1.0000 | 60 |
| SPAM | 100.00% | 100.00% | 1.0000 | 40 |
