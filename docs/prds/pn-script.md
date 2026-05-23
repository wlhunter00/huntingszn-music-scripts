# PRD: pn-script (Platinum Notes filename cleanup)

**Status:** Lost — recreate.

## Purpose

Bulk-rename files under Platinum Notes: remove `_pn` suffix from filenames (walk tree, rename in place).

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Root | `G:\Platnium Notes` | `$MUSIC_DRIVE_ROOT/Platnium Notes` |

## Dependencies

- stdlib only (`os`, `pathlib`)

## Behavior

```python
# Simplified from memory
for subdir, dirs, files in os.walk(root):
    for file in files:
        os.chdir(subdir)  # fragile — prefer Path.rename with full paths
        os.rename(file, file.replace('_pn', ''))
```

## Recreation notes

- **~287 bytes** — trivial.
- Fix: use `Path(root).rglob("*")` without `chdir`.
- Makefile: `make pn-cleanup` with `--dry-run`.
