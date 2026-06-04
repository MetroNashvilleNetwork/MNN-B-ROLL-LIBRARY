# Feeding MNN Clipper AI metadata into the B-Roll Library

The B-Roll Library can use the **AI breakdown** your MNN Clipper already produces
(tags + description) to make clips **searchable by content** and to
**auto-categorize them more accurately** — without re-analyzing any video, so it
stays fully offline and no footage leaves MNN.

All the Clipper needs to do is **write a small metadata file** that lives with the
footage. The B-Roll indexer reads it on the next re-index.

---

## Option A — one manifest file (recommended)

Write a single JSON file named **`_mnn_broll_metadata.json`** at the **root of the
footage drive**:

```
X:\2026 Metro Nashville Archive B-Roll Footage\_mnn_broll_metadata.json
```

(You can also put it elsewhere and point to it with `"metadata_manifest"` in
`config.json`.)

### Format

```json
{
  "version": 1,
  "clips": [
    {
      "filename": "blodgett-oven-closeup-commercial-kitchen.mov",
      "description": "Close-up of a Blodgett commercial oven in a restaurant kitchen.",
      "tags": ["oven", "stainless steel", "commercial kitchen", "appliance"],
      "category": "kitchen",
      "location": "The Commissary"
    },
    {
      "filename": "podium-wide-shot-city-council.mov",
      "description": "Wide shot of a speaker at a podium during a city council meeting.",
      "tags": ["podium", "city council", "microphone", "audience"]
    }
  ]
}
```

### Field reference

| Field | Required | Notes |
|-------|----------|-------|
| `filename` | **yes** | The file's name **as it appears on the drive** (after the Clipper renames it). Matched case-insensitively. |
| `description` | no | One-line AI caption. Shown in the detail view and made searchable. (`caption` also accepted.) |
| `tags` | no | The AI tags/labels. A JSON array **or** a comma-separated string. Made searchable. (`keywords`/`labels` also accepted.) |
| `category` | no | Optional category key (see list below). If omitted, the library auto-picks one from the tags + description. |
| `location` | no | Optional; folded into search. |
| `path` | no | Optional path relative to the footage root, e.g. `"Gil/July/clip.mov"`. Use it if two clips share a filename. |

Extra fields are ignored, so it's safe to include whatever else the Clipper
exports.

**Valid `category` keys:** `corporate`, `education`, `water`, `courts`,
`healthcare`, `kitchen`, `nature`, `weather`, `aerial`, `people`, `finance`,
`city`, `architecture`. (Leave it out to let the library decide.)

> Tip: your Clipper already has **Export CSV / Export Excel**. The easiest
> implementation is to add an **"Export B-Roll metadata (JSON)"** that writes this
> exact shape. If JSON is hard, tell me and I'll add CSV support to the importer.

---

## Option B — per-file sidecars

Instead of one manifest, the Clipper can drop a small file **next to each clip**,
named `<the video's full filename>.mnn.json`:

```
…\Gil\July\blodgett-oven-closeup-commercial-kitchen.mov
…\Gil\July\blodgett-oven-closeup-commercial-kitchen.mov.mnn.json
```

Each sidecar holds a single clip object (same fields; `filename` optional):

```json
{
  "description": "Close-up of a Blodgett commercial oven.",
  "tags": ["oven", "commercial kitchen", "stainless steel"],
  "category": "kitchen"
}
```

Sidecars override the manifest if both exist for a clip.

---

## How it shows up

1. The Clipper writes the manifest (or sidecars).
2. In the B-Roll Library, click **Re-index** (or wait for the daily run).
3. Each clip then:
   - is **searchable by its tags + description** (e.g. typing "microphone" finds a
     clip whose only mention of it is in the AI tags),
   - lands in a **better category**, and
   - shows its **description + clickable tags** in the detail view.

Files use **UTF-8**. Nothing is sent anywhere — the metadata is read locally,
exactly like the filenames.
