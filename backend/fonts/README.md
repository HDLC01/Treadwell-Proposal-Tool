# backend/fonts/ holds no font in git

The proposal templates are typeset in **Zetta Serif**, Treadwell's brand face. It is a
LICENSED font and this repository is public, so the files are not committed here and no image
built from this tree carries them. `.gitignore` and `.dockerignore` both drop every font file.

The app needs exactly these two files, by these names:

| File                   | Family (name table)  | Weight |
|------------------------|----------------------|--------|
| `Zetta Serif-Book.otf` | `Zetta Serif Book`   | 345    |
| `Zetta Serif.otf`      | `Zetta Serif`        | 400    |

Where they come from: Kyle's licensed copy, kept off GitHub. Ask Hanz for it.

Where they go:

* **VPS (staging and prod):** `/opt/treadwell-fonts/` on the host. Both compose files bind-mount
  that directory read-only onto `/usr/share/fonts/truetype/treadwell` in the container, where
  LibreOffice (PDF export) and `GET /api/proposal-font/{name}` (the editor) both read it. The
  deploy workflow refuses to deploy when either file is missing there.
* **Dev box:** this directory. `backend/proposal_fonts.py` reads the mount first, then here.

Without them the app still starts. It logs one `WARNING` line saying the font is missing, the PDF
prints in a substitute font (Liberation Sans, in the image), and the editor falls back to Georgia.
