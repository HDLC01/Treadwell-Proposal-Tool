# backend/fonts/ holds no font in git

The proposal templates are typeset in **Zetta Serif**, Treadwell's brand face. It is a
LICENSED font and this repository is public, so the files are not committed here and no image
built from this tree carries them. `.gitignore` and `.dockerignore` both drop every font file.

The app needs exactly these two files, by these names:

| File                   | Family (name table)  | Weight | sha256                                                             |
|------------------------|----------------------|--------|--------------------------------------------------------------------|
| `Zetta Serif-Book.otf` | `Zetta Serif Book`   | 345    | `646d78aa67025a11814d95e7f39ca7151ee1f52e6fb9d6aaca702e852963c581` |
| `Zetta Serif.otf`      | `Zetta Serif`        | 400    | `e4bcfb85ab4a059b4800a68317b4468d2df6d0abe96e79a9ad90b2a8d59971ac` |

## Where they come from

Treadwell's own licensed kit, in the team Dropbox (the FontFont order and its EULA sit in the
same `Fonts` folder):

    /2023 Treadwell Team Folder/Office/Technology/Fonts/Zetta_ForText/

That folder holds both files under exactly these names. `Zetta_ForText.zip` beside it holds the
same two. On a machine with the Dropbox app they are under `Treadwell Dropbox\` in the user's home
folder. Check any copy against the sha256 column before you use it: `backend/tests/test_proposal_fonts.py`
pins the same hashes.

This Dropbox folder is the only lasting copy. Git deletes the files from every checkout that moves
past the commit that untracked them (the VPS checkouts too, at their next `git pull`), and
`git worktree remove` deletes ignored files without asking.

## Where they go

* **VPS (staging and prod):** `/opt/treadwell-fonts/` on the host. Both compose files bind-mount
  that directory read-only onto `/usr/share/fonts/truetype/treadwell` in the container, where
  LibreOffice (PDF export) and `GET /api/proposal-font/{name}` (the editor) both read it.
  Every deploy path (the staging and prod steps of `.github/workflows/deploy.yml`, and
  `deploy/ship.sh`) first copies a file that is missing there from its own checkout's
  `backend/fonts/`, then refuses to go on while either file is still missing. The copy matters
  once: before the first pull past this change, the VPS checkouts still track the files and that
  pull deletes them. After that, a new box needs them copied in from Dropbox.
* **Dev box:** this directory. `backend/proposal_fonts.py` reads the mount first, then here. Copy
  them in from Dropbox.

Without them the app still starts. It logs one `WARNING` line saying the font is missing, the PDF
prints in a substitute font (Liberation Sans, in the image), and the editor falls back to Georgia.
